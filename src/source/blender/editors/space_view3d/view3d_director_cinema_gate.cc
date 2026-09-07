/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: fit the camera gate to the stage.
 *
 * The design's working area between the two columns used to carry a
 * decorative rounded frame with the camera border floating inside it. The
 * frame is gone; instead the camera view's zoom and pan are set so the
 * border itself fills that area. The fit runs from the overlay draw but
 * only when the layout changed (region size, stage rect, camera), so it is
 * a one-off write per layout, not a per-frame fight with the director's own
 * zooming and panning.
 */

#include <algorithm>
#include <vector>

#include "BLI_rect.h"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "DNA_screen_types.h"
#include "DNA_view3d_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"
#include "ED_space_api.hh"
#include "ED_view3d.hh"

#include "UI_interface_c.hh"

#include "view3d_director_cinema.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

struct GateFit {
  const ARegion *region = nullptr;
  int winx = 0;
  int winy = 0;
  rcti stage = {};
  const void *camera = nullptr;
};

std::vector<GateFit> g_fits;

bool fit_matches(const GateFit &a, const GateFit &b)
{
  return a.winx == b.winx && a.winy == b.winy && a.camera == b.camera &&
         BLI_rcti_compare(&a.stage, &b.stage);
}

}  // namespace

bool cinema_camera_gate_rect(const bContext *C, const ARegion *region, rctf *r_rect)
{
  const RegionView3D *rv3d = static_cast<const RegionView3D *>(region->regiondata);
  const View3D *v3d = CTX_wm_view3d(C);
  const Scene *scene = CTX_data_scene(C);
  if (rv3d == nullptr || v3d == nullptr || scene == nullptr || v3d->camera == nullptr ||
      rv3d->persp != RV3D_CAMOB)
  {
    return false;
  }
  const Depsgraph *depsgraph = CTX_data_depsgraph_pointer(C);
  if (depsgraph == nullptr) {
    return false;
  }
  ED_view3d_calc_camera_border(scene, depsgraph, region, v3d, rv3d, false, r_rect);
  return BLI_rctf_size_x(r_rect) > 1.0f && BLI_rctf_size_y(r_rect) > 1.0f;
}

void cinema_release_chat_seat(const bContext *C)
{
  ED_agent_bubble_set_cinema_seat(CTX_wm_window(C), false, 0);
}

void cinema_fit_camera_gate(const bContext *C, ARegion *region)
{
  RegionView3D *rv3d = static_cast<RegionView3D *>(region->regiondata);
  const View3D *v3d = CTX_wm_view3d(C);
  const Scene *scene = CTX_data_scene(C);
  if (rv3d == nullptr || v3d == nullptr || scene == nullptr || v3d->camera == nullptr ||
      rv3d->persp != RV3D_CAMOB)
  {
    return;
  }
  rctf stage;
  if (!cinema_stage_rect(C, region, &stage)) {
    return;
  }
  const float u = cinema_unit();
  wmWindow *win = CTX_wm_window(C);

  /* The chat bar — the resting Agent pill — sits centred on the host with
   * its foot CINEMA_CHAT_GAP above the timeline's top border (the region's
   * bottom edge, as a margin from the host's content bottom). The gate
   * keeps CINEMA_CHAT_GAP clear above the pill, or ends on the columns'
   * foot when that is higher. Handed over every draw, no-op when unchanged. */
  const float chat_gap = CINEMA_CHAT_GAP * u;
  const float pill_bottom = chat_gap;
  const float pill_top = pill_bottom + float(ED_agent_bubble_pill_band_px(win));
  ED_agent_bubble_set_cinema_seat(win, true, region->winrct.ymin + int(pill_bottom));
  /* The frame's foot is free: it may run below the columns' foot, down to
   * the chat bar. Only the gap above the bar bounds it. */
  stage.ymin = pill_top + chat_gap;

  GateFit fit;
  fit.region = region;
  fit.winx = region->winx;
  fit.winy = region->winy;
  BLI_rcti_rctf_copy(&fit.stage, &stage);
  fit.camera = v3d->camera;
  GateFit *record = nullptr;
  for (GateFit &item : g_fits) {
    if (item.region == region) {
      record = &item;
      break;
    }
  }
  if (record != nullptr && fit_matches(*record, fit)) {
    return;
  }

  const Depsgraph *depsgraph = CTX_data_depsgraph_pointer(C);
  if (depsgraph == nullptr) {
    return;
  }
  rctf target = stage;
  BLI_rctf_pad(&target, -CINEMA_GATE_PAD * u, -CINEMA_GATE_PAD * u);
  if (BLI_rctf_size_x(&target) <= 1.0f || BLI_rctf_size_y(&target) <= 1.0f) {
    return;
  }

  /* The border scales linearly with the zoom factor: size it first. The
   * width between the columns is what the frame is sized to; the height
   * only bounds it (a portrait aspect must still end above the chat bar). */
  rctf border;
  ED_view3d_calc_camera_border(scene, depsgraph, region, v3d, rv3d, false, &border);
  const float border_w = BLI_rctf_size_x(&border);
  const float border_h = BLI_rctf_size_y(&border);
  if (border_w <= 1.0f || border_h <= 1.0f) {
    return;
  }
  const float fac = BKE_screen_view3d_zoom_to_fac(rv3d->camzoom);
  const float scale = std::min(BLI_rctf_size_x(&target) / border_w,
                               BLI_rctf_size_y(&target) / border_h);
  rv3d->camzoom = std::clamp(BKE_screen_view3d_zoom_from_fac(fac * scale),
                             float(RV3D_CAMZOOM_MIN),
                             float(RV3D_CAMZOOM_MAX));
  const float fac_now = BKE_screen_view3d_zoom_to_fac(rv3d->camzoom);

  /* Then place it: centred between the columns, TOP on the columns' top.
   * The view plane shifts by `winx * 2 * camdx * fac` (see
   * BKE_camera_params_from_view3d / _compute_viewplane), which moves the
   * border the OTHER way by the same amount in region px. */
  ED_view3d_calc_camera_border(scene, depsgraph, region, v3d, rv3d, false, &border);
  const float dx = BLI_rctf_cent_x(&target) - BLI_rctf_cent_x(&border);
  const float dy = target.ymax - border.ymax;
  rv3d->camdx = std::clamp(rv3d->camdx - dx / (2.0f * fac_now * float(region->winx)), -1.0f, 1.0f);
  rv3d->camdy = std::clamp(rv3d->camdy - dy / (2.0f * fac_now * float(region->winy)), -1.0f, 1.0f);

  if (record != nullptr) {
    *record = fit;
  }
  else {
    g_fits.push_back(fit);
  }
  ED_region_tag_redraw(region);
}

}  // namespace blender
