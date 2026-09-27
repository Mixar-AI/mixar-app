/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#include <algorithm>
#include <cmath>

#include "UI_interface_icons.hh"
#include "interface_mixar_card_paint.hh"

namespace blender::ui {

/** Shared icon, label and raised version marker; native button owns input. */
inline void mixar_cinema_draw_label(const rcti &bounds,
                                    const char *label,
                                    const int icon_id,
                                    const uchar color[4],
                                    const float font_scale)
{
  const float u = UI_SCALE_FAC;
  const float icon_size = 16.0f * u;
  const bool has_icon = !ELEM(icon_id, ICON_NONE, ICON_BLANK1);
  const float leading = has_icon ? icon_size + 4.0f * u : 0.0f;
  const float gap = 3.0f * u;
  uiFontStyle font = mixar_card_font(font_scale, 0);
  uiFontStyle version_font = mixar_card_font(font_scale * 0.60f, 500);
  float text_width = fontstyle_string_width(&font, label);
  float version_width = fontstyle_string_width(&version_font, "V1");
  const float available = std::max(1.0f, BLI_rcti_size_x(&bounds) -
                                           14.0f * u - leading - gap);
  if (text_width + version_width > available) {
    const float fit = available / (text_width + version_width);
    font.points *= fit;
    version_font.points *= fit;
    text_width = fontstyle_string_width(&font, label);
    version_width = fontstyle_string_width(&version_font, "V1");
  }
  const float left = (bounds.xmin + bounds.xmax - leading - text_width -
                      gap - version_width) * 0.5f;
  if (has_icon) {
    icon_draw_ex(left,
                 (bounds.ymin + bounds.ymax - icon_size) * 0.5f,
                 icon_id, 1.0f, 1.0f, 0.0f, color, false, nullptr, false,
                 icon_size / 16.0f);
  }
  rcti text = bounds;
  text.xmin = int(std::round(left + leading));
  text.xmax = int(std::ceil(left + leading + text_width));
  mixar_card_draw_text(font, &text, label, color, UI_STYLE_TEXT_LEFT);
  rcti version = bounds;
  version.xmin = int(std::round(left + leading + text_width + gap));
  version.xmax = int(std::ceil(left + leading + text_width + gap + version_width));
  BLI_rcti_translate(&version, 0, int(std::round(4.0f * u)));
  mixar_card_draw_text(version_font, &version, "V1", color, UI_STYLE_TEXT_LEFT);
}

}  // namespace blender::ui
