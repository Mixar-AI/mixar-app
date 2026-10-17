/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * The sheet painters: the text elements (title, caption, prompt / note /
 * body lines), the close square, provider rows and the sidebar's foot,
 * model chips, the docked pills and the key field they dock into. Snippets,
 * switches, status dots and the foot's glyphs are in
 * `interface_mixar_sheet_blocks.cc`. See `interface_mixar_sheet.hh` for
 * the artboard the numbers come from.
 *
 * Every control reads its hover / press / selection from
 * #mixar_button_motion so state changes glide the way the rest of the
 * Mixar chrome does; "selected" is the `lit` tag for rows and chips and the
 * native UI_SELECT for a Row (enum) button drawn as a chip.
 */

#include <algorithm>
#include <cmath>
#include <cstring>
#include <string>

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

const char *but_label(const Button *but)
{
  return but->str.empty() ? but->drawstr.c_str() : but->str.c_str();
}

bool but_disabled(const Button *but)
{
  return (but->flag & (BUT_DISABLED | BUT_INACTIVE)) != 0;
}

void lerp_col(uchar out[4], const uchar a[4], const uchar b[4], const float t)
{
  for (int i = 0; i < 4; i++) {
    out[i] = uchar(std::lround(float(a[i]) + (float(b[i]) - float(a[i])) * std::clamp(t, 0.0f, 1.0f)));
  }
}

float hover_cue(const float hover, const float press)
{
  return std::min(1.0f, hover + press);
}

static float hover_cue(const MixarInteraction &motion)
{
  return hover_cue(motion.hover, motion.press);
}

static void dim(uchar col[4], const float alpha)
{
  col[3] = uchar(std::lround(float(col[3]) * alpha));
}

float line_px()
{
  return std::max(float(U.pixelsize), px(frame_line));
}

/* -- Text elements ------------------------------------------------------- */

/** "Title\nSubtitle": the title on the artboard's baseline below the sheet's
 * top edge, the subtitle on its own, both from the sheet's left margin. The
 * button's rect ends where the close square's slot begins (the sheet's edge
 * in the busy states, which have none); both lines keep the close square's
 * right margin from it and are ellipsised past that, so a long translation
 * never runs under the cross or off the card. */
void draw_title(Button *but, const rcti *rect)
{
  const std::string text = but_label(but);
  const size_t nl = text.find('\n');
  const std::string title = text.substr(0, nl);
  const std::string subtitle = nl == std::string::npos ? "" : text.substr(nl + 1);
  const float x = float(rect->xmin) + px(title_x);
  const float top = float(rect->ymax);
  const float max_w = float(rect->xmax) - px(close_right) - x;
  const int title_font = font(title_size, weight_strong);
  text_at(title_font,
          x,
          top - px(title_baseline),
          fit(title_font, title.c_str(), max_w).c_str(),
          text_bright);
  if (!subtitle.empty()) {
    const int subtitle_font = font(subtitle_size, weight_regular);
    text_at(subtitle_font,
            x,
            top - px(subtitle_baseline),
            fit(subtitle_font, subtitle.c_str(), max_w).c_str(),
            text_dim);
  }
}

/** Dim caption with bright spans: "ALL SUPPORTED \x1fANTHROPIC\x1f MODELS",
 * tail-ellipsised to the button's width as one line (the ellipsis takes the
 * colour of the span it cuts). */
