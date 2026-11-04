/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * The "agent working" halo: a breathing green inner glow around the 3D
 * viewport while the agent executes (Python owner:
 * `agent_viewport_lock`, which also runs the input-block modal).
 *
 * It is painted from the WINDOW region's `draw_overlay` pass, which the
 * window composite runs over the region's cached buffer, and advanced with
 * #WM_paint_cursor_tag_redraw (a window repaint). Neither re-renders the viewport: the former
 * Python POST_PIXEL handler needed a full region redraw per frame, so the
 * breathing animation re-rendered a production scene through EEVEE ~18 times
 * a second for the whole turn (measured 8.5% of the main thread plus the GPU
 * time on a 1.2M-polygon file).
 *
 * The Python side mirrors its state into two WindowManager ID properties
 * (#HALO_ACTIVE_WM_PROP, #HALO_INSET_WM_PROP) and calls
 * `mixar.agent_halo_redraw` on its tick. Keep the look in sync with
 * `agent_viewport_lock/constants.py` and `core/halo_renderer.py`, which
 * remains the fallback painter for a binary without this file.
 */

#include <algorithm>
#include <cmath>

#include "BKE_context.hh"
#include "BKE_idprop.hh"
#include "BKE_screen.hh"

#include "BLI_listbase.h"
#include "BLI_listbase_iterator.hh"
#include "BLI_math_base.h"
#include "BLI_time.h"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"

#include "GPU_immediate.hh"
#include "GPU_state.hh"

#include "UI_interface_c.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_intern.hh"

namespace blender {

/* Written by agent_viewport_lock/core/halo_renderer.py (names must match). */
static const char *HALO_ACTIVE_WM_PROP = "mixar_agent_halo_active";
static const char *HALO_INSET_WM_PROP = "mixar_agent_halo_inset";

/* Mirrors agent_viewport_lock/constants.py. */
static const float HALO_COLOR[3] = {0.290f, 0.870f, 0.502f};
static const float HALO_BAND_PX = 130.0f;
static const float HALO_ALPHA_MIN = 0.07f;
static const float HALO_ALPHA_MAX = 0.18f;
static const double HALO_PERIOD_S = 2.6;
static const float HALO_FALLOFF_EXP = 2.8f;
static const int HALO_STEPS = 8;

static int halo_wm_int(const wmWindowManager *wm, const char *name)
{
  if (!wm || !wm->id.properties) {
    return 0;
  }
  const IDProperty *prop = IDP_GetPropertyFromGroup(wm->id.properties, name);
  if (!prop) {
    return 0;
  }
  if (ELEM(prop->type, IDP_INT, IDP_BOOLEAN)) {
    return IDP_int_or_bool_get(prop);
  }
  return 0;
}

static float halo_breathing_alpha()
{
  const double phase = std::fmod(BLI_time_now_seconds(), HALO_PERIOD_S) / HALO_PERIOD_S;
  const float s = 0.5f - 0.5f * float(std::cos(2.0 * M_PI * phase)); /* 0..1, eased */
  return HALO_ALPHA_MIN + (HALO_ALPHA_MAX - HALO_ALPHA_MIN) * s;
}

/* One edge: `HALO_STEPS` quads from the edge (peak alpha) inward (zero). */
static void halo_band(const uint pos,
                      const uint col,
                      const float origin[2],
                      const float along[2],
                      const float inward[2],
                      const float band,
                      const float alpha)
{
  for (int i = 0; i < HALO_STEPS; i++) {
    const float t0 = float(i) / HALO_STEPS;
    const float t1 = float(i + 1) / HALO_STEPS;
    const float d0 = band * t0;
    const float d1 = band * t1;
    const float a0 = alpha * std::pow(1.0f - t0, HALO_FALLOFF_EXP);
    const float a1 = alpha * std::pow(1.0f - t1, HALO_FALLOFF_EXP);
    const float c0[4] = {HALO_COLOR[0], HALO_COLOR[1], HALO_COLOR[2], a0};
    const float c1[4] = {HALO_COLOR[0], HALO_COLOR[1], HALO_COLOR[2], a1};
    const float e0[2] = {origin[0] + inward[0] * d0, origin[1] + inward[1] * d0};
    const float e1[2] = {origin[0] + along[0] + inward[0] * d0,
                         origin[1] + along[1] + inward[1] * d0};
    const float i1[2] = {origin[0] + along[0] + inward[0] * d1,
                         origin[1] + along[1] + inward[1] * d1};
    const float i0[2] = {origin[0] + inward[0] * d1, origin[1] + inward[1] * d1};
    /* Two triangles per quad. */
    immAttr4fv(col, c0);
    immVertex2fv(pos, e0);
    immAttr4fv(col, c0);
    immVertex2fv(pos, e1);
    immAttr4fv(col, c1);
    immVertex2fv(pos, i1);
    immAttr4fv(col, c0);
    immVertex2fv(pos, e0);
    immAttr4fv(col, c1);
    immVertex2fv(pos, i1);
    immAttr4fv(col, c1);
    immVertex2fv(pos, i0);
  }
}

void view3d_agent_halo_overlay_draw(const bContext *C, ARegion *region)
{
  const wmWindowManager *wm = CTX_wm_manager(C);
  if (region == nullptr || !halo_wm_int(wm, HALO_ACTIVE_WM_PROP)) {
    return;
  }
  const float w = float(region->winx);
  /* Height hidden by an opaque header bed (Zen's scene toolbar): the glow
   * stops below it, same rule as halo_renderer._opaque_header_inset. */
  const float h = float(std::max(0, region->winy - halo_wm_int(wm, HALO_INSET_WM_PROP)));
  const float band = std::min({HALO_BAND_PX * UI_SCALE_FAC, w * 0.5f, h * 0.5f});
  if (band <= 1.0f) {
    return;
  }
  const float alpha = halo_breathing_alpha();

  ED_region_pixelspace(region);
  const GPUBlend blend_prev = GPU_blend_get();
  GPU_blend(GPU_BLEND_ALPHA);

  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  const uint col = GPU_vertformat_attr_add(
      format, "color", gpu::VertAttrType::SFLOAT_32_32_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_SMOOTH_COLOR);
  immBegin(GPU_PRIM_TRIS, 4 * HALO_STEPS * 6);
  const float o_left[2] = {0.0f, 0.0f}, o_right[2] = {w, 0.0f}, o_top[2] = {0.0f, h};
  const float up[2] = {0.0f, h}, across[2] = {w, 0.0f};
  const float in_r[2] = {1.0f, 0.0f}, in_l[2] = {-1.0f, 0.0f}, in_u[2] = {0.0f, 1.0f},
              in_d[2] = {0.0f, -1.0f};
  halo_band(pos, col, o_left, up, in_r, band, alpha);   /* left */
  halo_band(pos, col, o_right, up, in_l, band, alpha);  /* right */
  halo_band(pos, col, o_left, across, in_u, band, alpha); /* bottom */
  halo_band(pos, col, o_top, across, in_d, band, alpha);  /* top */
  immEnd();
  immUnbindProgram();

  GPU_blend(blend_prev);
}

/* -------------------------------------------------------------------- */
/** \name Redraw operator (the Python tick's frame request)
 * \{ */

static wmOperatorStatus agent_halo_redraw_exec(bContext *C, wmOperator * /*op*/)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return OPERATOR_CANCELLED;
  }
  for (wmWindow &win : wm->windows) {
    bScreen *screen = WM_window_get_active_screen(&win);
    if (screen == nullptr) {
      continue;
    }
    for (ScrArea &area : screen->areabase) {
      if (area.spacetype != SPACE_VIEW3D) {
        continue;
      }
      if (ARegion *region = BKE_area_find_region_type(&area, RGN_TYPE_WINDOW)) {
        /* Tag the window, not only the region: the window-redraw test reads
         * the region-level cursor flag only for the screen's own regions, so
         * a viewport tagged with #ED_region_tag_redraw_cursor alone never
         * repainted and the halo froze until something else redrew the
         * window. The repaint composites the cached region buffers and runs
         * every overlay pass; the viewport is not re-rendered. */
        WM_paint_cursor_tag_redraw(&win, region);
        break;
      }
    }
  }
  return OPERATOR_FINISHED;
}

void MIXAR_OT_agent_halo_redraw(wmOperatorType *ot)
{
  ot->name = "Agent Halo Redraw";
  ot->idname = "MIXAR_OT_agent_halo_redraw";
  ot->description = "Advance the agent-working halo animation without re-rendering the viewport";
  ot->exec = agent_halo_redraw_exec;
  ot->flag = OPTYPE_INTERNAL;
}

/** \} */

}  // namespace blender
