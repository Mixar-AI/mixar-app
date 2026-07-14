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

#include "MEM_guardedalloc.h"

#include "BLF_api.hh"

#include "UI_interface.hh"

#include "DNA_scene_types.h"
#include "DNA_userdef_types.h"

#include "RNA_access.hh"

#include "mixie_chat_footer_constants.hh"
#include "mixie_chat_footer_intern.hh"
#include "mixie_chat_intern.hh"

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

  char *text = static_cast<char *>(MEM_mallocN(text_len + 1, __func__));
  RNA_property_string_get(&scene_ptr, prop, text);

  /* Calculate available width for text wrapping.
   * Must match widget_draw_text_multiline() in interface_widgets.cc:
   *   rect_width = BLI_rcti_size_x(rect) - 4*pixelsize
   * The input rect width = region_width - side_padding*2 (from calculate_positions). */
  const float scale = UI_SCALE_FAC;
  const float side_padding = FOOTER_DEFAULT_SIDE_PADDING * scale;
  const int input_w = int(float(region_width) - side_padding * 2.0f);
  const int rect_width = std::max(input_w - int(4.0f * U.pixelsize), 10);

  int visual_line_count;
  if (rect_width > 10) {
    /* Use the same font setup as widget_draw_text_multiline():
     *   font = UI_style_get()->widget with points * 1.2f */
    uiFontStyle fstyle = UI_style_get()->widget;
    fstyle.points *= 1.2f;
    UI_fontstyle_set(&fstyle);
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

  MEM_freeN(text);

  return std::max(FOOTER_INPUT_LINE_COUNT,
                  std::min(visual_line_count, FOOTER_INPUT_MAX_LINE_COUNT));
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
                                    int mention_row_count)
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
  const int effective_lines = (input_line_count > 0) ? input_line_count : FOOTER_INPUT_LINE_COUNT;
  const int input_row_base = FOOTER_UI_UNIT_BASE * effective_lines;
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
    /* With thumbnails - include top padding above thumbnails for clearance */
    required_height_unscaled = bottom_padding_base + row_height_base + row_spacing_base +
                               input_row_base + mention_block_base + main_footer_gap_base +
                               thumb_top_margin_base + thumb_size_base + top_padding_base;
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

  const float scale = UI_SCALE_FAC;

  /* Get scaled values from theme cache */
  out_positions->side_padding = int(theme->side_padding * scale);
  out_positions->bottom_padding = int(theme->bottom_padding);
  out_positions->btn_size = int(chat_ui_get_send_button_size() * scale);
  out_positions->attach_btn_size = int(chat_ui_get_attach_button_size() * scale);
  out_positions->button_row_height = int(theme->button_row_height * scale);
  /* Dynamic input height based on actual line count */
  const int effective_lines = (input_line_count > 0) ? input_line_count : FOOTER_INPUT_LINE_COUNT;
  out_positions->input_height = int(FOOTER_UI_UNIT_BASE * effective_lines * scale);
  out_positions->thumb_size = int(theme->thumbnail_size * scale);
  out_positions->thumb_spacing = int(theme->thumbnail_spacing * scale);

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

  /* Attach button comes right after dropdown */
  out_positions->attach_btn_x = out_positions->dropdown_x + out_positions->dropdown_width +
                                int(FOOTER_BUTTON_SPACING_BASE * scale);

  out_positions->send_btn_x = region_width - out_positions->side_padding -
                              out_positions->btn_size;

  /* Input field aligned with button row (no extra horizontal padding) */
  out_positions->input_x = out_positions->side_padding;
  out_positions->input_w = region_width - out_positions->side_padding * 2;
}

/** \} */
