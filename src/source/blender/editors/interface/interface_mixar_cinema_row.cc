/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Cinema Mode popup rows. The Director dropdown popups (aspect, lens,
 * output, interpolation, moves, shots) are native block popups built from
 * plain buttons; tagged as #MixarCardElement::CinemaRow they paint as the
 * surface's own row class — the graded chip for the live choice, plain dim
 * text for the rest, a caption, a slider track, a segmented group — so a
 * list looks like the value block it opened from and like the Template
 * Style / My Cameras lists beside it.
 *
 * This file owns the tag, the kind lookup, the shared primitives and the
 * Option / Active / Action painter; `_segment.cc` and `_value.cc` paint the
 * other kinds.
 *
 * The live row's graded chip and the hover fill are panes: both sit ON the
 * popup's own back, so both take #MIXAR_GLASS_CHIP (tint, a hair of gloss,
 * the family rim — no shadow/specular) and keep only the graded wash that
 * marks the live choice; hover/press rides the pane alpha. Slider track and
 * fill stay flat — a groove that shows through stops reading as a groove.
 *
 * Geometry and colours live in `UI_mixar_chrome.hh` and still MIRROR
 * `view3d_director_cinema.hh` (CINEMA_ROW_RADIUS, CINEMA_COL_ROW_TOP/BOTTOM,
 * CINEMA_COL_VALUE/DIM/CAPTION/SPEED_ON); a pin test keeps them in step,
 * since this translation unit cannot reach into space_view3d.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_utildefines.h"

#include "GPU_state.hh"

#include "UI_interface_c.hh"
#include "UI_interface_icons.hh"
#include "UI_mixar_chrome.hh"
#include "UI_mixar_motion.hh"

#include "interface_intern.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_cinema_row.hh"
#include "interface_mixar_profile_card.hh"
#include "interface_mixar_section.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

