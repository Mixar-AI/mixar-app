/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include <cmath>

#include "BLI_rect.h"
#include "GPU_immediate.hh"
#include "GPU_state.hh"

namespace blender {

static constexpr int CORNER_SEGMENTS = 8;
static constexpr float PI = 3.14159265f;

void chat_ui_draw_rounded_rect_outline(const rctf *rect,
                                       float radius,
                                       const float color[4],
                                       float line_width)
{
#ifdef WIN32
  /* Text, icons and image painters can leave blending disabled. Never replace
   * the transcript bed with a translucent fill (or a fully transparent hole). */
  if (color[3] <= 0.0f) {
    return;
  }
  const GPUBlend previous_blend = GPU_blend_get();
  GPU_blend(GPU_BLEND_ALPHA);
#endif

  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);

  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(color);

  GPU_line_width(line_width);

  float x = rect->xmin;
  float y = rect->ymin;
  float w = BLI_rctf_size_x(rect);
  float h = BLI_rctf_size_y(rect);

  /* Clamp radius to half of smaller dimension */
  float r = radius;
  if (r > w / 2.0f) {
    r = w / 2.0f;
  }
  if (r > h / 2.0f) {
    r = h / 2.0f;
  }

  /* Calculate number of vertices: 4 corners * CORNER_SEGMENTS + 4 straight edges + 1 to close */
  int total_verts = 4 * (CORNER_SEGMENTS + 1) + 1;

  immBegin(GPU_PRIM_LINE_STRIP, total_verts);

  /* Bottom-left corner (arc from 180 to 270 degrees) */
  for (int i = 0; i <= CORNER_SEGMENTS; i++) {
    float angle = PI + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
    immVertex2f(pos, x + r + r * cosf(angle), y + r + r * sinf(angle));
  }

  /* Bottom-right corner (arc from 270 to 360 degrees) */
  for (int i = 0; i <= CORNER_SEGMENTS; i++) {
    float angle = (3.0f * PI / 2.0f) + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
    immVertex2f(pos, x + w - r + r * cosf(angle), y + r + r * sinf(angle));
  }

  /* Top-right corner (arc from 0 to 90 degrees) */
  for (int i = 0; i <= CORNER_SEGMENTS; i++) {
    float angle = 0.0f + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
    immVertex2f(pos, x + w - r + r * cosf(angle), y + h - r + r * sinf(angle));
  }

  /* Top-left corner (arc from 90 to 180 degrees) */
  for (int i = 0; i <= CORNER_SEGMENTS; i++) {
    float angle = (PI / 2.0f) + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
    immVertex2f(pos, x + r + r * cosf(angle), y + h - r + r * sinf(angle));
  }

  /* Close the loop - connect back to start */
  immVertex2f(pos, x, y + r);

  immEnd();
  immUnbindProgram();

  /* Reset line width */
  GPU_line_width(1.0f);

#ifdef WIN32
  GPU_blend(previous_blend);
#endif
}

void chat_ui_draw_rounded_rect(const rctf *rect, float radius, const float color[4])
{
#ifdef WIN32
  /* Text, icons and image painters can leave blending disabled. Never replace
   * the transcript bed with a translucent fill (or a fully transparent hole). */
  if (color[3] <= 0.0f) {
    return;
  }
  const GPUBlend previous_blend = GPU_blend_get();
  GPU_blend(GPU_BLEND_ALPHA);
#endif

  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);

  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(color);

  float x = rect->xmin;
  float y = rect->ymin;
  float w = BLI_rctf_size_x(rect);
  float h = BLI_rctf_size_y(rect);

  /* Clamp radius to half of smaller dimension */
  float r = radius;
  if (r > w / 2.0f) {
    r = w / 2.0f;
  }
  if (r > h / 2.0f) {
    r = h / 2.0f;
  }

  /* Draw main body rectangles */
  /* Center rectangle (full height, reduced width) */
  immRectf(pos, x + r, y, x + w - r, y + h);

  /* Left rectangle */
  immRectf(pos, x, y + r, x + r, y + h - r);

  /* Right rectangle */
  immRectf(pos, x + w - r, y + r, x + w, y + h - r);

  /* Draw 4 corner arcs as triangle fans */

  /* Bottom-left corner */
  immBegin(GPU_PRIM_TRI_FAN, CORNER_SEGMENTS + 2);
  immVertex2f(pos, x + r, y + r);
  for (int i = 0; i <= CORNER_SEGMENTS; i++) {
    float angle = PI + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
    immVertex2f(pos, x + r + r * cosf(angle), y + r + r * sinf(angle));
  }
  immEnd();

  /* Bottom-right corner */
  immBegin(GPU_PRIM_TRI_FAN, CORNER_SEGMENTS + 2);
  immVertex2f(pos, x + w - r, y + r);
  for (int i = 0; i <= CORNER_SEGMENTS; i++) {
    float angle = (3.0f * PI / 2.0f) + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
    immVertex2f(pos, x + w - r + r * cosf(angle), y + r + r * sinf(angle));
  }
  immEnd();

  /* Top-right corner */
  immBegin(GPU_PRIM_TRI_FAN, CORNER_SEGMENTS + 2);
  immVertex2f(pos, x + w - r, y + h - r);
  for (int i = 0; i <= CORNER_SEGMENTS; i++) {
    float angle = 0.0f + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
    immVertex2f(pos, x + w - r + r * cosf(angle), y + h - r + r * sinf(angle));
  }
  immEnd();

  /* Top-left corner */
  immBegin(GPU_PRIM_TRI_FAN, CORNER_SEGMENTS + 2);
  immVertex2f(pos, x + r, y + h - r);
  for (int i = 0; i <= CORNER_SEGMENTS; i++) {
    float angle = (PI / 2.0f) + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
    immVertex2f(pos, x + r + r * cosf(angle), y + h - r + r * sinf(angle));
  }
  immEnd();

  immUnbindProgram();

#ifdef WIN32
  GPU_blend(previous_blend);
#endif
}

void chat_ui_draw_rounded_rect_bordered(const rctf *rect,
                                        float radius,
                                        const float fill_color[4],
                                        const float border_color[4],
                                        float border_width)
{
  /* Draw border (larger rect) */
  rctf border_rect = *rect;
  BLI_rctf_pad(&border_rect, border_width, border_width);
  chat_ui_draw_rounded_rect(&border_rect, radius + border_width, border_color);

  /* Draw fill (inner rect) */
  chat_ui_draw_rounded_rect(rect, radius, fill_color);
}


}  // namespace blender
