/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * AI Provider settings sheet — the controls: the close square, provider
 * rows and the sidebar's Local Model foot, model chips, the docked pills and
 * the key field they dock into. See `interface_mixar_sheet.hh` for the
 * artboard the numbers come from.
 *
 * Every control reads its hover / press / selection from
 * #mixar_button_motion so state changes glide the way the rest of the
 * Mixar chrome does; "selected" is the `lit` tag for rows and chips and the
 * native UI_SELECT for a Row (enum) button drawn as a chip.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLI_math_color.h"
#include "BLI_rect.h"
#include "BLI_utildefines.h"

#include "DNA_userdef_types.h"

#include "GPU_state.hh"

#include "UI_interface_c.hh"
#include "UI_interface_icons.hh"
#include "UI_mixar_motion.hh"

#include "interface_intern.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_sheet.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

namespace mixar_sheet {

static const char *label(const Button *but)
{
  return but->str.empty() ? but->drawstr.c_str() : but->str.c_str();
}

static bool disabled(const Button *but)
{
  return (but->flag & (BUT_DISABLED | BUT_INACTIVE)) != 0;
}

static void lerp_col(uchar out[4], const uchar a[4], const uchar b[4], const float t)
{
  for (int i = 0; i < 4; i++) {
    out[i] = uchar(std::lround(float(a[i]) + (float(b[i]) - float(a[i])) * std::clamp(t, 0.0f, 1.0f)));
  }
}

static float hover_cue(const MixarInteraction &motion)
{
  return std::min(1.0f, motion.hover + motion.press);
}

static float line_px()
{
  return std::max(float(U.pixelsize), px(frame_line));
}

/* -- Close ---------------------------------------------------------------- */

void draw_close(Button *but, const rcti *rect)
{
  const MixarInteraction motion = mixar_button_motion(*but);
  rctf square;
  BLI_rctf_rcti_copy(&square, rect);
  /* The layout hands this button a 100-wide slot reaching down from the
   * sheet's top edge: the square sits at its foot, the artboard's 40 below
   * the edge; a shorter rect (an old layout) keeps the square at its top. */
  const float size = std::min(px(close_size),
                              std::min(BLI_rctf_size_x(&square), BLI_rctf_size_y(&square)));
  square.xmin = square.xmax - size;
  square.ymax -= std::min(px(close_top), BLI_rctf_size_y(&square) - size);
  square.ymin = square.ymax - size;

  uchar fill[4];
  lerp_col(fill, close_fill, close_fill_hover, hover_cue(motion));
  mixar_card_fill_round(&square, px(close_radius), fill, disabled(but) ? 0.5f : 1.0f);

  const float half = px(close_cross) * 0.5f;
  const float cx = BLI_rctf_cent_x(&square);
  const float cy = BLI_rctf_cent_y(&square);
  const float width = px(close_stroke);
  const float alpha = disabled(but) ? 0.5f : 1.0f;
  stroke(cx - half, cy - half, cx + half, cy + half, width, close_cross_col, alpha);
  stroke(cx - half, cy + half, cx + half, cy - half, width, close_cross_col, alpha);
}

/* -- Provider row ---------------------------------------------------------- */

void draw_provider_row(Button *but, const rcti *rect)
{
  const MixarInteraction motion = mixar_button_motion(*but);
  const float fade = disabled(but) ? 0.5f : 1.0f;
  rctf pill;
  BLI_rctf_rcti_copy(&pill, rect);
  const float rad = std::min(px(row_radius), BLI_rctf_size_y(&pill) * 0.5f);

  /* A quiet wash on a hovered rest row; the graded slate on the live one. */
  const float wash = hover_cue(motion) * (1.0f - motion.selected);
  if (wash > 0.0f) {
    mixar_card_fill_round(&pill, rad, text_bright, 0.06f * wash);
  }
  if (motion.selected > 0.0f) {
    float left[4], right[4];
    rgba_uchar_to_float(left, row_fill_a);
    rgba_uchar_to_float(right, row_fill_b);
    left[3] = right[3] = motion.selected * fade;
    draw_roundbox_corner_set(CNR_ALL);
    /* The widget shader mixes inner2 -> inner1 along X: dark left, light right. */
    draw_roundbox_4fv_ex(&pill, right, left, 0.0f, nullptr, 0.0f, rad);

    const float r = px(row_dot_r);
    const float cx = pill.xmin - px(row_dot_gap);
    const float cy = BLI_rctf_cent_y(&pill);
    const rctf dot = {cx - r, cx + r, cy - r, cy + r};
    mixar_card_fill_round(&dot, r, row_dot, motion.selected * fade);
  }

  uchar col[4];
  lerp_col(col, row_text_off, text_bright, motion.selected);
  col[3] = uchar(std::lround(float(col[3]) * fade));
  rctf text = pill;
  text.xmin += px(row_text_x);
  text.xmax -= px(row_text_x);
  /* Python widens the pill to a long name (`byok_sheet.row_right`); only a
   * name too long even for that runs on towards the divider before it is
   * ellipsised. */
  const int font_id = font(label_size);
  if (text_width(font_id, label(but)) > BLI_rctf_size_x(&text)) {
    const float sidebar = but->block->mixar_sheet_sidebar;
    const float divider = sidebar > 0.0f ? block_rect(but).xmin + sidebar - px(16.0f) : pill.xmax;
    text.xmax = std::max(pill.xmax - px(row_text_right), divider);
  }
  text_in(font_id, text, label(but), col, false);
}

/* -- Sidebar foot (Local Model) --------------------------------------------- */

/** The artboard's monitor: a rounded screen on a stand over a base, stroked. */
static void draw_monitor(const float x, const float cy, const uchar col[4], const float alpha)
{
  const float w = px(footer_icon);
  const float screen_h = px(15.2f);
  const float stroke_w = px(footer_icon_stroke);
  const rctf screen = {x, x + w, cy + px(10.0f) - screen_h, cy + px(10.0f)};
  float c[4];
  rgba_uchar_to_float(c, col);
  c[3] *= alpha;
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv(&screen, false, px(4.0f), c);
  const float mid = x + w * 0.5f;
  stroke(mid, screen.ymin, mid, cy - px(10.0f), stroke_w, col, alpha);
  stroke(x + px(5.5f), cy - px(10.0f), x + w - px(5.5f), cy - px(10.0f), stroke_w, col, alpha);
}

void draw_footer_row(Button *but, const rcti *rect)
{
  const MixarInteraction motion = mixar_button_motion(*but);
  const float fade = disabled(but) ? 0.5f : 1.0f;
  const rctf block = block_rect(but);
  const float line = line_px();
  const float sidebar = but->block->mixar_sheet_sidebar;

  /* The bar runs to the card's left and bottom edges and hugs its corner,
   * whatever the layout column measured. */
  rctf bar;
  bar.xmin = block.xmin + line;
  bar.xmax = sidebar > 0.0f ? block.xmin + sidebar - line * 0.5f : float(rect->xmax);
  bar.ymin = block.ymin + line;
  bar.ymax = float(rect->ymax);
  uchar fill[4];
  lerp_col(fill, footer_fill, footer_fill_hover, std::max(hover_cue(motion), motion.selected * 0.6f));
  float c[4];
  rgba_uchar_to_float(c, fill);
  c[3] *= fade;
  draw_roundbox_corner_set(CNR_BOTTOM_LEFT);
  draw_roundbox_4fv(&bar, true, std::max(px(frame_radius) - line, 0.0f), c);
  draw_roundbox_corner_set(CNR_ALL);

  const float cy = BLI_rctf_cent_y(&bar);
  draw_monitor(block.xmin + px(footer_icon_x), cy, text_bright, fade);
  uchar col[4];
  memcpy(col, text_bright, 4);
  col[3] = uchar(std::lround(255.0f * fade));
  const rctf text = {block.xmin + px(footer_text_x), bar.xmax - px(row_text_x), bar.ymin, bar.ymax};
  text_in(font(label_size), text, label(but), col, false);
}

/* -- Model chip ------------------------------------------------------------ */

void draw_chip(Button *but, const rcti *rect)
{
  const MixarInteraction motion = mixar_button_motion(*but);
  const float fade = disabled(but) ? 0.5f : 1.0f;
  rctf chip;
  BLI_rctf_rcti_copy(&chip, rect);
  const float rad = std::min(px(chip_radius), BLI_rctf_size_y(&chip) * 0.5f);

  const float wash = hover_cue(motion) * (1.0f - motion.selected);
  if (wash > 0.0f) {
    mixar_card_fill_round(&chip, rad, text_bright, 0.08f * wash);
  }
  if (motion.selected > 0.0f) {
    mixar_card_fill_round(&chip, rad, chip_fill, motion.selected * fade);
  }

  uchar col[4];
  lerp_col(col, chip_text_off, text_bright, motion.selected);
  col[3] = uchar(std::lround(float(col[3]) * fade));
  rctf text = chip;
  const float pad = std::min(px(chip_pad), BLI_rctf_size_x(&chip) * 0.25f);
  text.xmin += pad;
  text.xmax -= pad;
  text_in(font(label_size), text, label(but), col, true);
}

/* -- Pills ------------------------------------------------------------------ */

void draw_pill(Button *but, const rcti *rect, const MixarCardElement element)
{
  const MixarInteraction motion = mixar_button_motion(*but);
  const float fade = disabled(but) ? 0.45f : 1.0f;
  rctf pill;
  BLI_rctf_rcti_copy(&pill, rect);
  /* Docked: the pill sits inside the key field with the artboard's 8 px
   * breathing room on the field's top, bottom and right edges. */
  if (but->mixar_style.progress >= 0.5f) {
    const float inset = px(button_dock_inset);
    pill.ymin += inset;
    pill.ymax -= inset;
    pill.xmax -= inset;
  }
  const float rad = std::min(px(button_radius), BLI_rctf_size_y(&pill) * 0.5f);

  const uchar *rest = primary_fill;
  const uchar *hovered = primary_fill_hover;
  const uchar *text_col = text_bright;
  if (element == MixarCardElement::SheetSecondary) {
    rest = secondary_fill;
    hovered = secondary_fill_hover;
  }
  else if (element == MixarCardElement::SheetDangerButton) {
    rest = danger_fill;
    hovered = danger_fill_hover;
    text_col = text_danger;
  }
  uchar fill[4];
  lerp_col(fill, rest, hovered, hover_cue(motion));
  mixar_card_fill_round(&pill, rad, fill, fade);
  if (element == MixarCardElement::SheetSecondary) {
    mixar_card_outline_round(&pill, rad, frame_border, fade);
  }

  uchar col[4];
  memcpy(col, text_col, 4);
  col[3] = uchar(std::lround(float(col[3]) * fade));
  rctf text = pill;
  const float pad = std::min(px(button_pad) * 0.5f, BLI_rctf_size_x(&pill) * 0.2f);
  text.xmin += pad;
  text.xmax -= pad;
  if (!ELEM(but->icon, ICON_NONE, ICON_BLANK1)) {
    /* An icon pill (the Local branch's rescan): the stock glyph, centred,
     * ahead of whatever label there is. */
    const float icon_size = ICON_DEFAULT_HEIGHT * UI_SCALE_FAC;
    const int font_id = font(label_size);
    const float label_w = text_width(font_id, label(but));
    const float gap = label_w > 0.0f ? px(12.0f) : 0.0f;
    const float group_w = std::min(icon_size + gap + label_w, BLI_rctf_size_x(&text));
    const float x = BLI_rctf_cent_x(&text) - group_w * 0.5f;
    icon_draw_alpha(x, BLI_rctf_cent_y(&pill) - icon_size * 0.5f, but->icon, fade);
    text.xmin = x + icon_size + gap;
    text_in(font_id, text, label(but), col, false);
    return;
  }
  text_in(font(label_size), text, label(but), col, true);
}

}  // namespace mixar_sheet

