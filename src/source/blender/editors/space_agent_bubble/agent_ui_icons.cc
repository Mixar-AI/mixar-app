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

/** Thumbs-up.
 *
 * The artboard uses this same mark on 3D, Media, Gaussian Splat and My
 * Generations — it is plainly a placeholder the designer never replaced, but
 * the brief is an as-is replica, so it is reproduced rather than invented
 * around. Give each tab its own mark only when the design does. */
void glyph_thumb(const float cx,
                 const float cy,
                 const float s,
                 const float col[4],
                 const float bg[4])
{
  const float w = stroke_width(s);

  /* One pass at inset 0 in the ink colour, one at inset `w` in the backdrop.
   * The fist and the thumb overlap in BOTH passes, so the inner pass erases
   * the seam between them instead of outlining it. The cuff is a separate
   * shape in the artboard and stays separate here. */
  auto pass = [&](const float inset, const float c[4]) {
    /* Cuff. */
    box_fill(cx - s * 0.45f + inset,
             cx - s * 0.22f - inset,
             cy - s * 0.34f + inset,
             cy + s * 0.10f - inset,
             s * 0.05f,
             c);
    /* Fist. */
    box_fill(cx - s * 0.13f + inset,
             cx + s * 0.45f - inset,
             cy - s * 0.34f + inset,
             cy + s * 0.16f - inset,
             s * 0.12f,
             c);
    /* Thumb — reaches down into the fist so the two stay merged after inset. */
    box_fill(cx - s * 0.13f + inset,
             cx + s * 0.14f - inset,
             cy - s * 0.04f + inset,
             cy + s * 0.46f - inset,
             s * 0.09f,
             c);
  };
  pass(0.0f, col);
  pass(w, bg);
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
      glyph_thumb(cx, cy, s, color, backdrop);
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
