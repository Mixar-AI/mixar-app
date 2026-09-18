/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "BLF_api.hh"
#include "MEM_guardedalloc.h"
#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"
#include <cstring>

namespace blender::ui {
void mixar_fill_round(const rctf &rect, const float radius, const float color[4])
{
  draw_roundbox_corner_set(CNR_ALL);
  draw_roundbox_4fv(&rect, true, radius, color);
}
float mixar_text_width(const char *text, const float size)
{
  if (!text || !text[0]) {
    return 0.0f;
  }
  const int font = BLF_default();
  BLF_size(font, size);
  return BLF_width(font, text, strlen(text));
}
void mixar_label_left(
    const char *text, const float x, const float cy, const float size, const float color[4])
{
  if (!text || !text[0]) {
    return;
  }
  const int font = BLF_default();
  BLF_size(font, size);
  BLF_disable(font, BLF_CLIPPING);
  rcti box;
  BLF_boundbox(font, text, strlen(text), &box);
  BLF_color4fv(font, color);
  BLF_position(font, x, cy - float(box.ymin + box.ymax) * 0.5f, 0.0f);
  BLF_draw(font, text, strlen(text));
}
std::string mixar_fit_text(const char *text, const float max_width, const float size)
{
  if (!text || !text[0]) {
    return "";
  }
  const int font = BLF_default();
  BLF_size(font, size);
  const size_t len = strlen(text);
  if (BLF_width(font, text, len) <= max_width) {
    return text;
  }
  const char *ellipsis = "…";
  const float budget = max_width - BLF_width(font, ellipsis, strlen(ellipsis));
  if (budget < 0.0f) {
    return "";
  }
  /* One measuring pass instead of one per dropped codepoint: dropping a
   * character at a time re-shaped the whole remaining string every step, which
   * is O(n^2) glyph shaping on a path that runs per label per frame.
   * `BLF_width_to_strlen` respects UTF-8 boundaries, so the cut can never land
   * inside a multi-byte character. */
  const size_t keep = BLF_width_to_strlen(font, text, len, budget, nullptr);
  return std::string(text, keep) + ellipsis;
}
static std::string tooltip_owned(bContext *, void *arg, StringRef)
{
  return static_cast<const char *>(arg);
}
void mixar_button_tooltip_owned(Button *button, const char *text)
{
  if (!button || !text || !text[0]) {
    return;
  }
  const size_t size = strlen(text) + 1;
  char *owned = static_cast<char *>(MEM_new_uninitialized(size, __func__));
  memcpy(owned, text, size);
  button_func_tooltip_set(button, tooltip_owned, owned, MEM_delete_void);
}
}  // namespace blender::ui