using namespace mixar_sheet;

/* -- Native fields ------------------------------------------------------------ */

void UI_mixar_sheet_input_draw(Button *but, const rcti *rect)
{
  rctf box;
  BLI_rctf_rcti_copy(&box, rect);
  /* Run under the control docked after this field (its design-px width is
   * the tag's payload), so field and pill read as one bar. */
  box.xmax += px(but->mixar_style.progress);
  const float rad = std::min(px(input_radius), BLI_rctf_size_y(&box) * 0.5f);
  const bool focused = but->editstr != nullptr || (but->flag & UI_SELECT) != 0;
  float fill[4], border[4];
  rgba_uchar_to_float(fill, input_fill);
  rgba_uchar_to_float(border, focused ? input_border_focus : input_border);
  if (disabled(but)) {
    fill[3] = border[3] = 0.5f;
  }
  GPU_blend(GPU_BLEND_ALPHA);
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv_ex(&box, fill, fill, 0.0f, border, line_px(), rad);
  GPU_blend(GPU_BLEND_NONE);
}

void UI_mixar_sheet_dropdown_draw(Button *but, const rcti *rect)
{
  const MixarInteraction motion = mixar_button_motion(*but);
  rctf box;
  BLI_rctf_rcti_copy(&box, rect);
  const float rad = std::min(px(input_radius), BLI_rctf_size_y(&box) * 0.5f);
  float fill[4], border[4];
  rgba_uchar_to_float(fill, input_fill);
  uchar border_u[4];
  lerp_col(border_u, input_border, input_border_focus, hover_cue(motion));
  rgba_uchar_to_float(border, border_u);
  const float fade = disabled(but) ? 0.5f : 1.0f;
  fill[3] *= fade;
  border[3] *= fade;
  GPU_blend(GPU_BLEND_ALPHA);
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv_ex(&box, fill, fill, 0.0f, border, line_px(), rad);

  /* Chevron at the right end. */
  const float half = px(dropdown_chevron) * 0.5f;
  const float cx = box.xmax - px(30.0f);
  const float cy = BLI_rctf_cent_y(&box);
  const float width = px(2.0f);
  stroke(cx - half, cy + half * 0.5f, cx, cy - half * 0.5f, width, text_dim, fade);
  stroke(cx, cy - half * 0.5f, cx + half, cy + half * 0.5f, width, text_dim, fade);
  GPU_blend(GPU_BLEND_NONE);
}

}  // namespace blender::ui
