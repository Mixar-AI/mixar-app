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
  std::string result = text ? text : "";
  if (mixar_text_width(result.c_str(), size) <= max_width) {
    return result;
  }
  const char *ellipsis = "…";
  const float budget = max_width - mixar_text_width(ellipsis, size);
  if (budget < 0.0f) {
    return "";
  }
  while (!result.empty()) {
    size_t end = result.size() - 1;
    while (end > 0 && (static_cast<unsigned char>(result[end]) & 0xc0) == 0x80) {
      end--;
    }
    result.resize(end);
    if (mixar_text_width(result.c_str(), size) <= budget) {
      break;
    }
  }
  return result + ellipsis;
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
