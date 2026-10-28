/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Vector video glyphs: outlined icons with fixed-pixel strokes.
 *
 * Drawn as geometry rather than icon-font textures so a card's icons scale
 * with the card at every zoom and stay sharp, while the stroke width stays a
 * constant number of screen pixels (polyline shader).
 */

#include "mixie_moodboard_video_glyphs.hh"

#include <cmath>

#include "BLI_math_constants.h"

#include "GPU_immediate.hh"
#include "GPU_immediate_util.hh"
#include "GPU_state.hh"

namespace blender::ed::mixie {

struct GlyphPen {
  float cx, cy, s;
  uint pos;
};

static void pen_vertex(const GlyphPen &pen, const float x, const float y)
{
  immVertex2f(pen.pos, pen.cx + x * pen.s, pen.cy + y * pen.s);
}

static void stroke_begin(GlyphPen &pen, const float line_px, const float color[4])
{
  GPUVertFormat *format = immVertexFormat();
  pen.pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_POLYLINE_UNIFORM_COLOR);
  float viewport[4];
  GPU_viewport_size_get_f(viewport);
  immUniform2fv("viewportSize", &viewport[2]);
  immUniform1f("lineWidth", line_px);
  immUniform1i("lineSmooth", 1);
  immUniformColor4fv(color);
}

static void fill_begin(GlyphPen &pen, const float color[4])
{
  GPUVertFormat *format = immVertexFormat();
  pen.pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(color);
}

/** Open polyline through \a points (x, y pairs in box units). */
static void polyline(const GlyphPen &pen, const float (*points)[2], const int count)
{
  immBegin(GPU_PRIM_LINE_STRIP, count);
  for (int i = 0; i < count; i++) {
    pen_vertex(pen, points[i][0], points[i][1]);
  }
  immEnd();
}

static void segment(const GlyphPen &pen, float x0, float y0, float x1, float y1)
{
  immBegin(GPU_PRIM_LINES, 2);
  pen_vertex(pen, x0, y0);
  pen_vertex(pen, x1, y1);
  immEnd();
}

static void arc(const GlyphPen &pen, const float x, const float y, const float radius)
{
  constexpr int steps = 12;
  constexpr float half_angle = float(M_PI) * 0.27f;
  immBegin(GPU_PRIM_LINE_STRIP, steps + 1);
  for (int i = 0; i <= steps; i++) {
    const float angle = -half_angle + 2.0f * half_angle * float(i) / float(steps);
    pen_vertex(pen, x + radius * std::cos(angle), y + radius * std::sin(angle));
  }
  immEnd();
}

static void speaker(const GlyphPen &pen)
{
  static const float body[][2] = {{-0.44f, -0.15f},
                                  {-0.22f, -0.15f},
                                  {0.04f, -0.38f},
                                  {0.04f, 0.38f},
                                  {-0.22f, 0.15f},
                                  {-0.44f, 0.15f},
                                  {-0.44f, -0.15f}};
  polyline(pen, body, 7);
}

void video_glyph_draw(const VideoGlyph glyph,
                      const float cx,
                      const float cy,
                      const float size,
                      const float line_px,
                      const float color[4])
{
  GlyphPen pen{cx, cy, size, 0};
  GPU_blend(GPU_BLEND_ALPHA);

  switch (glyph) {
    case VideoGlyph::Play: {
      fill_begin(pen, color);
      immBegin(GPU_PRIM_TRIS, 3);
      pen_vertex(pen, -0.30f, -0.44f);
      pen_vertex(pen, 0.42f, 0.0f);
      pen_vertex(pen, -0.30f, 0.44f);
      immEnd();
      break;
    }
    case VideoGlyph::Pause: {
      fill_begin(pen, color);
      immRectf(pen.pos, cx - 0.30f * size, cy - 0.40f * size, cx - 0.08f * size, cy + 0.40f * size);
      immRectf(pen.pos, cx + 0.08f * size, cy - 0.40f * size, cx + 0.30f * size, cy + 0.40f * size);
      break;
    }
    case VideoGlyph::OpenPreview: {
      /* A window with an arrow leaving its top-right corner. */
      stroke_begin(pen, line_px, color);
      static const float frame[][2] = {
          {0.02f, 0.40f}, {-0.40f, 0.40f}, {-0.40f, -0.40f}, {0.40f, -0.40f}, {0.40f, -0.02f}};
      polyline(pen, frame, 5);
      segment(pen, -0.02f, 0.02f, 0.46f, 0.46f);
      static const float head[][2] = {{0.16f, 0.46f}, {0.46f, 0.46f}, {0.46f, 0.16f}};
      polyline(pen, head, 3);
      break;
    }
    case VideoGlyph::SoundOn: {
      stroke_begin(pen, line_px, color);
      speaker(pen);
      arc(pen, 0.04f, 0.0f, 0.20f);
      arc(pen, 0.04f, 0.0f, 0.36f);
      break;
    }
    case VideoGlyph::SoundOff: {
      stroke_begin(pen, line_px, color);
      speaker(pen);
      segment(pen, -0.42f, -0.44f, 0.44f, 0.44f);
      break;
    }
  }

  immUnbindProgram();
  GPU_blend(GPU_BLEND_NONE);
}

}  // namespace blender::ed::mixie
