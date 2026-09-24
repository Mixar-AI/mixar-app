/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Parallel Agents panel glyphs: the thin-stroke marks a card draws — eye,
 * cross, check and the "more agents" double chevron.
 *
 * Drawn from AA lines and discs rather than `ICON_*`: Blender's stock icon set
 * is weighted for toolbars and out-shouts these labels at card scale (the same
 * finding the profile card records). Split out of the draw pass to keep both
 * files inside the 500-line rule.
 */

#include <algorithm>
#include <cmath>

#include "BLI_math_base.h"
#include "BLI_rect.h"




#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_interface.hh"

#include "view3d_agent_panel.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

void view3d_agent_panel_draw_disc(const float cx, const float cy, const float radius, const float color[4])
{
  rctf disc;
  disc.xmin = cx - radius;
  disc.xmax = cx + radius;
  disc.ymin = cy - radius;
  disc.ymax = cy + radius;
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&disc, true, radius, color);
}

/* -------------------------------------------------------------------- */
/** \name Glyphs
 *
 * Drawn from AA lines and discs rather than `ICON_*`: Blender's stock icon set
 * is weighted for toolbars and out-shouts these labels at card scale (the same
 * finding the profile card records).
 * \{ */

void view3d_agent_panel_glyph_line(const float x1,
                const float y1,
                const float x2,
                const float y2,
                const float width,
                const float color[4])
{
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_POLYLINE_UNIFORM_COLOR);
  float viewport[4];
  GPU_viewport_size_get_f(viewport);
  immUniform2fv("viewportSize", &viewport[2]);
  immUniform1f("lineWidth", width);
  immUniformColor4fv(color);
  immBegin(GPU_PRIM_LINES, 2);
  immVertex2f(pos, x1, y1);
  immVertex2f(pos, x2, y2);
  immEnd();
  immUnbindProgram();
}

/** An eye: a lens outline approximated by two arcs, plus a filled pupil. */
void view3d_agent_panel_glyph_eye(const rcti &box, const float scale, const float color[4])
{
  const float cx = float(box.xmin + box.xmax + 1) * 0.5f;
  const float cy = float(box.ymin + box.ymax + 1) * 0.5f;
  const float w = float(BLI_rcti_size_x(&box)) * 0.5f;
  const float h = w * 0.62f;
  const float width = std::max(1.0f * scale, 1.0f);

  const int segments = 10;
  for (int side = 0; side < 2; side++) {
    const float dir = side == 0 ? 1.0f : -1.0f;
    float px = cx - w;
    float py = cy;
    for (int i = 1; i <= segments; i++) {
      const float t = float(i) / float(segments);
      const float nx = cx - w + 2.0f * w * t;
      const float ny = cy + dir * h * sinf(t * float(M_PI));
      view3d_agent_panel_glyph_line(px, py, nx, ny, width, color);
      px = nx;
      py = ny;
    }
  }
  view3d_agent_panel_draw_disc(cx, cy, w * 0.30f, color);
}

void view3d_agent_panel_glyph_cross(const rcti &box, const float scale, const float color[4])
{
  const float inset = float(BLI_rcti_size_x(&box)) * 0.28f;
  const float width = std::max(1.4f * scale, 1.0f);
  const float x0 = float(box.xmin) + inset;
  const float x1 = float(box.xmax + 1) - inset;
  const float y0 = float(box.ymin) + inset;
  const float y1 = float(box.ymax + 1) - inset;
  view3d_agent_panel_glyph_line(x0, y0, x1, y1, width, color);
  view3d_agent_panel_glyph_line(x0, y1, x1, y0, width, color);
}

void view3d_agent_panel_glyph_check(const rcti &box, const float scale, const float color[4])
{
  const float w = float(BLI_rcti_size_x(&box) + 1);
  const float h = float(BLI_rcti_size_y(&box) + 1);
  const float width = std::max(1.6f * scale, 1.0f);
  const float x = float(box.xmin);
  const float y = float(box.ymin);
  view3d_agent_panel_glyph_line(x + w * 0.20f, y + h * 0.52f, x + w * 0.42f, y + h * 0.28f, width, color);
  view3d_agent_panel_glyph_line(x + w * 0.42f, y + h * 0.28f, x + w * 0.82f, y + h * 0.74f, width, color);
}

/** A double chevron pointing down: "there are more agents below". */
void view3d_agent_panel_glyph_chevrons_down(const rcti &box, const float scale, const float color[4])
{
  const float cx = float(box.xmin + box.xmax + 1) * 0.5f;
  const float cy = float(box.ymin + box.ymax + 1) * 0.5f;
  const float w = float(BLI_rcti_size_x(&box)) * 0.20f;
  const float h = float(BLI_rcti_size_y(&box)) * 0.16f;
  const float width = std::max(1.4f * scale, 1.0f);
  for (int i = 0; i < 2; i++) {
    const float y = cy + h * (0.9f - float(i) * 1.8f);
    view3d_agent_panel_glyph_line(cx - w, y + h, cx, y - h, width, color);
    view3d_agent_panel_glyph_line(cx, y - h, cx + w, y + h, width, color);
  }
}


}  // namespace blender
