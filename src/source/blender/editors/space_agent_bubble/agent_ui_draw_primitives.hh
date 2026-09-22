/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

/** Private inline painting primitives shared by the island and compact draft painters. */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLF_api.hh"
#include "BLI_rect.h"
#include "GPU_immediate.hh"
#include "GPU_state.hh"
#include "UI_interface_c.hh"
#include "UI_mixar.hh"
#include "ED_mixar_glass.hh"

namespace blender {

namespace {

/* -------------------------------------------------------------------- */
/** \name Shape helpers
 * \{ */

inline void fill_round(const rctf *rect, const float radius, const float col[4])
{
  ui::mixar_fill_round(*rect, radius, col);
}

inline void outline_round(const rctf *rect, const float radius, const float col[4])
{
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(rect, false, radius, col);
}

/**
 * One liquid-glass pane, in the caller's pixel space.
 *
 * `radius` is always explicit px: the panes here are capsules and cards whose
 * radius comes from the layout or the window, not from the role. The role
 * supplies the palette and the metrics.
 *
 * The drop shadow is OFF unless asked for, and the reason is the pill: its
 * window IS its capsule, so a shadow grown outward from the pane would be
 * clipped by the window at best and leave a hard edge where the clip falls at
 * worst — `tests/test_agent_bubble_pill_paint.py` pins that nothing the pill
 * paints may fall outside it. Only a pane with room around it inside its own
 * window passes `true`.
 *
 * Native frost passes tint=false: the common sheen and rim finish the pane
 * without stacking another coloured bed on top of AppKit or DWM see-through.
 */
inline void glass_fill_round(const rctf *rect,
                             const ui::eMixarGlassRole role,
                             const float radius,
                             const bool shadow = false,
                             const bool specular = false,
                             const bool tint = true,
                             const bool rim = true)
{
  rcti pane;
  BLI_rcti_rctf_copy(&pane, rect);
  ui::MixarGlassStyle style;
  style.role = role;
  style.radius = radius;
  style.draw_shadow = shadow;
  style.draw_specular = specular;
  style.draw_tint = tint;
  style.draw_rim = rim;
  ui::mixar_glass_draw(pane, style);
}

/**
 * Rounded rect filled with a two-stop ramp along an ARBITRARY axis.
 *
 * `ui::draw_roundbox_4fv_ex` can only shade vertically. The minimised pill's
 * logo chip ramps diagonally — its axis runs from the chip's top-right down and
 * to the left — and shading that vertically loses the horizontal falloff
 * entirely, which is most of the effect.
 *
 * So the fill is a triangle fan with per-vertex colour, sampled at
 * t = clamp(dot(p - a, b - a) / |b - a|^2, 0, 1). A raw fan is rasterised with
 * no coverage anti-aliasing, so its rim carries its own half-pixel feather
 * (see `aa` below) — the chip has nothing drawn over its edge, and without the
 * feather it drew visibly stair-stepped.
 */
inline void fill_round_gradient(const rctf *rect,
                                const float radius,
                                const float c0[4],
                                const float c1[4],
                                const float a[2],
                                const float b[2])
{
  const float abx = b[0] - a[0];
  const float aby = b[1] - a[1];
  const float len_sq = abx * abx + aby * aby;
  if (len_sq <= 0.0f) {
    fill_round(rect, radius, c0);
    return;
  }

  /* Corner arcs tessellated FROM the radius rather than at a fixed count: 8
   * segments is fine on a small chip and visibly polygonal on the minimised
   * pill's capsule and logo chip, where the radius runs to tens of pixels. */
  constexpr int ARC_MAX = 32;
  constexpr int RIM_MAX = (ARC_MAX + 1) * 4;

  const float x0 = rect->xmin;
  const float x1 = rect->xmax;
  const float y0 = rect->ymin;
  const float y1 = rect->ymax;
  const float r = std::min(radius, std::min((x1 - x0), (y1 - y0)) * 0.5f);
  const int arc = std::clamp(int(std::ceil(r)), 8, ARC_MAX);

  /* Half-pixel feather. The fan is rasterised without coverage AA, so its rim
   * steps against whatever is behind it — on the minimised pill that is the
   * opaque bed, and the capsule and its logo chip drew visibly stair-stepped
   * (the capsule's faint rim stroke is at alpha 0.14 and covers nothing, and
   * the idle chip carries no stroke at all). So the solid fan is pulled half a
   * pixel INSIDE the nominal edge and a ring of quads carries the colour from
   * there to half a pixel outside at zero alpha, putting the visual edge back
   * exactly where it was with a one-pixel ramp across it. */
  const float aa = (r > 0.5f) ? 0.5f : 0.0f;

  float rim[RIM_MAX][2];
  float nrm[RIM_MAX][2];
  int n = 0;
  /* Corner centres walked ANTICLOCKWISE from bottom-right, each sweeping the
   * quadrant that starts at `base`. Centre order and angle order have to agree
   * — pairing a bottom-left centre with a bottom-right quadrant folds the
   * polygon in on itself and the fill stops covering the card. */
  const float cx[4] = {x1 - r, x1 - r, x0 + r, x0 + r};
  const float cy[4] = {y0 + r, y1 - r, y1 - r, y0 + r};
  for (int corner = 0; corner < 4; corner++) {
    const float base = float(M_PI) * -0.5f + float(corner) * float(M_PI) * 0.5f;
    for (int i = 0; i <= arc; i++) {
      const float ang = base + (float(M_PI) * 0.5f) * (float(i) / float(arc));
      const float cs = std::cos(ang);
      const float sn = std::sin(ang);
      nrm[n][0] = cs;
      nrm[n][1] = sn;
      rim[n][0] = cx[corner] + cs * r;
      rim[n][1] = cy[corner] + sn * r;
      n++;
    }
  }

  auto sample = [&](const float px, const float py, float out[4]) {
    float t = ((px - a[0]) * abx + (py - a[1]) * aby) / len_sq;
    t = std::clamp(t, 0.0f, 1.0f);
    for (int i = 0; i < 4; i++) {
      out[i] = c0[i] + (c1[i] - c0[i]) * t;
    }
  };

  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  const uint col = GPU_vertformat_attr_add(
      format, "color", blender::gpu::VertAttrType::SFLOAT_32_32_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_SMOOTH_COLOR);

  /* The feather only reads as a ramp under alpha blending; callers that paint
   * an opaque bed first (the pill) would otherwise write the zero-alpha outer
   * ring straight into the framebuffer. */
  const GPUBlend blend_prev = GPU_blend_get();
  if (aa > 0.0f) {
    GPU_blend(GPU_BLEND_ALPHA);
  }

  immBegin(GPU_PRIM_TRI_FAN, n + 2);
  float c[4];
  const float mid_x = (x0 + x1) * 0.5f;
  const float mid_y = (y0 + y1) * 0.5f;
  sample(mid_x, mid_y, c);
  immAttr4fv(col, c);
  immVertex2f(pos, mid_x, mid_y);
  for (int i = 0; i < n; i++) {
    sample(rim[i][0], rim[i][1], c);
    immAttr4fv(col, c);
    immVertex2f(pos, rim[i][0] - nrm[i][0] * aa, rim[i][1] - nrm[i][1] * aa);
  }
  /* Close the fan back onto its first rim vertex. */
  sample(rim[0][0], rim[0][1], c);
  immAttr4fv(col, c);
  immVertex2f(pos, rim[0][0] - nrm[0][0] * aa, rim[0][1] - nrm[0][1] * aa);
  immEnd();

  if (aa > 0.0f) {
    immBegin(GPU_PRIM_TRI_STRIP, (n + 1) * 2);
    for (int i = 0; i <= n; i++) {
      const int k = (i == n) ? 0 : i;
      sample(rim[k][0], rim[k][1], c);
      immAttr4fv(col, c);
      immVertex2f(pos, rim[k][0] - nrm[k][0] * aa, rim[k][1] - nrm[k][1] * aa);
      const float fade[4] = {c[0], c[1], c[2], 0.0f};
      immAttr4fv(col, fade);
      immVertex2f(pos, rim[k][0] + nrm[k][0] * aa, rim[k][1] + nrm[k][1] * aa);
    }
    immEnd();
  }

  immUnbindProgram();

  if (aa > 0.0f) {
    GPU_blend(blend_prev);
  }
}

/**
 * The card's border, drawn as a credits meter.
 *
 * A full bright ring means a full allowance; as credits are spent the lit part
 * retreats and the spent part is drawn at a lower opacity, so the border reads as a
 * percentage strip running around the card rather than as decoration.
 *
 * The ring starts at the top-left corner and runs CLOCKWISE. That start point
 * is deliberate: it is the corner the eye already goes to, so the gap opens
 * where it is legible instead of behind the chip row.
 *
 * `remaining` outside [0,1] means "unknown" and draws the ring whole — an
 * empty-looking border on an account whose balance simply has not loaded yet
 * would read as a rendering bug, not as information.
 */
inline void draw_card_border_meter(const rctf *rect,
                                   const float radius,
                                   const float width,
                                   const float lit[4],
                                   const float spent[4],
                                   const float remaining)
{
  /* The BAND only. This used to fill the whole card rect in both branches and
   * rely on an opaque gradient painted afterwards to hide the interior; the
   * card's bed is a translucent pane now, so a whole-rect fill shows straight
   * through it and the card's middle reads as a flat wash. The ring form also
   * paints the corner arcs, which the four straight runs below never did. */
  const bool unknown = (remaining < 0.0f || remaining >= 1.0f);
  const float *band = unknown ? lit : spent;
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv_ex(rect, nullptr, nullptr, 1.0f, band, width, radius);

  if (unknown) {
    return;
  }

  /* Perimeter walked as four straight runs; the corner arcs are short enough at
   * this radius that folding them into the adjacent runs is imperceptible, and
   * it keeps the meter's arithmetic to one dimension. */
  const float w = BLI_rctf_size_x(rect);
  const float h = BLI_rctf_size_y(rect);
  const float total = (w + h) * 2.0f;
  const float lit_len = total * remaining;

  /* Each run is (start distance along the perimeter, length, rect builder). */
  struct Run {
    float len;
    int axis; /* 0 = along the top, 1 = down the right, 2 = along the bottom, 3 = up the left */
  };
  const Run runs[4] = {{w, 0}, {h, 1}, {w, 2}, {h, 3}};

  float walked = 0.0f;
  for (const Run &run : runs) {
    if (walked >= lit_len) {
      break;
    }
    const float take = std::min(run.len, lit_len - walked);
    const float t = take / run.len;
    rctf seg;
    switch (run.axis) {
      case 0: /* top, left -> right */
        seg.xmin = rect->xmin;
        seg.xmax = rect->xmin + w * t;
        seg.ymin = rect->ymax - width;
        seg.ymax = rect->ymax;
        break;
      case 1: /* right, top -> bottom */
        seg.xmin = rect->xmax - width;
        seg.xmax = rect->xmax;
        seg.ymin = rect->ymax - h * t;
        seg.ymax = rect->ymax;
        break;
      case 2: /* bottom, right -> left */
        seg.xmin = rect->xmax - w * t;
        seg.xmax = rect->xmax;
        seg.ymin = rect->ymin;
        seg.ymax = rect->ymin + width;
        break;
      default: /* left, bottom -> top */
        seg.xmin = rect->xmin;
        seg.xmax = rect->xmin + width;
        seg.ymin = rect->ymin;
        seg.ymax = rect->ymin + h * t;
        break;
    }
    fill_round(&seg, width * 0.5f, lit);
    walked += take;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Text helpers
 *
 * `chat_ui_draw_label` positions by baseline. The island positions almost
 * everything by optical centre instead, so these measure first. Measuring is
 * cheap next to the alternative: the account card learned the hard way that
 * BLF clips without an ellipsis, so a label that outgrows its slot vanishes
 * mid-word with no runtime signal at all.
 * \{ */

inline int island_font()
{
  return BLF_default();
}

inline float text_width(const char *text, const float size)
{
  const int font = island_font();
  BLF_size(font, size);
  return BLF_width(font, text, strlen(text));
}

/** Draw \a text with its left edge at \a x and its ink centred on \a cy. */
inline void label_left(
    const char *text, const float x, const float cy, const float size, const float col[4])
{
  if (!text || text[0] == '\0') {
    return;
  }
  const int font = island_font();
  BLF_size(font, size);
  /* Blender's widget text pass sets BLF_CLIPPING on the default font and does
   * not always leave it off. Any label drawn afterwards — the placeholder is
   * drawn after the uiBlocks on purpose — then gets clipped to that widget's
   * rect and vanishes silently, which is exactly how it presents: no error,
   * no glyphs. Clear it before every island label. */
  BLF_disable(font, BLF_CLIPPING);

  rcti box;
  BLF_boundbox(font, text, strlen(text), &box);
  const float baseline = cy - float(box.ymin + box.ymax) * 0.5f;

  BLF_color4fv(font, col);
  BLF_position(font, x, baseline, 0.0f);
  BLF_draw(font, text, strlen(text));
}

/** Draw \a text centred on (cx, cy). */
inline void label_centre(
    const char *text, const float cx, const float cy, const float size, const float col[4])
{
  if (!text || text[0] == '\0') {
    return;
  }
  label_left(text, cx - text_width(text, size) * 0.5f, cy, size, col);
}

/** Draw \a text with its right edge at \a x. */
inline void label_right(
    const char *text, const float x, const float cy, const float size, const float col[4])
{
  if (!text || text[0] == '\0') {
    return;
  }
  label_left(text, x - text_width(text, size), cy, size, col);
}

/** \} */

}  // namespace

}  // namespace blender
