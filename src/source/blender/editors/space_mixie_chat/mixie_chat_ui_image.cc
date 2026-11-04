/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Low-level GPU drawing primitives for chat UI.
 * Provides rounded rectangles, text rendering, and image drawing.
 */

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <string>

#include "BLI_math_vector.h"
#include "BLI_rect.h"

#include "BLF_api.hh"

#include "GPU_immediate.hh"
#include "GPU_matrix.hh"
#include "GPU_state.hh"
#include "GPU_texture.hh"

#include "ED_mixar_glass.hh"

#include "mixie_chat_line_break.hh"
#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

static constexpr int CORNER_SEGMENTS = 8;
static constexpr float PI = 3.14159265f;

/* -------------------------------------------------------------------- */
/** \name Image Drawing
 * \{ */

void chat_ui_draw_image(blender::gpu::Texture *tex,
                        const rctf *rect,
                        float corner_radius)
{
  if (!tex) {
    return;
  }

  float width = BLI_rctf_size_x(rect);
  float height = BLI_rctf_size_y(rect);

  /* Clamp radius to half of smaller dimension */
  float r = corner_radius;
  if (r > width / 2.0f) {
    r = width / 2.0f;
  }
  if (r > height / 2.0f) {
    r = height / 2.0f;
  }

  GPU_texture_bind(tex, 0);
  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  uint texcoord = GPU_vertformat_attr_add(
      format, "texCoord", blender::gpu::VertAttrType::SFLOAT_32_32);

  immBindBuiltinProgram(GPU_SHADER_3D_IMAGE);
  GPU_texture_filter_mode(tex, true);

  /* If radius is too small, just draw rectangular image */
  if (r < 1.0f) {
    immBegin(GPU_PRIM_TRI_FAN, 4);
    immAttr2f(texcoord, 0.0f, 0.0f);
    immVertex2f(pos, rect->xmin, rect->ymin);
    immAttr2f(texcoord, 1.0f, 0.0f);
    immVertex2f(pos, rect->xmax, rect->ymin);
    immAttr2f(texcoord, 1.0f, 1.0f);
    immVertex2f(pos, rect->xmax, rect->ymax);
    immAttr2f(texcoord, 0.0f, 1.0f);
    immVertex2f(pos, rect->xmin, rect->ymax);
    immEnd();
  }
  else {
    /* Draw image with rounded corners using a rounded rectangle mesh */
    float x = rect->xmin;
    float y = rect->ymin;
    float w = width;
    float h = height;

    /* Helper lambdas to calculate texture coordinates */
    auto tex_u = [x, w](float px) { return (px - x) / w; };
    auto tex_v = [y, h](float py) { return (py - y) / h; };

    /* Draw center rectangle */
    immBegin(GPU_PRIM_TRI_FAN, 4);
    immAttr2f(texcoord, tex_u(x + r), tex_v(y));
    immVertex2f(pos, x + r, y);
    immAttr2f(texcoord, tex_u(x + w - r), tex_v(y));
    immVertex2f(pos, x + w - r, y);
    immAttr2f(texcoord, tex_u(x + w - r), tex_v(y + h));
    immVertex2f(pos, x + w - r, y + h);
    immAttr2f(texcoord, tex_u(x + r), tex_v(y + h));
    immVertex2f(pos, x + r, y + h);
    immEnd();

    /* Draw left rectangle */
    immBegin(GPU_PRIM_TRI_FAN, 4);
    immAttr2f(texcoord, tex_u(x), tex_v(y + r));
    immVertex2f(pos, x, y + r);
    immAttr2f(texcoord, tex_u(x + r), tex_v(y + r));
    immVertex2f(pos, x + r, y + r);
    immAttr2f(texcoord, tex_u(x + r), tex_v(y + h - r));
    immVertex2f(pos, x + r, y + h - r);
    immAttr2f(texcoord, tex_u(x), tex_v(y + h - r));
    immVertex2f(pos, x, y + h - r);
    immEnd();

    /* Draw right rectangle */
    immBegin(GPU_PRIM_TRI_FAN, 4);
    immAttr2f(texcoord, tex_u(x + w - r), tex_v(y + r));
    immVertex2f(pos, x + w - r, y + r);
    immAttr2f(texcoord, tex_u(x + w), tex_v(y + r));
    immVertex2f(pos, x + w, y + r);
    immAttr2f(texcoord, tex_u(x + w), tex_v(y + h - r));
    immVertex2f(pos, x + w, y + h - r);
    immAttr2f(texcoord, tex_u(x + w - r), tex_v(y + h - r));
    immVertex2f(pos, x + w - r, y + h - r);
    immEnd();

    /* Draw the 4 corners as triangle fans */
    /* Bottom-left corner */
    immBegin(GPU_PRIM_TRI_FAN, CORNER_SEGMENTS + 2);
    immAttr2f(texcoord, tex_u(x + r), tex_v(y + r));
    immVertex2f(pos, x + r, y + r);
    for (int i = 0; i <= CORNER_SEGMENTS; i++) {
      float angle = PI + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
      float px = x + r + r * cosf(angle);
      float py = y + r + r * sinf(angle);
      immAttr2f(texcoord, tex_u(px), tex_v(py));
      immVertex2f(pos, px, py);
    }
    immEnd();

    /* Bottom-right corner */
    immBegin(GPU_PRIM_TRI_FAN, CORNER_SEGMENTS + 2);
    immAttr2f(texcoord, tex_u(x + w - r), tex_v(y + r));
    immVertex2f(pos, x + w - r, y + r);
    for (int i = 0; i <= CORNER_SEGMENTS; i++) {
      float angle = (3.0f * PI / 2.0f) + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
      float px = x + w - r + r * cosf(angle);
      float py = y + r + r * sinf(angle);
      immAttr2f(texcoord, tex_u(px), tex_v(py));
      immVertex2f(pos, px, py);
    }
    immEnd();

    /* Top-right corner */
    immBegin(GPU_PRIM_TRI_FAN, CORNER_SEGMENTS + 2);
    immAttr2f(texcoord, tex_u(x + w - r), tex_v(y + h - r));
    immVertex2f(pos, x + w - r, y + h - r);
    for (int i = 0; i <= CORNER_SEGMENTS; i++) {
      float angle = 0.0f + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
      float px = x + w - r + r * cosf(angle);
      float py = y + h - r + r * sinf(angle);
      immAttr2f(texcoord, tex_u(px), tex_v(py));
      immVertex2f(pos, px, py);
    }
    immEnd();

    /* Top-left corner */
    immBegin(GPU_PRIM_TRI_FAN, CORNER_SEGMENTS + 2);
    immAttr2f(texcoord, tex_u(x + r), tex_v(y + h - r));
    immVertex2f(pos, x + r, y + h - r);
    for (int i = 0; i <= CORNER_SEGMENTS; i++) {
      float angle = (PI / 2.0f) + (PI / 2.0f) * float(i) / float(CORNER_SEGMENTS);
      float px = x + r + r * cosf(angle);
      float py = y + h - r + r * sinf(angle);
      immAttr2f(texcoord, tex_u(px), tex_v(py));
      immVertex2f(pos, px, py);
    }
    immEnd();
  }

  immUnbindProgram();
  GPU_texture_unbind(tex);
}

void chat_ui_calc_image_bounds(int tex_width,
                               int tex_height,
                               float max_width,
                               float max_height,
                               float *out_width,
                               float *out_height)
{
  if (tex_width <= 0 || tex_height <= 0) {
    *out_width = 0.0f;
    *out_height = 0.0f;
    return;
  }

  float aspect = float(tex_width) / float(tex_height);
  float display_width = max_width;
  float display_height = display_width / aspect;

  /* Clamp to max height */
  if (display_height > max_height) {
    display_height = max_height;
    display_width = display_height * aspect;
  }

  /* Clamp to max width again in case aspect made it exceed */
  if (display_width > max_width) {
    display_width = max_width;
    display_height = display_width / aspect;
  }

  *out_width = display_width;
  *out_height = display_height;
}

/** \} */
}  // namespace blender