void draw_caption(Button *but, const rcti *rect)
{
  /* The island card's caption: monospace, dim, the bright span lit. */
  const int font_id = font(caption_size, weight_regular, true);
  const std::string text = but_label(but);
  rctf box;
  BLI_rctf_rcti_copy(&box, rect);
  const float baseline = BLI_rctf_cent_y(&box) - cap_height(font_id) * 0.5f;
  const float fade = but_disabled(but) ? 0.5f : 1.0f;
  uchar dim_col[4], bright_col[4];
  memcpy(dim_col, text_dim, 4);
  memcpy(bright_col, text_bright, 4);
  dim(dim_col, fade);
  dim(bright_col, fade);

  /* Fit the caption as the reader sees it (marks dropped), then spend that
   * many bytes across the spans. */
  std::string plain = text;
  plain.erase(std::remove(plain.begin(), plain.end(), caption_bright_mark), plain.end());
  const std::string shown = fit(font_id, plain.c_str(), BLI_rctf_size_x(&box));
  const bool clipped = shown != plain;
  const char *ellipsis = "\xe2\x80\xa6";
  size_t budget = clipped ? shown.size() - std::min(shown.size(), strlen(ellipsis)) :
                            plain.size();

  float x = float(rect->xmin);
  bool bright = false;
  size_t start = 0;
  while (start <= text.size()) {
    size_t end = text.find(caption_bright_mark, start);
    if (end == std::string::npos) {
      end = text.size();
    }
    std::string segment = text.substr(start, std::min(end - start, budget));
    budget -= segment.size();
    const bool cut = clipped && budget == 0;
    if (cut) {
      segment += ellipsis;
    }
    if (!segment.empty()) {
      text_at(font_id, x, baseline, segment.c_str(), bright ? bright_col : dim_col);
      x += text_width(font_id, segment.c_str());
    }
    if (cut) {
      break;
    }
    bright = !bright;
    start = end + 1;
  }
}

void draw_text(Button *but,
                      const rcti *rect,
                      const float size_dp,
                      const uchar col_in[4],
                      const int weight)
{
  uchar col[4];
  memcpy(col, col_in, 4);
  dim(col, but_disabled(but) ? 0.5f : 1.0f);
  rctf box;
  BLI_rctf_rcti_copy(&box, rect);
  text_in(font(size_dp, weight), box, but_label(but), col, false);
}

/* -- Close ---------------------------------------------------------------- */

void draw_close(Button *but, const rcti *rect)
{
  const MixarInteraction motion = mixar_button_motion(*but);
  rctf square;
  BLI_rctf_rcti_copy(&square, rect);
  /* The layout hands this button a #close_size-wide slot reaching down from
   * the sheet's top edge: the square sits at its foot, #close_top below the
   * edge; a shorter rect (an old layout) keeps the square at its top. */
  const float size = std::min(px(close_size),
                              std::min(BLI_rctf_size_x(&square), BLI_rctf_size_y(&square)));
  square.xmin = square.xmax - size;
  square.ymax -= std::min(px(close_top), BLI_rctf_size_y(&square) - size);
  square.ymin = square.ymax - size;

  uchar fill[4];
  lerp_col(fill, close_fill, close_fill_hover, hover_cue(motion));
  mixar_card_fill_round(&square, px(close_radius), fill, but_disabled(but) ? 0.5f : 1.0f);

  const float half = px(close_cross) * 0.5f;
  const float cx = BLI_rctf_cent_x(&square);
  const float cy = BLI_rctf_cent_y(&square);
  const float width = px(close_stroke);
  const float alpha = but_disabled(but) ? 0.5f : 1.0f;
  stroke(cx - half, cy - half, cx + half, cy + half, width, close_cross_col, alpha);
  stroke(cx - half, cy + half, cx + half, cy - half, width, close_cross_col, alpha);
}

/* -- Provider row ---------------------------------------------------------- */

void draw_provider_row(Button *but, const rcti *rect)
{
  const MixarInteraction motion = mixar_button_motion(*but);
  const float fade = but_disabled(but) ? 0.5f : 1.0f;
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
  const int font_id = font(label_size, motion.selected > 0.5f ? weight_strong : weight_medium);
  if (text_width(font_id, but_label(but)) > BLI_rctf_size_x(&text)) {
    const float sidebar = but->block->mixar_sheet_sidebar;
    const float divider = sidebar > 0.0f ? block_rect(but).xmin + sidebar - px(16.0f) : pill.xmax;
    text.xmax = std::max(pill.xmax - px(row_text_right), divider);
  }
  text_in(font_id, text, but_label(but), col, false);
}

/* -- Sidebar foot (Local Model, Other app) ---------------------------------- */

