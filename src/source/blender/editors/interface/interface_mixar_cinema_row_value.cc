/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Cinema Mode popup rows: the caption, the slider and the field
 * (#MixarCinemaRowKind::Caption / Slider / Field).
 *
 * - Caption: dim caption text at the row padding, optional leading icon, no
 *   chrome — the surface's 12 px captions against its 13 px values.
 * - Slider: a `ButtonType::NumSlider` drawn as the row class: a dark track
 *   with the surface's green fill to the value, label left, value right.
 *   Only drawing changes — click-drag, ctrl-click and double-click-to-type
 *   are the stock button's.
 * - Field: a `ButtonType::Text` laid over text the surface painted itself:
 *   nothing while idle. While editing, the dispatcher in
 *   `interface_mixar_cinema_row.cc` lays the chip and the stock text pass
 *   draws the edit string on top.
 */

#include <algorithm>
#include <cstring>
#include <string>

#include "BLI_rect.h"
#include "BLI_utildefines.h"

#include "UI_interface_c.hh"
#include "UI_interface_icons.hh"
#include "UI_mixar_motion.hh"

#include "interface_intern.hh"
#include "interface_mixar_card_paint.hh"
#include "interface_mixar_cinema_row.hh"
#include "interface_mixar_profile_card.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender::ui::mixar_cinema_row {

namespace {

/** "Resolution: " -> "Resolution". */
std::string label_without_separator(const std::string &str)
{
  std::string label = str;
  while (!label.empty() && (label.back() == ':' || label.back() == ' ')) {
    label.pop_back();
  }
  return label;
}

/**
 * The value part of a number button's `drawstr`, which Blender builds as
 * `str` + value (+ unit); strip the label so it is not printed twice.
 */
std::string value_text(const Button *but)
{
  const std::string &drawstr = but->drawstr;
  std::string value = drawstr;
  if (!but->str.empty() && drawstr.compare(0, but->str.size(), but->str) == 0) {
    value = drawstr.substr(but->str.size());
  }
  size_t start = 0;
  while (start < value.size() && (value[start] == ' ' || value[start] == ':')) {
    start++;
  }
  return value.substr(start);
}

rcti padded_text_rect(const rcti *rect)
{
  rcti text = *rect;
  text.xmin += int(TEXT_PAD * UI_SCALE_FAC);
  text.xmax -= int(TEXT_PAD * UI_SCALE_FAC);
  return text;
}

}  // namespace

void draw_caption(Button *but, const rcti *rect)
{
  const uiFontStyle fs = caption_font();
  const char *label = row_label(but);
  rcti text = padded_text_rect(rect);
  const float label_w = fontstyle_string_width(&fs, label);
  /* Same rule as the option row: icon then label, icon dropped if tight. */
  const bool icon_drawn = draw_leading_icon(but, rect, text, label_w, 0.55f);
  draw_label(
      fs, &text, label, CAPTION, UI_STYLE_TEXT_LEFT, icon_drawn ? 0.0f : pad_slack(), pad_slack());
}

void draw_slider(Button *but, const rcti *rect, const bool /*is_hover*/)
{
  const bool disabled = (but->flag & (BUT_DISABLED | BUT_INACTIVE)) != 0;
  const rctf row = row_rect(rect);
  const float rad = row_radius(row);

  /* Track: the popup hover fill, a step darker at rest. Never the lit chip —
   * that ramp means "the active choice". */
  const MixarInteraction motion = mixar_button_motion(*but);
  const float emphasis = std::max(motion.hover, motion.press);
  uchar track[4];
  for (int i = 0; i < 4; i++) {
    track[i] = uchar(float(TRACK[i]) + (float(HOVER[i]) - TRACK[i]) * emphasis);
  }
  mixar_card_fill_round(&row, rad, track, 1.0f);

  /* Fill from the left to the value's place in the SOFT range (what the
   * drag travels). */
  const double span = double(but->softmax) - double(but->softmin);
  const double value = button_value_get(but);
  const float fraction = span > 0.0 ?
                             std::clamp(float((value - double(but->softmin)) / span), 0.0f, 1.0f) :
                             0.0f;
  if (fraction > 0.0f) {
    rctf fill = row;
    fill.xmax = row.xmin + BLI_rctf_size_x(&row) * fraction;
    const float fill_rad = std::min(rad, BLI_rctf_size_x(&fill) * 0.5f);
    mixar_card_fill_round(&fill, fill_rad, SLIDER_ON, disabled ? 0.45f : 1.0f);
  }

  const uiFontStyle fs = row_font();
  const uchar *col = disabled ? TEXT_DISABLED : TEXT_ON;
  const rcti text = padded_text_rect(rect);

  /* Value right-aligned; the label takes what is left, ellipsised if tight. */
  const std::string value_str = value_text(but);
  const float value_w = fontstyle_string_width(&fs, value_str.c_str());
  mixar_card_draw_text(fs, &text, value_str.c_str(), col, UI_STYLE_TEXT_RIGHT);

  const std::string label = label_without_separator(but->str);
  rcti label_rect = text;
  label_rect.xmax -= int(value_w + 8.0f * UI_SCALE_FAC);
  /* The right edge is the value, so only the left pad may give. */
  draw_label(fs, &label_rect, label.c_str(), col, UI_STYLE_TEXT_LEFT, pad_slack(), 0.0f);
}

void draw_field(Button * /*but*/, const rcti * /*rect*/)
{
  /* Idle: paint nothing — the surface painted the text this field sits
   * over. The editing chip is laid by the dispatcher (`editstr` set). */
}

}  // namespace blender::ui::mixar_cinema_row
