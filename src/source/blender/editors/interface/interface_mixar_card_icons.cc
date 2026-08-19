/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup edinterface
 *
 * Thin-stroke glyphs for the Mixar account card — see the header for why
 * these exist instead of `ICON_*`.
 *
 * Every glyph is composed from two primitives: an anti-aliased rounded
 * box (which doubles as a circle at `rad = size / 2`, and as a stroke at
 * small heights) and an anti-aliased line for diagonals. All geometry is
 * expressed as fractions of the glyph box so a single definition holds
 * at any DPI.
 */

#include <algorithm>
#include <cmath>

#include "BLI_math_color.h"
#include "BLI_rect.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_interface_c.hh"

#include "interface_mixar_card_icons.hh"

namespace {

/** Stroke weight as a fraction of the glyph box, floored at one pixel. */
float stroke_width(const float size)
{
  return std::max(1.0f, size * 0.085f);
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

/** Horizontal stroke centred on \a cy, drawn as a capsule. */
void rule(const float x0, const float x1, const float cy, const float w, const float col[4])
{
  box_fill(x0, x1, cy - w * 0.5f, cy + w * 0.5f, w * 0.5f, col);
}

/** Vertical stroke centred on \a cx, drawn as a capsule. */
void vrule(const float y0, const float y1, const float cx, const float w, const float col[4])
{
  box_fill(cx - w * 0.5f, cx + w * 0.5f, y0, y1, w * 0.5f, col);
}

void disc(const float cx, const float cy, const float r, const float col[4])
{
  box_fill(cx - r, cx + r, cy - r, cy + r, r, col);
}

/**
 * Anti-aliased line, for the diagonals a rounded box cannot express.
 *
 * Uses `GPU_PRIM_LINES` with smoothing rather than a rotated quad: a
 * quad has no coverage anti-aliasing, and a 45-degree stroke at 16px is
 * exactly where that shows.
 */
void diagonal(const float x0,
              const float y0,
              const float x1,
              const float y1,
              const float w,
              const float col[4])
{
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(col);

  GPU_line_smooth(true);
  GPU_line_width(w);
  immBegin(GPU_PRIM_LINES, 2);
  immVertex2f(pos, x0, y0);
  immVertex2f(pos, x1, y1);
  immEnd();
  GPU_line_width(1.0f);
  GPU_line_smooth(false);

  immUnbindProgram();
}

/* -------------------------------------------------------------------- */
/* Glyphs                                                                */

/** 2x2 tiles. Reads as "dashboard" faster than any gauge or globe. */
void glyph_grid(const float cx, const float cy, const float s, const float col[4])
{
  const float cell = s * 0.42f;
  const float gap = s * 0.16f;
  const float off = (cell + gap) * 0.5f;
  const float rad = s * 0.09f;

  for (int iy = 0; iy < 2; iy++) {
    for (int ix = 0; ix < 2; ix++) {
      const float ox = cx + (ix == 0 ? -off : off);
      const float oy = cy + (iy == 0 ? -off : off);
      box_fill(ox - cell * 0.5f, ox + cell * 0.5f, oy - cell * 0.5f, oy + cell * 0.5f, rad, col);
    }
  }
}

/** Two tracks with knobs at opposite ends — the settings idiom. */
void glyph_sliders(const float cx, const float cy, const float s, const float col[4])
{
  const float w = stroke_width(s);
  const float half = s * 0.46f;
  const float knob = s * 0.155f;
  const float y_top = cy + s * 0.21f;
  const float y_bot = cy - s * 0.21f;

  rule(cx - half, cx + half, y_top, w, col);
  disc(cx + s * 0.17f, y_top, knob, col);

  rule(cx - half, cx + half, y_bot, w, col);
  disc(cx - s * 0.17f, y_bot, knob, col);
}

/** Page outline with two text rules. */
void glyph_document(const float cx, const float cy, const float s, const float col[4])
{
  const float w = stroke_width(s);
  const float hw = s * 0.34f;
  const float hh = s * 0.45f;

  box_outline(cx - hw, cx + hw, cy - hh, cy + hh, s * 0.11f, col);

  const float inset = s * 0.17f;
  rule(cx - hw + inset, cx + hw - inset, cy + s * 0.13f, w, col);
  rule(cx - hw + inset, cx + hw - inset * 2.0f, cy - s * 0.09f, w, col);
}

/** Ringed exclamation. Softer than a filled warning triangle, which
 * reads as a blocking error rather than a "tell us about it" action. */
void glyph_alert(const float cx, const float cy, const float s, const float col[4])
{
  const float r = s * 0.46f;
  const float w = stroke_width(s);

  box_outline(cx - r, cx + r, cy - r, cy + r, r, col);
  vrule(cy - s * 0.02f, cy + s * 0.23f, cx, w, col);
  disc(cx, cy - s * 0.17f, w * 0.62f, col);
}

/** Diagonal cross. */
void glyph_cross(const float cx, const float cy, const float s, const float col[4])
{
  const float h = s * 0.32f;
  const float w = stroke_width(s) * 1.15f;

  diagonal(cx - h, cy - h, cx + h, cy + h, w, col);
  diagonal(cx - h, cy + h, cx + h, cy - h, w, col);
}

}  // namespace

void UI_mixar_card_icon_draw(
    const MixarCardIcon icon, const float cx, const float cy, const float size, const uchar col[4])
{
  if (icon == MixarCardIcon::None || size <= 0.0f) {
    return;
  }

  float c[4];
  rgba_uchar_to_float(c, col);

  switch (icon) {
    case MixarCardIcon::Grid:
      glyph_grid(cx, cy, size, c);
      break;
    case MixarCardIcon::Sliders:
      glyph_sliders(cx, cy, size, c);
      break;
    case MixarCardIcon::Document:
      glyph_document(cx, cy, size, c);
      break;
    case MixarCardIcon::Alert:
      glyph_alert(cx, cy, size, c);
      break;
    case MixarCardIcon::Cross:
      glyph_cross(cx, cy, size, c);
      break;
    case MixarCardIcon::None:
      break;
  }
}
