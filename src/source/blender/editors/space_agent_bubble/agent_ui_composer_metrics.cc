/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Composer text metrics: how wide the island's input wraps, how many visual
 * lines a draft takes, and the artboard height of the post-transcript strip.
 * Shared by the layout build and the region sizing (both must agree), and
 * kept beside the layout so its unit line stays the one in
 * `agent_ui_layout_build`.
 */

#include <algorithm>
#include <cstring>

#include "BLF_api.hh"

#include "BLI_string_ref.hh"
#include "BLI_vector.hh"

#include "DNA_userdef_types.h"

#include "UI_interface.hh"

#include "agent_ui_layout.hh"
#include "agent_ui_theme.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

float agent_ui_composer_wrap_width_px(const int window_w, const int pad_real_w)
{
  const bool pad = pad_real_w > 0;
  const float u = float(window_w) / float(AGENT_ISLAND_W);
  const float region_w = pad ? float(pad_real_w) : float(window_w);
  const float island_w = pad ? (region_w / u) : float(AGENT_ISLAND_W);
  const float card_w = island_w - AGENT_CARD_X * 2.0f;
  return (card_w - AGENT_SEG_X * 2.0f) * u;
}

int agent_ui_composer_visual_lines(const char *text, const float wrap_width_px)
{
  if (text == nullptr || text[0] == '\0') {
    return 1;
  }

  /* Must match widget_draw_text_multiline: native widget font, wrap width
   * after the 0.4 UI-unit text pad and 4*pixelsize inset. */
  const int text_pad = int(0.4f * U.widget_unit);
  const int width = std::max(int(wrap_width_px) - text_pad - int(4.0f * U.pixelsize), 10);

  uiFontStyle fstyle = ui::style_get()->widget;
  ui::fontstyle_set(&fstyle);
  const int fontid = fstyle.uifont_id;
  const int text_len = int(strlen(text));
  blender::Vector<blender::StringRef> lines = BLF_string_wrap(
      fontid,
      blender::StringRef(text, text_len),
      width,
      BLFWrapMode(int(BLFWrapMode::Typographical) | int(BLFWrapMode::HardLimit)));
  int count = int(lines.size());
  if (text_len > 0 && text[text_len - 1] == '\n') {
    count++;
  }
  return std::clamp(std::max(1, count), 1, AGENT_INPUT_MAX_LINES);
}

float agent_ui_composer_strip_h(const int visual_lines)
{
  const int lines = std::clamp(visual_lines, 1, AGENT_INPUT_MAX_LINES);
  return float(AGENT_INPUT_H * lines);
}

}  // namespace blender