namespace mixar_cinema_row {

/* Design px @1x — named in UI_mixar_chrome.hh, mirrored from cinema.hh. */
const float ROW_RADIUS = mixar_chrome::cinema_row_radius;
const float TEXT_PAD = mixar_chrome::cinema_row_text_pad;
const float TEXT_PAD_MIN = mixar_chrome::cinema_row_text_pad_min;
const float SEGMENT_MIN_W = mixar_chrome::cinema_row_segment_min_w;

const uchar ROW_TOP[4] = {mixar_chrome::cinema_row_top[0],
                          mixar_chrome::cinema_row_top[1],
                          mixar_chrome::cinema_row_top[2],
                          mixar_chrome::cinema_row_top[3]};
const uchar ROW_BOTTOM[4] = {mixar_chrome::cinema_row_bottom[0],
                             mixar_chrome::cinema_row_bottom[1],
                             mixar_chrome::cinema_row_bottom[2],
                             mixar_chrome::cinema_row_bottom[3]};
const uchar HOVER[4] = {mixar_chrome::cinema_row_hover[0],
                        mixar_chrome::cinema_row_hover[1],
                        mixar_chrome::cinema_row_hover[2],
                        mixar_chrome::cinema_row_hover[3]};
const uchar TRACK[4] = {mixar_chrome::cinema_row_track[0],
                        mixar_chrome::cinema_row_track[1],
                        mixar_chrome::cinema_row_track[2],
                        mixar_chrome::cinema_row_track[3]};
const uchar TEXT_ON[4] = {mixar_chrome::cinema_row_text_on[0],
                          mixar_chrome::cinema_row_text_on[1],
                          mixar_chrome::cinema_row_text_on[2],
                          mixar_chrome::cinema_row_text_on[3]};
const uchar TEXT_OFF[4] = {mixar_chrome::cinema_row_text_off[0],
                           mixar_chrome::cinema_row_text_off[1],
                           mixar_chrome::cinema_row_text_off[2],
                           mixar_chrome::cinema_row_text_off[3]};
const uchar TEXT_DISABLED[4] = {mixar_chrome::cinema_row_text_disabled[0],
                                mixar_chrome::cinema_row_text_disabled[1],
                                mixar_chrome::cinema_row_text_disabled[2],
                                mixar_chrome::cinema_row_text_disabled[3]};
const uchar CAPTION[4] = {mixar_chrome::cinema_row_caption[0],
                          mixar_chrome::cinema_row_caption[1],
                          mixar_chrome::cinema_row_caption[2],
                          mixar_chrome::cinema_row_caption[3]};
const uchar SLIDER_ON[4] = {mixar_chrome::cinema_row_slider_on[0],
                            mixar_chrome::cinema_row_slider_on[1],
                            mixar_chrome::cinema_row_slider_on[2],
                            mixar_chrome::cinema_row_slider_on[3]};

rctf row_rect(const rcti *rect)
{
  rctf row;
  mixar_card_rect_to_rctf(rect, &row);
  const float inset = mixar_chrome::cinema_row_inset * UI_SCALE_FAC;
  BLI_rctf_pad(&row, -inset, -inset);
  return row;
}

float row_radius(const rctf &row)
{
  return std::min(ROW_RADIUS * UI_SCALE_FAC, BLI_rctf_size_y(&row) * 0.5f);
}

const char *row_label(const Button *but)
{
  return but->str.empty() ? but->drawstr.c_str() : but->str.c_str();
}

uiFontStyle row_font()
{
  return mixar_card_font(mixar_chrome::label_scale, 0);
}

uiFontStyle caption_font()
{
  return mixar_card_font(mixar_chrome::caption_scale, 0);
}

/** The live chip's graded slate is a wash: an opaque ramp would cover the
 * pane the row now sits in. */
constexpr float CHIP_WASH = 0.6f;

void draw_chip(const rctf &row, const float radius, const float alpha)
{
  mixar_card_glass_round(&row, radius, MIXAR_GLASS_CHIP, alpha);

  float top[4], bottom[4];
  mixar_card_to_float(ROW_TOP, top);
  mixar_card_to_float(ROW_BOTTOM, bottom);
  top[3] *= CHIP_WASH * alpha;
  bottom[3] *= CHIP_WASH * alpha;
  const float inset = 1.0f * UI_SCALE_FAC;
  rctf wash = row;
  BLI_rctf_pad(&wash, -inset, -inset);
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv_ex(&wash, top, bottom, 1.0f, nullptr, 0.0f, std::max(radius - inset, 0.0f));
}

void draw_hover(const rctf &row, const float radius, const float alpha)
{
  /* Hover/press cue is the pane's alpha; HOVER grey stays on the slider track. */
  mixar_card_glass_round(&row, radius, MIXAR_GLASS_CHIP, alpha);
}

float pad_slack()
{
  return (TEXT_PAD - TEXT_PAD_MIN) * UI_SCALE_FAC;
}

void draw_label(const uiFontStyle &fs,
                const rcti *rect,
                const char *label,
                const uchar col[4],
                const FontStyleAlign align,
                const float slack_left,
                const float slack_right)
{
  if (label == nullptr || label[0] == '\0') {
    return;
  }
  /* Fit before ellipsis: a label a few px too wide for the TEXT_PAD inset
   * (the Output popup's three-up "Beauty") takes the padding back, evenly
   * from both sides down to TEXT_PAD_MIN, and is drawn whole. */
  rcti fit = *rect;
  const float label_w = fontstyle_string_width(&fs, label);
  const float need = label_w - float(BLI_rcti_size_x(&fit));
  if (need > 0.0f) {
    const float left = std::min(slack_left, need * 0.5f);
    const float right = std::min(slack_right, need - left);
    fit.xmin -= int(std::ceil(std::min(slack_left, need - right)));
    fit.xmax += int(std::ceil(right));
  }
  /* Then shorten with an ellipsis BEFORE drawing: `fontstyle_draw` clips per
   * glyph, which is what cut "Perspective" to "Perspe". */
  char clipped[UI_MAX_DRAW_STR];
  STRNCPY(clipped, label);
  const float okwidth = float(std::max(BLI_rcti_size_x(&fit), 0));
  const float minwidth = ICON_DEFAULT_HEIGHT * UI_SCALE_FAC;
  text_clip_middle_ex(&fs, clipped, okwidth, minwidth, sizeof(clipped), '\0');
  mixar_card_draw_text(fs, &fit, clipped, col, align);
}

bool draw_leading_icon(
    const Button *but, const rcti *rect, rcti &text, const float label_w, const float alpha)
{
  if (but->icon == ICON_NONE) {
    return false;
  }
  /* The stock 16px glyph, vertically centred, then the label after it —
   * unless the cell cannot hold both, when the label wins. */
  const float icon_size = ICON_DEFAULT_HEIGHT * UI_SCALE_FAC;
  const float icon_gap = mixar_chrome::cinema_row_icon_gap * UI_SCALE_FAC;
  if (icon_size + icon_gap + label_w <= float(BLI_rcti_size_x(&text))) {
    const float icon_y = float(rect->ymin) + (float(BLI_rcti_size_y(rect)) - icon_size) * 0.5f;
    icon_draw_alpha(float(text.xmin), icon_y, but->icon, alpha);
    text.xmin += int(icon_size + icon_gap);
    return true;
  }
  return false;
}

void draw_option(Button *but,
                 const rcti *rect,
                 const MixarCinemaRowKind kind,
                 const bool /*is_hover*/,
                 const bool /*is_active*/)
{
  const MixarInteraction motion = mixar_button_motion(*but);
  const bool disabled = (but->flag & (BUT_DISABLED | BUT_INACTIVE)) != 0;
  const rctf row = row_rect(rect);
  const float rad = row_radius(row);
  const float hover = 0.9f * motion.hover + (1.0f - 0.9f * motion.hover) * motion.press;
  draw_hover(row, rad, hover * (1.0f - motion.selected));
  if (motion.selected > 0.0f) {
    draw_chip(row, rad, motion.selected);
  }

  const float selected = kind == MixarCinemaRowKind::Action ? 1.0f : motion.selected;
  uchar col[4];
  for (int i = 0; i < 4; i++) {
    col[i] = disabled ? TEXT_DISABLED[i] :
                        uchar(float(TEXT_OFF[i]) + (float(TEXT_ON[i]) - TEXT_OFF[i]) * selected);
  }
  rcti text = *rect;
  text.xmin += int(TEXT_PAD * UI_SCALE_FAC);
  text.xmax -= int(TEXT_PAD * UI_SCALE_FAC);
  const uiFontStyle fs = row_font();
  const char *label = row_label(but);
  const float label_w = fontstyle_string_width(&fs, label);
  const bool icon_drawn = draw_leading_icon(but, rect, text, label_w, disabled ? 0.4f : 0.9f);
  draw_label(
      fs, &text, label, col, UI_STYLE_TEXT_LEFT, icon_drawn ? 0.0f : pad_slack(), pad_slack());
}

}  // namespace mixar_cinema_row

