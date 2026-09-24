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

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

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
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&rect, true, rad, col);
}

void box_outline(const float xmin,
                 const float xmax,
                 const float ymin,
                 const float ymax,
                 const float rad,
                 const float col[4])
{
  const rctf rect = {xmin, xmax, ymin, ymax};
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&rect, false, rad, col);
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
 * three edges meeting at the centre — the same punch idiom as the other
 * silhouettes, so the seams where those edges meet the rim are erased rather
 * than outlined. */
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

/** Band of constant width along a circular arc, as a triangle strip. */
void arc_band(const float cx,
              const float cy,
              const float r,
              const float w,
              const float a0,
              const float a1,
              const float col[4])
{
  const int steps = 24;
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(col);

  immBegin(GPU_PRIM_TRI_STRIP, (steps + 1) * 2);
  for (int i = 0; i <= steps; i++) {
    const float t = a0 + (a1 - a0) * (float(i) / float(steps));
    const float c = std::cos(t);
    const float sn = std::sin(t);
    immVertex2f(pos, cx + c * (r - w * 0.5f), cy + sn * (r - w * 0.5f));
    immVertex2f(pos, cx + c * (r + w * 0.5f), cy + sn * (r + w * 0.5f));
  }
  immEnd();

  immUnbindProgram();
}

/** Counter-clockwise arrow on an open ring — the turn-checkpoints button
 *  ("go back to an earlier turn"). Same monoline weight as the clock. */
void glyph_restore(const float cx, const float cy, const float s, const float col[4])
{
  const float w = std::max(1.0f, s * 0.10f);
  const float r = s * 0.40f;
  /* Follow the arc counter-clockwise to its upper-right end. */
  const float a_start = float(M_PI) * 0.72f;
  const float a_end = a_start + float(M_PI) * 1.55f;
  arc_band(cx, cy, r, w, a_start, a_end, col);

  /* A left-pointing arrow at the end reads as undo/restore. The old head
   * sat at the start with the opposite tangent and read as redo. */
  const float tx = cx + std::cos(a_end) * r;
  const float ty = cy + std::sin(a_end) * r;
  const float dx = -std::sin(a_end);
  const float dy = std::cos(a_end);
  const float nx = -dy;
  const float ny = dx;
  const float len = s * 0.26f;
  const float half = s * 0.17f;
  const float pts[3][2] = {
      {tx + dx * len, ty + dy * len},
      {tx - nx * half, ty - ny * half},
      {tx + nx * half, ty + ny * half},
  };
  poly(pts, 3, col);
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

/** A stylus at 45°: body quad, nib triangle, a dot for the cap. Convex
 *  pieces only, so each is one `poly` — a rotated rounded box would need
 *  its own fan and the punch idiom has nothing to punch here. */
void glyph_pen(const float cx, const float cy, const float s, const float col[4])
{
  const float d = 0.70710678f; /* unit diagonal, tail bottom-left -> nib top-right */
  const float hw = s * 0.11f;   /* half the body width */
  const float tail = s * 0.38f;
  const float nib_base = s * 0.14f;
  const float tip = s * 0.44f;

  /* Along the axis: t < 0 is toward the tail. Across: n = (-d, d). */
  auto at = [&](const float t, const float across, float out[2]) {
    out[0] = cx + d * t - d * across;
    out[1] = cy + d * t + d * across;
  };
  float body[4][2];
  at(-tail, -hw, body[0]);
  at(nib_base, -hw, body[1]);
  at(nib_base, hw, body[2]);
  at(-tail, hw, body[3]);
  poly(body, 4, col);

  float nib[3][2];
  at(nib_base, -hw, nib[0]);
  at(tip, 0.0f, nib[1]);
  at(nib_base, hw, nib[2]);
  poly(nib, 3, col);

  float cap[2];
  at(-tail, 0.0f, cap);
  disc(cap[0], cap[1], hw, col);
}

/** Two bars at 45° — the plus glyph turned, as a pair of convex quads. */
void glyph_cross(const float cx, const float cy, const float s, const float col[4])
{
  const float w = std::max(1.5f, s * 0.14f) * 0.5f;
  const float arm = s * 0.30f;
  const float d = 0.70710678f;
  for (int bar = 0; bar < 2; bar++) {
    /* Axis of this bar and its perpendicular, both unit length. */
    const float ax = d;
    const float ay = (bar == 0) ? d : -d;
    const float nx = -ay;
    const float ny = ax;
    const float pts[4][2] = {
        {cx - ax * arm - nx * w, cy - ay * arm - ny * w},
        {cx + ax * arm - nx * w, cy + ay * arm - ny * w},
        {cx + ax * arm + nx * w, cy + ay * arm + ny * w},
        {cx - ax * arm + nx * w, cy - ay * arm + ny * w},
    };
    poly(pts, 4, col);
  }
}

/** Microphone: a capsule over a U-shaped cradle, on a stem and base. The
 * cradle is a run of thin quads along a half circle — `poly` is the one
 * primitive every glyph here already uses. */
void glyph_mic(const float cx, const float cy, const float s, const float col[4])
{
  const float w = stroke_width(s);
  const float cap_w = s * 0.32f;
  const float cap_top = cy + s * 0.46f;
  const float cap_bottom = cy - s * 0.04f;
  box_fill(cx - cap_w * 0.5f, cx + cap_w * 0.5f, cap_bottom, cap_top, cap_w * 0.5f, col);

  const float r = s * 0.30f;
  const float ccy = cap_bottom + s * 0.12f;
  const int segments = 10;
  for (int i = 0; i < segments; i++) {
    const float a0 = float(M_PI) + float(M_PI) * float(i) / float(segments);
    const float a1 = float(M_PI) + float(M_PI) * float(i + 1) / float(segments);
    const float ax = cosf(a0), ay = sinf(a0), bx = cosf(a1), by = sinf(a1);
    const float half = w * 0.5f;
    const float pts[4][2] = {
        {cx + ax * (r - half), ccy + ay * (r - half)},
        {cx + bx * (r - half), ccy + by * (r - half)},
        {cx + bx * (r + half), ccy + by * (r + half)},
        {cx + ax * (r + half), ccy + ay * (r + half)},
    };
    poly(pts, 4, col);
  }
  const float stem_top = ccy - r;
  const float stem_bottom = stem_top - s * 0.14f;
  vrule(stem_bottom, stem_top, cx, w, col);
  rule(cx - s * 0.20f, cx + s * 0.20f, stem_bottom, w, col);
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
    case AGENT_ICON_VIDEO:
    case AGENT_ICON_RULES:
    case AGENT_ICON_SIGNATURE:
      agent_ui_tab_icon_draw(icon, cx, cy, s, color);
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
    case AGENT_ICON_RESTORE:
      /* Keep the ring and arrowhead comfortably inside the accent disc. */
      glyph_restore(cx, cy, s * 0.78f, color);
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
    case AGENT_ICON_PEN:
      glyph_pen(cx, cy, s, color);
      break;
    case AGENT_ICON_CROSS:
      glyph_cross(cx, cy, s, color);
      break;
    case AGENT_ICON_MIC:
      glyph_mic(cx, cy, s, color);
      break;
    case AGENT_ICON_COUNT:
      break;
  }
}

}  // namespace blender
