/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * The provider controls' filled chevron (agent_ui_provider.hh).
 */

#include <algorithm>
#include <cmath>

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "agent_ui_provider.hh"

namespace blender {

namespace {
constexpr float PI = 3.14159265358979f;
}  // namespace

/** The frames' chevron: an equilateral triangle pointing down with softly
 *  rounded corners, filled, centred on (cx, cy). Anti-aliased by a smooth
 *  outline over the fill (the polyline shader filters at the real width). */
void agent_ui_chevron_fill_draw(
    const float cx, const float cy, const float w, const float h, const float col[4])
{
  const float r = w * 0.09f;
  const float corners[3][2] = {{cx - w * 0.5f, cy + h * 0.5f},
                               {cx + w * 0.5f, cy + h * 0.5f},
                               {cx, cy - h * 0.5f}};
  constexpr int arc = 4;
  float pts[3 * (arc + 1)][2];
  int n = 0;
  for (int i = 0; i < 3; i++) {
    const float *p = corners[i];
    const float *a = corners[(i + 2) % 3];
    const float *b = corners[(i + 1) % 3];
    float da[2] = {a[0] - p[0], a[1] - p[1]};
    float db[2] = {b[0] - p[0], b[1] - p[1]};
    const float la = std::hypot(da[0], da[1]), lb = std::hypot(db[0], db[1]);
    da[0] /= la, da[1] /= la, db[0] /= lb, db[1] /= lb;
    const float theta = std::acos(std::clamp(da[0] * db[0] + da[1] * db[1], -1.0f, 1.0f));
    const float d = r / std::tan(theta * 0.5f);
    const float bis[2] = {da[0] + db[0], da[1] + db[1]};
    const float lbis = std::hypot(bis[0], bis[1]);
    const float c[2] = {p[0] + bis[0] / lbis * r / std::sin(theta * 0.5f),
                        p[1] + bis[1] / lbis * r / std::sin(theta * 0.5f)};
    const float s[2] = {p[0] + da[0] * d, p[1] + da[1] * d};
    const float e[2] = {p[0] + db[0] * d, p[1] + db[1] * d};
    float a0 = std::atan2(s[1] - c[1], s[0] - c[0]);
    float a1 = std::atan2(e[1] - c[1], e[0] - c[0]);
    /* The short way round the corner. */
    while (a1 - a0 > PI) {
      a1 -= 2.0f * PI;
    }
    while (a0 - a1 > PI) {
      a1 += 2.0f * PI;
    }
    for (int k = 0; k <= arc; k++) {
      const float t = a0 + (a1 - a0) * float(k) / arc;
      pts[n][0] = c[0] + std::cos(t) * r;
      pts[n][1] = c[1] + std::sin(t) * r;
      n++;
    }
  }

  const GPUBlend blend_prev = GPU_blend_get();
  GPU_blend(GPU_BLEND_ALPHA);
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(col);
  immBegin(GPU_PRIM_TRI_FAN, n);
  for (int i = 0; i < n; i++) {
    immVertex2f(pos, pts[i][0], pts[i][1]);
  }
  immEnd();
  immUnbindProgram();

  float viewport[4];
  GPU_viewport_size_get_f(viewport);
  immBindBuiltinProgram(GPU_SHADER_3D_POLYLINE_UNIFORM_COLOR);
  immUniform2fv("viewportSize", &viewport[2]);
  immUniform1f("lineWidth", 1.0f);
  immUniform1i("lineSmooth", 1);
  immUniformColor4fv(col);
  immBegin(GPU_PRIM_LINE_LOOP, n);
  for (int i = 0; i < n; i++) {
    immVertex2f(pos, pts[i][0], pts[i][1]);
  }
  immEnd();
  immUnbindProgram();
  GPU_blend(blend_prev);
}

}  // namespace blender
