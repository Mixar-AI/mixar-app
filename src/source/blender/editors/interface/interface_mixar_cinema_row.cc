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
 * The tokens MIRROR `view3d_director_cinema.hh` (CINEMA_ROW_RADIUS,
 * CINEMA_COL_ROW_TOP/BOTTOM, CINEMA_COL_VALUE/DIM/CAPTION/SPEED_ON); a pin
 * test keeps them in step, since this translation unit cannot reach into
 * space_view3d.
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

#include "interface_intern.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_cinema_row.hh"
#include "interface_mixar_profile_card.hh"
#include "interface_mixar_section.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui {

namespace mixar_cinema_row {

/* Design px @1x — see view3d_director_cinema.hh. */
const float ROW_RADIUS = 14.0f;
const float TEXT_PAD = 12.0f;
const float TEXT_PAD_MIN = 4.0f;
const float SEGMENT_MIN_W = 28.0f;

const uchar ROW_TOP[4] = {0x58, 0x58, 0x58, 255};    /* CINEMA_COL_ROW_TOP */
const uchar ROW_BOTTOM[4] = {0x24, 0x24, 0x24, 255}; /* CINEMA_COL_ROW_BOTTOM */
const uchar HOVER[4] = {0x2E, 0x2E, 0x2E, 255};
const uchar TRACK[4] = {0x26, 0x26, 0x26, 255};      /* a step under HOVER: never the lit chip */
const uchar TEXT_ON[4] = {255, 255, 255, 255};       /* CINEMA_COL_VALUE */
const uchar TEXT_OFF[4] = {0xB4, 0xB4, 0xB4, 255};   /* readable on the popup back */
const uchar TEXT_DISABLED[4] = {0x63, 0x63, 0x63, 255}; /* CINEMA_COL_DIM */
const uchar CAPTION[4] = {102, 102, 102, 217};       /* CINEMA_COL_CAPTION 0.40/0.85 */
const uchar SLIDER_ON[4] = {42, 121, 73, 255};       /* CINEMA_COL_SPEED_ON #2A7949 */

rctf row_rect(const rcti *rect)
{
  rctf row;
  mixar_card_rect_to_rctf(rect, &row);
  const float inset = 1.0f * UI_SCALE_FAC;
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
  return mixar_card_font(0.95f, 0);
}

uiFontStyle caption_font()
{
  return mixar_card_font(0.9f, 0);
}

void draw_chip(const rctf &row, const float radius)
{
  float top[4], bottom[4];
  mixar_card_to_float(ROW_TOP, top);
  mixar_card_to_float(ROW_BOTTOM, bottom);
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv_ex(&row, top, bottom, 1.0f, nullptr, 0.0f, radius);
}

void draw_hover(const rctf &row, const float radius, const float alpha)
{
  mixar_card_fill_round(&row, radius, HOVER, alpha);
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
  const float icon_gap = 6.0f * UI_SCALE_FAC;
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
                 const bool is_hover,
                 const bool is_active)
{
  /* A Row / Toggle button carries its state in UI_SELECT; for operator rows
   * UI_SELECT is only "held down". */
  const bool is_toggle = ELEM(but->type, ButtonType::Row, ButtonType::Toggle, ButtonType::IconToggle);
  const bool lit = kind == MixarCinemaRowKind::Active ||
                   (is_toggle && (but->flag & UI_SELECT) != 0);
  const bool disabled = (but->flag & BUT_DISABLED) != 0;
  const bool pressed = is_active || (!is_toggle && (but->flag & UI_SELECT) != 0);

  const rctf row = row_rect(rect);
  const float rad = row_radius(row);
  if (lit) {
    draw_chip(row, rad);
  }
  else if ((is_hover || pressed) && !disabled) {
    draw_hover(row, rad, pressed ? 1.0f : 0.9f);
  }

  const uchar *col = disabled ? TEXT_DISABLED :
                                (lit || kind == MixarCinemaRowKind::Action ? TEXT_ON : TEXT_OFF);
  rcti text = *rect;
  text.xmin += int(TEXT_PAD * UI_SCALE_FAC);
  text.xmax -= int(TEXT_PAD * UI_SCALE_FAC);
  const uiFontStyle fs = row_font();
  const char *label = row_label(but);
  const float label_w = fontstyle_string_width(&fs, label);
  const bool icon_drawn = draw_leading_icon(but, rect, text, label_w, disabled ? 0.4f : 0.9f);
  draw_label(fs, &text, label, col, UI_STYLE_TEXT_LEFT, icon_drawn ? 0.0f : pad_slack(), pad_slack());
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
