/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Kinsoku over BLF's typographical wrap.
 *
 * BLF may break after any CJK character, so a plain bubble could end with a
 * line holding only its closing 。. These helpers re-run the wrap from an
 * earlier break whenever a soft break would start a line with a closer (or
 * end one with an opener), so draw, measure, selection and hit testing all
 * see the same corrected lines.
 */

#include <cstring>
#include <string>
#include <utility>

#include "BLI_string_ref.hh"
#include "BLI_vector.hh"

#include "BLF_api.hh"

#include "mixie_chat_line_break.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

bool chat_ui_wrap_lines(const int font_id,
                        const char *text,
                        const int width,
                        const BLFWrapMode mode,
                        Vector<StringRef> &r_lines)
{
  r_lines.clear();
  const int len = int(strlen(text));
  Vector<StringRef> lines = BLF_string_wrap(font_id, text, width, mode);
  if (mode != CHAT_PROSE_WRAP) {
    r_lines = std::move(lines);
    return false;
  }
  bool adjusted = false;
  for (int k = 0; k < int(lines.size());) {
    const StringRef line = lines[k];
    if (k + 1 < int(lines.size())) {
      const int line_start = int(line.data() - text);
      const int line_end = line_start + int(line.size());
      /* Only a soft break (nothing dropped between the lines) can move. */
      if (int(lines[k + 1].data() - text) == line_end) {
        const int brk = chat_ui_kinsoku_break(text, line_start, line_end, len);
        if (brk != line_end) {
          r_lines.append(StringRef(text + line_start, brk - line_start));
          adjusted = true;
          lines = BLF_string_wrap(font_id, StringRef(text + brk, len - brk), width, mode);
          k = 0;
          continue;
        }
      }
    }
    r_lines.append(line);
    k++;
  }
  return adjusted;
}

const char *chat_ui_prose_text(const int font_id,
                               const char *text,
                               const int width,
                               const BLFWrapMode mode,
                               std::string &r_storage)
{
  if (mode != CHAT_PROSE_WRAP) {
    return text;
  }
  Vector<StringRef> lines;
  if (!chat_ui_wrap_lines(font_id, text, width, mode, lines)) {
    return text;
  }
  /* Explicit newlines at the corrected breaks; every line already fits, so
   * BLF's own wrap leaves them as they are. */
  r_storage.clear();
  for (int k = 0; k < int(lines.size()); k++) {
    if (k > 0) {
      r_storage += '\n';
    }
    r_storage.append(lines[k].data(), size_t(lines[k].size()));
  }
  return r_storage.c_str();
}

}  // namespace blender
