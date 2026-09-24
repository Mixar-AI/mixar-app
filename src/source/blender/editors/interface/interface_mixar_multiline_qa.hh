/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#include "BLI_string_utf8.h"
#include "interface_intern.hh"

namespace blender::ui {

/* Inspect the painter's layout, never reconstruct padding or font scale in a test.
 * Offsets are UTF-8 bytes, matching the native text editor. No clipboard access. */
inline std::string mixar_text_edit_qa_json(const Button &but, const ARegion &region)
{
  if (!but.editstr) {
    return "";
  }
  std::string out = ",\"text_edit\":{\"cursor\":" + std::to_string(but.pos) +
                    ",\"selection\":[" + std::to_string(but.selsta) + "," +
                    std::to_string(but.selend) + "]";
  if (but.type == ButtonType::Text && (but.flag & BUT_TEXTEDIT_UPDATE) &&
      BLI_rctf_size_y(&but.rect) > UI_UNIT_Y * 1.5f)
  {
    const MixarMultilineState &state = static_cast<const ButtonText &>(but).multiline;
    if (state.valid) {
      fontstyle_set(&state.font);
      Vector<int> offsets;
      const auto lines = mixar_multiline_wrap(
          state.font.uifont_id, but.editstr, state.wrap_width, offsets);
      out += ",\"scroll\":" + std::to_string(state.scroll_offset) + ",\"carets\":[";
      bool first = true;
      int count = 0;
      for (int i = state.scroll_offset;
           i < std::min(int(lines.size()), state.scroll_offset + state.visible_lines); i++)
      {
        const StringRef line = lines[i];
        for (int byte = 0; byte <= line.size() && count < 4096; count++) {
          const int x = state.text_rect.xmin + region.winrct.xmin +
              BLF_str_offset_to_cursor(state.font.uifont_id, line.data(), int(line.size()),
                                       byte, std::max(1, int(U.pixelsize * 2)));
          const int y = state.text_rect.ymax + region.winrct.ymin -
              (i - state.scroll_offset) * state.line_height - state.line_height / 2;
          if (!first) {
            out += ',';
          }
          first = false;
          out += "{\"byte\":" + std::to_string(offsets[i] + byte) +
                 ",\"x\":" + std::to_string(x) + ",\"y\":" + std::to_string(y) + "}";
          if (byte == line.size()) {
            break;
          }
          byte += BLI_str_utf8_size_safe(line.data() + byte);
        }
      }
      out += ']';
    }
  }
  return out + '}';
}

}  // namespace blender::ui
