/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Footer layout calculations.
 * Centralized height calculation to eliminate code duplication.
 */

#include <algorithm>
#include <cmath>

#include "MEM_guardedalloc.h"

#include "BLF_api.hh"

#include "UI_interface.hh"

#include "DNA_scene_types.h"
#include "DNA_userdef_types.h"

#include "RNA_access.hh"

#include "mixie_chat_footer_constants.hh"
#include "mixie_chat_footer_intern.hh"
#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Dynamic Input Line Count
 * \{ */

int footer_layout_get_input_line_count(Scene *scene, int region_width)
{
  if (!scene) {
    return FOOTER_INPUT_LINE_COUNT;
  }

  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *prop = RNA_struct_find_property(&scene_ptr, "mixie_chat_input");
  if (!prop) {
    return FOOTER_INPUT_LINE_COUNT;
  }

  const int text_len = RNA_property_string_length(&scene_ptr, prop);
  if (text_len == 0) {
    return FOOTER_INPUT_LINE_COUNT;
  }

  char *text = static_cast<char *>(MEM_new_uninitialized(text_len + 1, __func__));
  RNA_property_string_get(&scene_ptr, prop, text);

  /* Calculate available width for text wrapping. Must match what
   * widget_draw_text_multiline() in interface_widgets.cc actually wraps at:
   * the button rect is region_width - side_padding*2 (calculate_positions,
   * from the SAME theme cache), widget_draw_text_icon() then insets the
   * left edge by button_text_padding() while the field is edited, and the
   * painter takes another 4*pixelsize. Counting at any other width sizes
   * the box for rows the painter never fills, which the user sees as blank
   * "line breaks" under a pasted paragraph that no key can delete. */
  const float scale = UI_SCALE_FAC;
  const FooterThemeCache *theme = footer_cache_get_theme();
  const int side_padding = int(theme->side_padding * scale);
  const int input_w = region_width - side_padding * 2;
  const int text_padding = int(FOOTER_TEXT_MARGIN_X * U.widget_unit + 0.5f);
  const int rect_width = std::max(input_w - text_padding - int(4.0f * U.pixelsize), 10);

  int visual_line_count;
  if (rect_width > 10) {
    /* The painter draws the plain widget font ("Preserve the native widget
     * font. Hit testing reads this exact style."). It used to be 1.2x, and
     * this counter kept that factor after the painter dropped it, so every
     * wrapped paragraph counted ~20% more lines than were drawn. */
    uiFontStyle fstyle = ui::style_get()->widget;
    ui::fontstyle_set(&fstyle);
    const int fontid = fstyle.uifont_id;

    /* Use BLF_string_wrap with the same mode as the widget rendering */
    blender::Vector<blender::StringRef> lines = BLF_string_wrap(
        fontid,
        blender::StringRef(text, text_len),
        rect_width,
        BLFWrapMode(int(BLFWrapMode::Typographical) | int(BLFWrapMode::HardLimit)));

    visual_line_count = int(lines.size());

    /* Account for trailing \n adding a virtual line (matches widget behavior) */
    if (text_len > 0 && text[text_len - 1] == '\n') {
      visual_line_count++;
    }

    /* Ensure at least 1 line */
    visual_line_count = std::max(1, visual_line_count);
  }
  else {
    /* Fallback: just count newlines when width is too small */
    visual_line_count = 1;
    for (int i = 0; i < text_len; i++) {
      if (text[i] == '\n') {
        visual_line_count++;
      }
    }
  }

  MEM_delete_void(static_cast<void *>(text));

  return std::max(FOOTER_INPUT_LINE_COUNT,
                  std::min(visual_line_count, FOOTER_INPUT_MAX_LINE_COUNT));
}

int footer_layout_input_row_base(int input_line_count)
{
  const int effective_lines = (input_line_count > 0) ? input_line_count : FOOTER_INPUT_LINE_COUNT;
  /* Mirror widget_draw_text_multiline(): one row is the widget font's "Wg"
   * height plus 2*pixelsize, the top of the field is inset 4*pixelsize, and
   * visible_lines = floor((box - inset) / row). Reserve the exact rows plus
   * a little slack so integer rounding of the scaled height never floors a
   * row away or leaves a spare, empty one under the text. */
  uiFontStyle fstyle = ui::style_get()->widget;
  ui::fontstyle_set(&fstyle);
  const float row_f = BLF_height(fstyle.uifont_id, "Wg", 2) + 2.0f * U.pixelsize;
  const float row = std::max(float(int(row_f)), 1.0f);
  const float scale = UI_SCALE_FAC;
  const float top_inset = 4.0f * U.pixelsize;
  const float scaled = float(effective_lines) * row + top_inset + 2.0f * U.pixelsize + scale;
  return std::max(int(std::ceil(scaled / scale)), 1);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Height Calculation
 * \{ */

/**
 * Calculate required footer height based on pending attachments.
 * CRITICAL: Returns UNSCALED units - Blender applies UI_SCALE_FAC when creating window rectangle.
 *
 * This is the single source of truth for footer height calculation.
 * Called by both layout and draw functions to ensure consistency.
 *
 * \param scene: Scene containing pending attachments
 * \param theme: Cached theme values (pass nullptr to fetch fresh)
 * \param out_has_overflow: Set to true if height exceeds maximum limit (optional)
 * \return Required height in unscaled units
 */
int footer_layout_calculate_height(Scene *scene,
                                    const struct FooterThemeCache *theme,
                                    bool *out_has_overflow,
                                    int input_line_count,
                                    int mention_row_count,
                                    int region_width)
{
  /* Get cached theme if not provided */
  if (!theme) {
    theme = footer_cache_get_theme();
  }

  /* Get pending attachment count from cache */
  int pending_count = footer_cache_get_attachment_count(scene);

  /* Sanity check for attachment count */
  if (pending_count < 0 || pending_count >= FOOTER_MAX_ATTACHMENT_COUNT) {
    pending_count = 0;
  }

  /* Get UI scale for unscaling operations */
  const float scale = UI_SCALE_FAC;

  /* Extract unscaled values from theme cache */
  const int row_height_base = int(theme->button_row_height);
  /* Dynamic input height: use provided line count, or fall back to theme default */
  const int input_row_base = footer_layout_input_row_base(input_line_count);
  const int thumb_size_base = int(theme->thumbnail_size);
  const int bottom_padding_base = int(theme->bottom_padding / scale);
  const int row_spacing_base = int(theme->row_spacing);
  const int top_padding_base = int(theme->top_padding);
  const int thumb_top_margin_base = int(theme->thumbnail_top_margin);
  const int main_footer_gap_base = int(theme->main_footer_gap);

  /* '@' mention dropdown block above the input (0 when closed):
   * gap + panel padding + N suggestion rows. */
  const int mention_block_base =
      (mention_row_count > 0) ? (FOOTER_MENTION_GAP_BASE + FOOTER_MENTION_PANEL_PAD_BASE * 2 +
                                 FOOTER_MENTION_ROW_H_BASE * mention_row_count) :
                                0;

  /* Bottom-up height calculation (TWO-ROW LAYOUT) - ALL IN UNSCALED UNITS:
   *
   * Without thumbnails:
   *   bottom_padding + button_row + row_spacing + input_row(3x) + gap + top_padding
   *
   * With thumbnails:
   *   bottom_padding + button_row + row_spacing + input_row(3x) + gap + thumb_top_margin + thumb_size + top_padding
   *
   * Layout from bottom to top:
   * 1. Bottom padding (theme)
   * 2. Button row (row_height_base) — single row for buttons
   * 3. Row spacing (theme)
   * 4. Input row (row_height_base * FOOTER_INPUT_LINE_COUNT) — multi-line input
   * 5. Main-footer gap (theme) - internal spacing above input
   * 6a. Top padding (theme) - space above input when no thumbnails
   * 6b. Thumbnail top margin (theme) - space between input and thumbnails when present
   * 7. Thumbnails (if present)
   * 8. Top padding (theme) - clearance above thumbnails to prevent clipping by main area
   */
  int required_height_unscaled;

  if (pending_count > 0) {
    /* With thumbnails: wrap onto extra rows when the footer is too narrow
     * for FOOTER_MAX_ATTACHMENTS in one line. Height is unscaled; wrap
     * math uses the same unscaled size/spacing as this block. */
    const int available = (region_width > 0) ?
                              int(float(region_width) / scale) - int(theme->side_padding) * 2 :
                              0;
    /* Unknown width (init) keeps one row so the footer does not jump to
     * ten stacked thumbnails before the first layout pass. */
    const int columns = (region_width > 0) ? footer_attachment_columns(
                            available, thumb_size_base, int(theme->thumbnail_spacing), pending_count) :
                                             FOOTER_MAX_ATTACHMENTS;
    const int rows = std::max(1, footer_attachment_rows(pending_count, columns));
    const int thumbs_h = rows * thumb_size_base + (rows - 1) * int(theme->thumbnail_spacing);
    required_height_unscaled = bottom_padding_base + row_height_base + row_spacing_base +
                               input_row_base + mention_block_base + main_footer_gap_base +
                               thumb_top_margin_base + thumbs_h + top_padding_base;
  }
  else {
    /* No thumbnails - top padding provides space above input */
    required_height_unscaled = bottom_padding_base + row_height_base + row_spacing_base +
                               input_row_base + mention_block_base + main_footer_gap_base +
                               top_padding_base;
  }

  /* Safety check for maximum height */
  bool has_overflow = (required_height_unscaled > FOOTER_MAX_HEIGHT);
  if (has_overflow) {
    required_height_unscaled = FOOTER_MAX_HEIGHT;
  }

  if (out_has_overflow) {
    *out_has_overflow = has_overflow;
  }

  return required_height_unscaled;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Button Positioning
 * \{ */

/**
 * Calculate X/Y positions for footer UI elements.
 * Provides consistent positioning across layout and draw functions.
 *
 * \param region_width: Width of the footer region
 * \param pending_count: Number of pending attachments
 * \param theme: Cached theme values
 * \param out_positions: Structure to fill with calculated positions
 */
void footer_layout_calculate_positions(int region_width,
                                        int pending_count,
                                        const struct FooterThemeCache *theme,
                                        FooterElementPositions *out_positions,
                                        int input_line_count,
                                        int mention_row_count)
{
  if (!theme || !out_positions) {
    return;
  }

  out_positions->thumb_columns = 1;
  out_positions->thumb_rows = 0;

  const float scale = UI_SCALE_FAC;

  /* Get scaled values from theme cache */
  out_positions->side_padding = int(theme->side_padding * scale);
  out_positions->bottom_padding = int(theme->bottom_padding);
  out_positions->btn_size = int(chat_ui_get_send_button_size() * scale);
  out_positions->attach_btn_size = int(chat_ui_get_attach_button_size() * scale);
  out_positions->button_row_height = int(theme->button_row_height * scale);
  /* Dynamic input height based on actual line count, sized from the
   * painter's row metrics so the box holds exactly that many rows. */
  out_positions->input_height = int(footer_layout_input_row_base(input_line_count) * scale);
  out_positions->thumb_size = int(theme->thumbnail_size * scale);
  out_positions->thumb_spacing = int(theme->thumbnail_spacing * scale);
  const int available = region_width - out_positions->side_padding * 2;
  const int shown = std::min(pending_count, FOOTER_MAX_ATTACHMENTS);
  out_positions->thumb_columns = footer_attachment_columns(
      available, out_positions->thumb_size, out_positions->thumb_spacing, shown);
  out_positions->thumb_rows = footer_attachment_rows(shown, out_positions->thumb_columns);

  const int row_spacing = int(theme->row_spacing * scale);
  const int main_footer_gap = int(theme->main_footer_gap * scale);

  /* Calculate Y positions (bottom to top) */
  out_positions->buttons_y = out_positions->bottom_padding;
  /* Button row uses single-row height; input_y sits above that */
  out_positions->input_y = out_positions->buttons_y + out_positions->button_row_height +
                           row_spacing + main_footer_gap;

  /* '@' mention dropdown sits directly above the input; thumbnails (when
   * present) are pushed above it. */
  out_positions->mention_count = mention_row_count;
  int mention_block = 0;
  if (mention_row_count > 0) {
    out_positions->mention_y = out_positions->input_y + out_positions->input_height +
                               int(FOOTER_MENTION_GAP_BASE * scale);
    mention_block = int(FOOTER_MENTION_GAP_BASE * scale) +
                    int(FOOTER_MENTION_PANEL_PAD_BASE * scale) * 2 +
                    int(FOOTER_MENTION_ROW_H_BASE * scale) * mention_row_count;
  }
  else {
    out_positions->mention_y = 0;
  }

  if (pending_count > 0) {
    /* Use dedicated thumbnail top margin for vertical spacing above thumbnails */
    out_positions->thumb_y = out_positions->input_y + out_positions->input_height +
                             mention_block + int(theme->thumbnail_top_margin * scale);
  }
  else {
    out_positions->thumb_y = 0;
  }

  /* Calculate X positions */
  out_positions->dropdown_width = int(FOOTER_DROPDOWN_WIDTH_BASE * scale);
  out_positions->dropdown_x = out_positions->side_padding;

  /* Agent model picker sits between the mode dropdown and the attach button.
   * Only the widths are settled here; whether it is drawn at all depends on
   * the WindowManager mirror the Python half owns, so the draw does the
   * shifting (see mixie_chat_footer.cc). */
  out_positions->model_dropdown_width = int(FOOTER_MODEL_BUTTON_WIDTH_BASE * scale);
  out_positions->model_dropdown_min_width = int(FOOTER_MODEL_BUTTON_MIN_BASE * scale);
  out_positions->model_dropdown_x = out_positions->dropdown_x + out_positions->dropdown_width +
                                    int(FOOTER_BUTTON_SPACING_BASE * scale);

  /* Attach button comes right after dropdown (no model picker shown) */
  out_positions->attach_btn_x = out_positions->model_dropdown_x;

  out_positions->send_btn_x = region_width - out_positions->side_padding -
                              out_positions->btn_size;

  /* Input field aligned with button row (no extra horizontal padding) */
  out_positions->input_x = out_positions->side_padding;
  out_positions->input_w = region_width - out_positions->side_padding * 2;
}

/** \} */
}  // namespace blender
