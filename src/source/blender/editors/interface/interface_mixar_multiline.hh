/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#include <algorithm>
#include <cstring>

#include "BLI_rect.h"
#include "BLI_string_ref.hh"
#include "BLI_vector.hh"
#include "BLF_api.hh"
#include "DNA_theme_types.h"

namespace blender::ui {

/* Geometry is captured after native widget padding, in region pixels.
 * Each Text button owns its scroll state; unrelated fields cannot reset it. */
struct MixarMultilineState {
  rcti text_rect = {};
  uiFontStyle font = {};
  int wrap_width = 0;
  int line_height = 1;
  int visible_lines = 1;
  int scroll_offset = 0;
  int previous_cursor = -1;
  int touchpad_accum = 0;
  bool was_editing = false;
  bool valid = false;
};

/* The painter and event handler use the same wrapped strings and byte indices. */
inline Vector<StringRef> mixar_multiline_wrap(const int fontid,
                                             const char *text,
                                             const int width,
                                             Vector<int> &offsets)
{
  Vector<StringRef> lines = BLF_string_wrap(
      fontid, text, width,
      BLFWrapMode(int(BLFWrapMode::Typographical) | int(BLFWrapMode::HardLimit)));
  for (StringRef &line : lines) {
    if (!line.is_empty() && line[line.size() - 1] == '\n') {
      line = StringRef(line.data(), line.size() - 1);
    }
  }
  const int length = int(strlen(text));
  if (length && text[length - 1] == '\n') {
    lines.append(StringRef(text + length, int64_t(0)));
  }
  if (lines.is_empty()) {
    lines.append(StringRef(text, int64_t(0)));
  }
  offsets.clear();
  for (const StringRef line : lines) {
    /* Empty BLF lines also point into the source; preserve consecutive newlines. */
    offsets.append(int(line.data() - text));
  }
  return lines;
}

}  // namespace blender::ui
