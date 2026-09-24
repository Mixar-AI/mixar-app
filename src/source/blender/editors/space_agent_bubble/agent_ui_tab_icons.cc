/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include <algorithm>
#include <cmath>
#include "BLI_rect.h"
#include "GPU_immediate.hh"
#include "UI_interface.hh"
#include "agent_ui_icons.hh"

namespace blender {
namespace {
void disc(float x, float y, float radius, const float color[4])
{
  rctf rect{x - radius, x + radius, y - radius, y + radius};
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&rect, true, radius, color);
}
/** Stroke a polyline given in glyph-box fractions of \a s about (cx, cy).
 *
 * A silhouette punch cannot express the traced artwork: the design's outlines
 * cross themselves (the thumb re-enters the fist) and a punch fills that
 * crossing solid. Every segment quad goes into ONE triangle batch — a
 * flattened Bezier is dozens of segments, and a draw call each would put a
 * shader bind per segment on the tab strip's per-frame cost. Joins are only
 * capped where the path actually turns; between the dense samples of a curve
 * the notch is well under a pixel.
 */
void stroke_path(const float (*pts)[2],
                 const int count,
                 const float cx,
                 const float cy,
                 const float s,
                 const float w,
                 const bool closed,
                 const float col[4])
{
  if (count < 2) {
    return;
  }
  const float half = w * 0.5f;
  auto at = [&](const int i, float &x, float &y) {
    x = cx + pts[i][0] * s;
    y = cy + pts[i][1] * s;
  };

  const int segments = closed ? count : count - 1;

  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(col);
  immBegin(GPU_PRIM_TRIS, segments * 6);

  for (int i = 0; i < segments; i++) {
    float ax, ay, bx, by;
    at(i, ax, ay);
    at((i + 1) % count, bx, by);

    float dx = bx - ax;
    float dy = by - ay;
    const float len = std::sqrt(dx * dx + dy * dy);
    if (len < 1e-6f) {
      /* Degenerate samples still owe the batch its six vertices. */
      dx = 1.0f;
      dy = 0.0f;
    }
    else {
      dx /= len;
      dy /= len;
    }
    const float nx = -dy * half;
    const float ny = dx * half;

    immVertex2f(pos, ax + nx, ay + ny);
    immVertex2f(pos, bx + nx, by + ny);
    immVertex2f(pos, bx - nx, by - ny);
    immVertex2f(pos, ax + nx, ay + ny);
    immVertex2f(pos, bx - nx, by - ny);
    immVertex2f(pos, ax - nx, ay - ny);
  }

  immEnd();
  immUnbindProgram();

  /* Round the corners and the open ends. */
  const int joins = closed ? count : count - 2;
  for (int j = 0; j < joins; j++) {
    const int i = closed ? j : j + 1;
    float px, py, vx, vy, nx2, ny2;
    at((i - 1 + count) % count, px, py);
    at(i, vx, vy);
    at((i + 1) % count, nx2, ny2);

    const float ux = vx - px, uy = vy - py;
    const float wx = nx2 - vx, wy = ny2 - vy;
    const float ul = std::sqrt(ux * ux + uy * uy);
    const float wl = std::sqrt(wx * wx + wy * wy);
    if (ul < 1e-6f || wl < 1e-6f) {
      continue;
    }
    /* cos of the turn; only cap where the miter would actually notch. */
    if ((ux * wx + uy * wy) / (ul * wl) < 0.985f) {
      disc(vx, vy, half, col);
    }
  }
  if (!closed) {
    float x, y;
    at(0, x, y);
    disc(x, y, half, col);
    at(count - 1, x, y);
    disc(x, y, half, col);
  }
}

}  // namespace

/* Thin-stroke glyphs balance the neighboring marks at compact sizes. */
void agent_ui_tab_icon_draw(AgentIcon icon, float cx, float cy, float size, const float color[4])
{
  const float weight = std::max(1.0f, size / 14.0f);
  if (icon == AGENT_ICON_SIGNATURE) {
    /* A short signed name: one rising stroke and the line it sits on. */
    static const float stroke[][2] = {
        {-.32f, -.04f},
        {-.20f, .20f},
        {-.06f, -.14f},
        {.06f, .18f},
        {.20f, -.06f},
        {.34f, .06f},
    };
    static const float baseline[][2] = {{-.24f, -.26f}, {.32f, -.26f}};
    stroke_path(stroke, 6, cx, cy, size, weight, false, color);
    stroke_path(baseline, 2, cx, cy, size, weight, false, color);
    return;
  }
  if (icon == AGENT_ICON_RULES) {
    static const float page[][2] = {
        {-.25f, -.32f}, {.25f, -.32f}, {.25f, .14f}, {.07f, .32f}, {-.25f, .32f}};
    static const float fold[][2] = {{.07f, .32f}, {.07f, .14f}, {.25f, .14f}};
    stroke_path(page, 5, cx, cy, size, weight, true, color);
    stroke_path(fold, 3, cx, cy, size, weight, false, color);
    for (const float y : {.04f, -.12f}) {
      const float line[][2] = {{-.12f, y}, {.12f, y}};
      stroke_path(line, 2, cx, cy, size, weight, false, color);
    }
    return;
  }
  if (icon != AGENT_ICON_VIDEO) {
    return;
  }
  static const float body[][2] = {{-.40f,-.28f},{.12f,-.28f},{.12f,.28f},{-.40f,.28f}};
  static const float lens[][2] = {{.12f,-.12f},{.40f,-.28f},{.40f,.28f},{.12f,.12f}};
  stroke_path(body, 4, cx, cy, size, weight, true, color);
  stroke_path(lens, 4, cx, cy, size, weight, true, color);
}
}  // namespace blender
