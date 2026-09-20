/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "BLF_api.hh"
#include "MEM_guardedalloc.h"
#include "UI_interface.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include <algorithm>
#include <cmath>
#include <cstring>

namespace blender::ui {
void mixar_fill_round(const rctf &rect, const float radius, const float color[4])
{
  /* Widget roundboxes dest-over with GPU_BLEND_ALPHA and do not reliably
   * raise dest A on WGL. Opaque chrome must replace dest alpha the same
   * way the frost wash does. Keep CNR_ALL: mixar_component_draw outlines
   * with a widget roundbox and used to inherit this side effect. */
  draw_roundbox_corner_set(CNR_ALL);
  if (color[3] <= 0.0f) {
    return;
  }
  const float x0 = rect.xmin;
  const float x1 = rect.xmax;
  const float y0 = rect.ymin;
  const float y1 = rect.ymax;
  const float w = x1 - x0;
  const float h = y1 - y0;
  if (w <= 0.0f || h <= 0.0f) {
    return;
  }
  const float premul[4] = {
      color[0] * color[3], color[1] * color[3], color[2] * color[3], color[3]};
  const float fade[4] = {0.0f, 0.0f, 0.0f, 0.0f};
  const GPUBlend prev = GPU_blend_get();
  GPU_color_mask(true, true, true, true);
  GPU_blend(color[3] >= 0.999f ? GPU_BLEND_NONE : GPU_BLEND_ALPHA_PREMULT);

  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  const uint col = GPU_vertformat_attr_add(
      format, "color", blender::gpu::VertAttrType::SFLOAT_32_32_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_SMOOTH_COLOR);

  const float r = std::min(radius, std::min(w, h) * 0.5f);
  if (r < 0.5f) {
    immBegin(GPU_PRIM_TRI_FAN, 4);
    immAttr4fv(col, premul);
    immVertex2f(pos, x0, y0);
    immAttr4fv(col, premul);
    immVertex2f(pos, x1, y0);
    immAttr4fv(col, premul);
    immVertex2f(pos, x1, y1);
    immAttr4fv(col, premul);
    immVertex2f(pos, x0, y1);
    immEnd();
    immUnbindProgram();
    GPU_blend(prev);
    return;
  }

  /* Same tessellation and half-pixel feather as fill_round_gradient: a raw
   * fan has no coverage AA in a non-multisampled UI region. */
  constexpr int ARC_MAX = 32;
  constexpr int RIM_MAX = (ARC_MAX + 1) * 4;
  const int arc = std::clamp(int(std::ceil(r)), 8, ARC_MAX);
  const float aa = 0.5f;
  float rim[RIM_MAX][2];
  float nrm[RIM_MAX][2];
  int n = 0;
  const float cx[4] = {x1 - r, x1 - r, x0 + r, x0 + r};
  const float cy[4] = {y0 + r, y1 - r, y1 - r, y0 + r};
  constexpr float pi = 3.14159265f;
  for (int corner = 0; corner < 4; corner++) {
    const float base = pi * -0.5f + float(corner) * pi * 0.5f;
    for (int i = 0; i <= arc; i++) {
      const float ang = base + (pi * 0.5f) * (float(i) / float(arc));
      const float cs = std::cos(ang);
      const float sn = std::sin(ang);
      nrm[n][0] = cs;
      nrm[n][1] = sn;
      rim[n][0] = cx[corner] + cs * r;
      rim[n][1] = cy[corner] + sn * r;
      n++;
    }
  }

  immBegin(GPU_PRIM_TRI_FAN, n + 2);
  immAttr4fv(col, premul);
  immVertex2f(pos, (x0 + x1) * 0.5f, (y0 + y1) * 0.5f);
  for (int i = 0; i < n; i++) {
    immAttr4fv(col, premul);
    immVertex2f(pos, rim[i][0] - nrm[i][0] * aa, rim[i][1] - nrm[i][1] * aa);
  }
  immAttr4fv(col, premul);
  immVertex2f(pos, rim[0][0] - nrm[0][0] * aa, rim[0][1] - nrm[0][1] * aa);
  immEnd();

  GPU_blend(GPU_BLEND_ALPHA_PREMULT);
  immBegin(GPU_PRIM_TRI_STRIP, (n + 1) * 2);
  for (int i = 0; i <= n; i++) {
    const int k = (i == n) ? 0 : i;
    immAttr4fv(col, premul);
    immVertex2f(pos, rim[k][0] - nrm[k][0] * aa, rim[k][1] - nrm[k][1] * aa);
    immAttr4fv(col, fade);
    immVertex2f(pos, rim[k][0] + nrm[k][0] * aa, rim[k][1] + nrm[k][1] * aa);
  }
  immEnd();
  immUnbindProgram();
  GPU_blend(prev);
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
