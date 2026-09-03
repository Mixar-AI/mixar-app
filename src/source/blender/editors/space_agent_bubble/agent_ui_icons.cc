/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Glyphs for the Agent island — see the header for why these are hand-drawn.
 */

#include <algorithm>
#include <cmath>

#include "BLI_rect.h"
#include "BLI_utildefines.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_interface_c.hh"

#include "agent_ui_icons.hh"

namespace {

/** Monoline weight as a fraction of the glyph box, floored at one pixel. */
float stroke_width(const float size)
{
  return std::max(1.0f, size * 0.083f);
}

void box_fill(const float xmin,
              const float xmax,
              const float ymin,
              const float ymax,
              const float rad,
              const float col[4])
{
  const rctf rect = {xmin, xmax, ymin, ymax};
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv(&rect, true, rad, col);
}

void box_outline(const float xmin,
                 const float xmax,
                 const float ymin,
                 const float ymax,
                 const float rad,
                 const float col[4])
{
  const rctf rect = {xmin, xmax, ymin, ymax};
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv(&rect, false, rad, col);
}

void rule(const float x0, const float x1, const float cy, const float w, const float col[4])
{
  box_fill(x0, x1, cy - w * 0.5f, cy + w * 0.5f, w * 0.5f, col);
}

void vrule(const float y0, const float y1, const float cx, const float w, const float col[4])
{
  box_fill(cx - w * 0.5f, cx + w * 0.5f, y0, y1, w * 0.5f, col);
}

void disc(const float cx, const float cy, const float r, const float col[4])
{
  box_fill(cx - r, cx + r, cy - r, cy + r, r, col);
}

void ring(const float cx, const float cy, const float r, const float col[4])
{
  box_outline(cx - r, cx + r, cy - r, cy + r, r, col);
}

/** Filled convex polygon. For the star and the chevron, which no rounded box
 *  can express. Anti-aliasing comes from the polygon smoothing Blender's
 *  interface pass already has enabled. */
void poly(const float (*pts)[2], const int count, const float col[4])
{
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(col);

  immBegin(GPU_PRIM_TRI_FAN, count);
  for (int i = 0; i < count; i++) {
    immVertex2f(pos, pts[i][0], pts[i][1]);
  }
  immEnd();

  immUnbindProgram();
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

/* -------------------------------------------------------------------- */
/* Glyphs. `s` is the glyph box edge; (cx, cy) its centre.               */

/** Person in a ring — the Agent tab's mark. */
void glyph_agent(const float cx, const float cy, const float s, const float col[4])
{
  const float r = s * 0.46f;

  ring(cx, cy, r, col);
  /* Head, then shoulders as a wide capsule clipped by the ring's lower half.
   * Drawing the shoulders as a plain capsule rather than an arc is what the
   * artboard does at this size — an arc's ends read as noise below 16 px. */
  disc(cx, cy + s * 0.12f, s * 0.13f, col);
  box_fill(cx - s * 0.24f,
           cx + s * 0.24f,
           cy - s * 0.30f,
           cy - s * 0.04f,
           s * 0.13f,
           col);
}

/** Nine-dot rosette — the Gaussian Splat tab's mark.
 *
 * `generations.svg` draws it as nine r=2.46 discs in a 24-unit box: one at
 * the centre and eight on a radius-9 circle at 45-degree steps. Discs, not a
 * stippled texture — the splat mark has to stay legible at 16 px. */
void glyph_splat(const float cx, const float cy, const float s, const float col[4])
{
  const float ring_r = s * 0.375f;
  const float dot_r = std::max(0.75f, s * 0.1025f);

  disc(cx, cy, dot_r, col);
  for (int i = 0; i < 8; i++) {
    const float a = float(i) * float(M_PI) / 4.0f;
    disc(cx + std::cos(a) * ring_r, cy + std::sin(a) * ring_r, dot_r, col);
  }
}

/** Down arrow beside an up arrow — the generations sort chip.
 *
 * The design draws two 2-unit shafts 16 units apart, each 16 tall, with a
 * chevron head at opposite ends. Both are built from the same primitives as
 * the chevron glyph so the weights match the rest of the set. */
void glyph_sort(const float cx, const float cy, const float s, const float col[4])
{
  const float half_h = s * 0.36f;
  const float dx = s * 0.22f;
  const float w = std::max(1.0f, s * 0.09f);
  const float head = s * 0.16f;

  auto arrow = [&](const float x, const bool down) {
    const float tip = down ? (cy - half_h) : (cy + half_h);
    vrule(cy - half_h, cy + half_h, x, w, col);
    const float base = down ? (tip + head) : (tip - head);
    const float pts[3][2] = {{x - head, base}, {x + head, base}, {x, tip}};
    poly(pts, 3, col);
  };
  arrow(cx - dx, true);
  arrow(cx + dx, false);
}

/** Isometric cube — a 3D asset whose preview has not loaded (or does not
 * exist). Drawn as a hexagon silhouette punched by an inset hexagon, plus the
 * three edges meeting at the centre — the same punch idiom as the thumbs-up,
 * so the seams where those edges meet the rim are erased rather than
 * outlined. */
void glyph_mesh(const float cx,
                const float cy,
                const float s,
                const float col[4],
                const float bg[4])
{
  const float w = stroke_width(s);

  auto hexagon = [&](const float r, const float c[4]) {
    float pts[8][2];
    pts[0][0] = cx;
    pts[0][1] = cy;
    for (int i = 0; i <= 6; i++) {
      const float a = float(M_PI) * 0.5f + float(i % 6) * float(M_PI) / 3.0f;
      pts[i + 1][0] = cx + std::cos(a) * r;
      pts[i + 1][1] = cy + std::sin(a) * r;
    }
    poly(pts, 8, c);
  };
  hexagon(s * 0.46f, col);
  hexagon(s * 0.46f - w, bg);

  /* The three visible cube edges: up, down-left, down-right. */
  const float r = s * 0.46f - w * 0.5f;
  vrule(cy, cy + r, cx, w, col);
  for (const float a : {float(M_PI) * 7.0f / 6.0f, float(M_PI) * 11.0f / 6.0f}) {
    const float ex = cx + std::cos(a) * r;
    const float ey = cy + std::sin(a) * r;
    /* A rotated capsule is overkill at this size; a short box between the
     * centre and the vertex reads as an edge. */
    const int steps = 6;
    for (int i = 0; i <= steps; i++) {
      const float t = float(i) / float(steps);
      disc(cx + (ex - cx) * t, cy + (ey - cy) * t, w * 0.5f, col);
    }
  }
}

/** Thumbs-up — My Generations.
 *
 * Traced from `generations.svg`'s own outline (Lucide's thumbs-up at
 * stroke-width 2 in a 17-unit box) and flattened to a polyline, rather than
 * approximated from rounded boxes: the approximation collapsed into a blob at
 * 16 px and was indistinguishable from the placeholder mark the tab strip
 * used to stamp on every tab. Points are fractions of the glyph box, y up. */
void glyph_thumb(const float cx, const float cy, const float s, const float col[4])
{
  static const float outline[57][2] = {
      {+0.3068f, -0.4831f}, {-0.3792f, -0.4831f}, {-0.4035f, -0.4807f},
      {-0.4261f, -0.4736f}, {-0.4466f, -0.4625f}, {-0.4645f, -0.4477f},
      {-0.4793f, -0.4299f}, {-0.4905f, -0.4094f}, {-0.4975f, -0.3867f},
      {-0.5000f, -0.3623f}, {-0.5000f, +0.1208f}, {-0.2627f, +0.1208f},
      {-0.2477f, +0.1217f}, {-0.2331f, +0.1245f}, {-0.2191f, +0.1289f},
      {-0.2058f, +0.1351f}, {-0.1933f, +0.1428f}, {-0.1818f, +0.1520f},
      {-0.1715f, +0.1626f}, {-0.1624f, +0.1746f}, {-0.0102f, +0.4024f},
      {+0.0035f, +0.4204f}, {+0.0190f, +0.4363f}, {+0.0363f, +0.4501f},
      {+0.0551f, +0.4617f}, {+0.0751f, +0.4709f}, {+0.0962f, +0.4776f},
      {+0.1181f, +0.4817f}, {+0.1407f, +0.4831f}, {+0.1534f, +0.4831f},
      {+0.1670f, +0.4816f}, {+0.1794f, +0.4773f}, {+0.1904f, +0.4706f},
      {+0.1996f, +0.4618f}, {+0.2068f, +0.4512f}, {+0.2117f, +0.4393f},
      {+0.2139f, +0.4264f}, {+0.2132f, +0.4128f}, {+0.1643f, +0.1208f},
      {+0.3793f, +0.1208f}, {+0.4068f, +0.1176f}, {+0.4320f, +0.1087f},
      {+0.4541f, +0.0948f}, {+0.4726f, +0.0766f}, {+0.4869f, +0.0549f},
      {+0.4962f, +0.0304f}, {+0.5000f, +0.0040f}, {+0.4976f, -0.0237f},
      {+0.4252f, -0.3860f}, {+0.4191f, -0.4064f}, {+0.4099f, -0.4250f},
      {+0.3978f, -0.4415f}, {+0.3832f, -0.4557f}, {+0.3664f, -0.4673f},
      {+0.3479f, -0.4759f}, {+0.3279f, -0.4813f}, {+0.3068f, -0.4831f},
  };
  /* The cuff divider, a separate stroke in the artboard. */
  static const float cuff[2][2] = {{-0.2584f, +0.1208f}, {-0.2584f, -0.4831f}};

  const float w = std::max(1.0f, s * 0.11f);
  stroke_path(outline, 57, cx, cy, s, w, true, col);
  stroke_path(cuff, 2, cx, cy, s, w, false, col);
}

/** Clock face — the history button. Drawn as a filled disc with cut hands
 *  because the artboard's button is a light disc on green, not an outline. */
void glyph_clock(const float cx, const float cy, const float s, const float col[4])
{
  const float w = std::max(1.0f, s * 0.10f);
  const float r = s * 0.44f;

  ring(cx, cy, r, col);
  vrule(cy, cy + r * 0.58f, cx, w, col);
  rule(cx, cx + r * 0.44f, cy, w, col);
}

void glyph_plus(const float cx, const float cy, const float s, const float col[4])
{
  const float w = std::max(1.5f, s * 0.16f);
  const float arm = s * 0.32f;

  rule(cx - arm, cx + arm, cy, w, col);
  vrule(cy - arm, cy + arm, cx, w, col);
}

/** Framed picture with a horizon and a sun — the Upload Reference chip. */
void glyph_image(const float cx, const float cy, const float s, const float col[4])
{
  const float half = s * 0.40f;

  box_outline(cx - half, cx + half, cy - half, cy + half, s * 0.12f, col);
  disc(cx - half * 0.42f, cy + half * 0.38f, s * 0.075f, col);

  /* The "mountain": a low capsule reads as a ridge at 16 px where a real
   * chevron collapses into a smudge. */
  box_fill(cx - half * 0.72f,
           cx + half * 0.86f,
           cy - half * 0.62f,
           cy - half * 0.16f,
           s * 0.09f,
           col);
}

void glyph_star(const float cx, const float cy, const float s, const float col[4])
{
  const float outer = s * 0.46f;
  const float inner = outer * 0.42f;

  /* Centre, ten alternating rim points, then the first rim point again — a
   * TRI_FAN leaves the last wedge open unless the ring is explicitly closed. */
  float pts[12][2];
  pts[0][0] = cx;
  pts[0][1] = cy;
  for (int i = 0; i <= 10; i++) {
    const float r = (i % 2 == 0) ? outer : inner;
    /* Start at 12 o'clock and walk clockwise. */
    const float a = float(M_PI) * 0.5f - float(i % 10) * float(M_PI) / 5.0f;
    pts[i + 1][0] = cx + std::cos(a) * r;
    pts[i + 1][1] = cy + std::sin(a) * r;
  }
  poly(pts, 12, col);
}

void glyph_chevron_down(const float cx, const float cy, const float s, const float col[4])
{
  const float half = s * 0.30f;
  const float depth = s * 0.20f;

  const float pts[3][2] = {
      {cx - half, cy + depth},
      {cx + half, cy + depth},
      {cx, cy - depth},
  };
  poly(pts, 3, col);
}

}  // namespace

void agent_ui_icon_draw(const AgentIcon icon,
                        const rctf *box,
                        const float color[4],
                        const float backdrop[4])
{
  const float cx = BLI_rctf_cent_x(box);
  const float cy = BLI_rctf_cent_y(box);
  const float s = std::min(BLI_rctf_size_x(box), BLI_rctf_size_y(box));

  if (s <= 0.0f) {
    return;
  }

  switch (icon) {
    case AGENT_ICON_AGENT:
      glyph_agent(cx, cy, s, color);
      break;
    case AGENT_ICON_THUMB:
      glyph_thumb(cx, cy, s, color);
      break;
    case AGENT_ICON_SPLAT:
      glyph_splat(cx, cy, s, color);
      break;
    case AGENT_ICON_SORT:
      glyph_sort(cx, cy, s, color);
      break;
    case AGENT_ICON_MESH:
      glyph_mesh(cx, cy, s, color, backdrop);
      break;
    case AGENT_ICON_CLOCK:
      glyph_clock(cx, cy, s, color);
      break;
    case AGENT_ICON_PLUS:
      glyph_plus(cx, cy, s, color);
      break;
    case AGENT_ICON_IMAGE:
      glyph_image(cx, cy, s, color);
      break;
    case AGENT_ICON_STAR:
      glyph_star(cx, cy, s, color);
      break;
    case AGENT_ICON_CHEVRON_DOWN:
      glyph_chevron_down(cx, cy, s, color);
      break;
    case AGENT_ICON_COUNT:
      break;
  }
}