void draw_footer_row(Button *but, const rcti *rect)
{
  /* The column's foot: a sidebar row like the providers — the same plate,
   * wash and lit state — led by its glyph (`draw_footer_glyph`: Local
   * model's monitor, Other app's terminal). */
  const MixarInteraction motion = mixar_button_motion(*but);
  const float fade = but_disabled(but) ? 0.5f : 1.0f;
  rctf pill;
  BLI_rctf_rcti_copy(&pill, rect);
  const float rad = std::min(px(row_radius), BLI_rctf_size_y(&pill) * 0.5f);
  const float wash = std::max(hover_cue(motion) * (1.0f - motion.selected), 0.0f);
  /* At rest a faint plate, so the foot reads as a destination, not a label. */
  mixar_card_fill_round(&pill, rad, text_bright, (0.035f + 0.04f * wash) * fade);
  if (motion.selected > 0.0f) {
    mixar_card_fill_round(&pill, rad, row_fill_b, motion.selected * fade);
  }
  uchar col[4];
  lerp_col(col, row_text_off, text_bright, std::max(motion.selected, hover_cue(motion) * 0.6f));
  col[3] = uchar(std::lround(float(col[3]) * fade));
  const float cy = BLI_rctf_cent_y(&pill);
  const float icon_x = pill.xmin + px(row_text_x);
  draw_footer_glyph(but, icon_x, cy, col);
  const rctf text = {icon_x + px(footer_icon) + px(footer_icon_gap),
                     pill.xmax - px(row_text_x),
                     pill.ymin,
                     pill.ymax};
  text_in(font(label_size, motion.selected > 0.5f ? weight_strong : weight_medium),
          text,
          but_label(but),
          col,
          false);
}

/* -- Model chip ------------------------------------------------------------ */

void draw_chip(Button *but, const rcti *rect)
{
  const MixarInteraction motion = mixar_button_motion(*but);
  const float fade = but_disabled(but) ? 0.5f : 1.0f;
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
  /* One weight lit or not: Python sized the chip with this face, and the
   * fill already says which one is current. */
  text_in(font(label_size, weight_medium), text, but_label(but), col, true);
}

/* -- Pills ------------------------------------------------------------------ */

void draw_pill(Button *but, const rcti *rect, const MixarCardElement element)
{
  const MixarInteraction motion = mixar_button_motion(*but);
  const float fade = but_disabled(but) ? 0.45f : 1.0f;
  rctf pill;
  BLI_rctf_rcti_copy(&pill, rect);
  /* Docked: the pill sits inside the key field with #button_dock_inset of
   * breathing room on the field's top, bottom and right edges; in a
   * snippet's corner it keeps the top and right inset and its own height,
   * however tall the block is. */
  const float inset = px(button_dock_inset);
  if (but->mixar_style.progress >= dock_corner) {
    pill.ymax -= inset;
    pill.xmax -= inset;
    pill.ymin = std::max(pill.ymin, pill.ymax - px(button_h));
  }
  else if (but->mixar_style.progress >= 0.5f) {
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
    const int font_id = font(label_size, weight_strong);
    const float label_w = text_width(font_id, but_label(but));
    const float gap = label_w > 0.0f ? px(12.0f) : 0.0f;
    const float group_w = std::min(icon_size + gap + label_w, BLI_rctf_size_x(&text));
    const float x = BLI_rctf_cent_x(&text) - group_w * 0.5f;
    icon_draw_alpha(x, BLI_rctf_cent_y(&pill) - icon_size * 0.5f, but->icon, fade);
    text.xmin = x + icon_size + gap;
    text_in(font_id, text, but_label(but), col, false);
    return;
  }
  text_in(font(label_size, weight_strong), text, but_label(but), col, true);
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
  if (but_disabled(but)) {
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
  const float fade = but_disabled(but) ? 0.5f : 1.0f;
  fill[3] *= fade;
  border[3] *= fade;
  GPU_blend(GPU_BLEND_ALPHA);
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv_ex(&box, fill, fill, 0.0f, border, line_px(), rad);

  /* Chevron at the right end. */
  const float half = px(dropdown_chevron) * 0.5f;
  const float cx = box.xmax - px(dropdown_chevron_right);
  const float cy = BLI_rctf_cent_y(&box);
  const float width = px(2.0f);
  stroke(cx - half, cy + half * 0.5f, cx, cy - half * 0.5f, width, text_dim, fade);
  stroke(cx, cy - half * 0.5f, cx + half, cy + half * 0.5f, width, text_dim, fade);
  GPU_blend(GPU_BLEND_NONE);
}

int UI_mixar_sheet_dropdown_text_inset()
{
  return int(std::lround(px(dropdown_text_right)));
}

}  // namespace blender::ui