using namespace mixar_cinema_row;

ButtonType UI_mixar_button_type(const Button *but)
{
  return but->type;
}

bool UI_mixar_cinema_row_carries_value(const Button *but)
{
  /* Kept for compatibility callers; the dedicated descriptor means even
   * Row enum values and all numeric/text limits remain untouched. */
  return ELEM(but->type,
              ButtonType::Num,
              ButtonType::NumSlider,
              ButtonType::Scroll,
              ButtonType::Text,
              ButtonType::Toggle,
              ButtonType::IconToggle,
              ButtonType::Menu);
}

MixarCinemaRowKind UI_mixar_cinema_row_kind_get(const Button *but)
{
  switch (but->type) {
    case ButtonType::Num:
    case ButtonType::NumSlider:
    case ButtonType::Scroll:
      return MixarCinemaRowKind::Slider;
    case ButtonType::Text:
      return MixarCinemaRowKind::Field;
    case ButtonType::Row:
    case ButtonType::Toggle:
    case ButtonType::IconToggle:
    case ButtonType::Menu:
      /* Lights from UI_SELECT; `hardmax` is the toggle's value, not a kind. */
      return MixarCinemaRowKind::Option;
    default:
      return but->mixar_style.cinema;
  }
}

void UI_mixar_button_double_click_edits_label(Button *but)
{
  if (but != nullptr) {
    UI_BUT_MIXAR_DBLCLICK_EDITS_LABEL_SET(but);
  }
}

void UI_mixar_cinema_row_tag(Button *but, const MixarCinemaRowKind kind)
{
  if (but == nullptr) {
    return;
  }
  but->mixar_style.component = MixarComponent::LegacyCard;
  if (!but->mixar_style.explicit_theme) {
    but->mixar_style.theme = MixarTheme::LegacyMixar;
  }
  but->mixar_style.card = MixarCardElement::CinemaRow;
  but->mixar_style.cinema = kind;
  /* Value-carrying rows retain their historical recipe; the resolved kind is
   * stored explicitly instead of stealing range/value fields. */
  but->mixar_style.cinema = UI_mixar_cinema_row_kind_get(but);
}

void UI_mixar_cinema_row_draw(Button *but,
                              const rcti *rect,
                              const bool is_hover,
                              const bool is_active)
{
  const MixarCinemaRowKind kind = UI_mixar_cinema_row_kind_get(but);
  GPU_blend(GPU_BLEND_ALPHA);

  if (but->editstr != nullptr) {
    /* Text editing (a Slider double-clicked, a Field rename): the stock text
     * pass draws the edit string, selection and cursor AFTER this call (see
     * the CinemaRow fall-through in `interface_widgets.cc`), so lay only the
     * chip under it — and nothing at all for kinds that never edit. */
    if (ELEM(kind, MixarCinemaRowKind::Slider, MixarCinemaRowKind::Field)) {
      const rctf row = row_rect(rect);
      draw_chip(row, row_radius(row));
    }
    return;
  }

  switch (kind) {
    case MixarCinemaRowKind::Segment:
      draw_segment(but, rect);
      return;
    case MixarCinemaRowKind::Caption:
      draw_caption(but, rect);
      return;
    case MixarCinemaRowKind::Slider:
      draw_slider(but, rect, is_hover);
      return;
    case MixarCinemaRowKind::Field:
      draw_field(but, rect);
      return;
    default:
      draw_option(but, rect, kind, is_hover, is_active);
      return;
  }
}

}  // namespace blender::ui
