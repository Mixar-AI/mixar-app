/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Click or drag to place the shot camera: on the Cinema Mode aerial map
 * card, or anywhere in the stage while the AERIAL view is on.
 *
 * `MIXAR_OT_director_place_camera` is a native modal shaped like the camera
 * nudge (`view3d_director_nudge.cc`): the press places the camera at the
 * world XY under the cursor (its Z and rotation untouched, so a Track To
 * constraint keeps the aim), every mouse move while the button is held
 * places it again, the release ends it as ONE undo step (`OPTYPE_UNDO`), and
 * Esc / RMB put the camera back where it started.
 *
 * Two sources for the world XY, fixed at the press:
 * - over the aerial map card: the transform the card painter published
 *   (#view3d_director_minimap_world_from_region_px), clamped to the map;
 * - in the stage while `navigation_mode == AERIAL` (the main viewport is an
 *   ORTHO top view): the region pixel projected onto the plane
 *   `z = camera.z` (#ED_view3d_win_to_3d_on_plane). In an orthographic view
 *   the pick ray is parallel to the view axis, so for a top view the
 *   intersection with any horizontal plane has the same XY — the result is
 *   exact whatever Z the plane sits at.
 *
 * The keymap contract lives in `director/ui/keymap.py`: a plain LEFTMOUSE
 * PRESS in the addon "3D View" keymap. The POLL is what scopes it — a
 * directing session, a 3D viewport's WINDOW region, and the cursor over the
 * map rect or, in Aerial, inside the stage (never over the columns, whose
 * invisible uiButs are asked first anyway) — so anywhere else the press
 * falls through to `view3d.select` and friends untouched. Over a valid
 * target the press is absorbed even when there is nothing to move (no
 * camera, locked take).
 */

#include "MEM_guardedalloc.h"

#include "BLI_math_geom.h"
#include "BLI_math_matrix_types.hh"
#include "BLI_math_vector_types.hh"
#include "BLI_rect.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"
#include "BKE_object.hh"
#include "BKE_report.hh"
#include "BKE_wm_runtime.hh"

#include "DEG_depsgraph.hh"

#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"
#include "ED_view3d.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "UI_interface_c.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/** `navigation_mode` enum index of the AERIAL item (see `director_properties.py`). */
constexpr int NAVIGATION_MODE_AERIAL = 3;

struct PlaceCameraData {
  /** Resolved at invoke; re-resolved on every move so a shot switch or a
   * camera removal mid-drag ends the placement instead of touching a stale
   * pointer. */
  Object *camera = nullptr;
  /** WORLD matrix when the press landed, for Esc / RMB. */
  float4x4 start_matrix;
  /** Running WORLD matrix: only the XY of its translation ever changes. */
  float4x4 matrix;
  /** Where the press landed decides the mapping for the whole drag. */
  bool on_map = false;
  bool moved = false;
};

bool aerial_mode(bContext *C)
{
  return view3d_director_navigation_mode(CTX_data_scene(C)) == NAVIGATION_MODE_AERIAL;
}

/** Whether region px (\a x, \a y) is a stage press in Aerial mode. */
bool stage_contains(const bContext *C, const ARegion *region, const int x, const int y)
{
  rctf stage;
  if (cinema_stage_rect(C, region, &stage)) {
    return BLI_rctf_isect_pt(&stage, float(x), float(y));
  }
  /* Compact layout: no columns, the whole region is the stage. */
  return x >= 0 && y >= 0 && x < region->winx && y < region->winy;
}

/** World XY under the region px for the drag's mapping; false when unmappable. */
bool world_xy_at(const bContext *C,
                 const ARegion *region,
                 const PlaceCameraData *data,
                 const int mval[2],
                 float r_xy[2])
{
  if (data->on_map) {
    return view3d_director_minimap_world_from_region_px(region, mval[0], mval[1], r_xy);
  }
  UNUSED_VARS(C);
  const float3 &loc = data->matrix.location();
  float plane[4];
  const float normal[3] = {0.0f, 0.0f, 1.0f};
  plane_from_point_normal_v3(plane, loc, normal);
  const float mval_f[2] = {float(mval[0]), float(mval[1])};
  float out[3];
  if (!ED_view3d_win_to_3d_on_plane(region, plane, mval_f, false, out)) {
    return false;
  }
  r_xy[0] = out[0];
  r_xy[1] = out[1];
  return true;
}

/** Write \a matrix to the camera and let everything that watches it know. */
void place_camera_write(bContext *C, Object *camera, const float4x4 &matrix)
{
  /* Through the WORLD matrix so a parented camera lands where asked, not
   * where its parent's transform makes of the point; `use_compat` keeps the
   * Euler continuity of the current rotation. */
  BKE_object_apply_mat4(camera, matrix.ptr(), true, true);
  DEG_id_tag_update(&camera->id, ID_RECALC_TRANSFORM);
  WM_event_add_notifier(C, NC_OBJECT | ND_TRANSFORM, camera);
  if (ARegion *region = CTX_wm_region(C)) {
    ED_region_tag_redraw(region);
  }
}

/** Place the camera at world (\a xy), keeping its Z and rotation. */
void place_camera_apply(bContext *C, PlaceCameraData *data, const float xy[2])
{
  float3 &loc = data->matrix.location();
  if (loc.x == xy[0] && loc.y == xy[1]) {
    return;
  }
  loc.x = xy[0];
  loc.y = xy[1];
  place_camera_write(C, data->camera, data->matrix);
  data->moved = true;
}

void place_camera_exit(wmOperator *op)
{
  PlaceCameraData *data = static_cast<PlaceCameraData *>(op->customdata);
  if (data) {
    MEM_delete(data);
    op->customdata = nullptr;
  }
}

/** Esc / RMB / WM cancel: the camera goes back to where the press found it. */
void place_camera_cancel(bContext *C, wmOperator *op)
{
  PlaceCameraData *data = static_cast<PlaceCameraData *>(op->customdata);
  if (data && data->moved) {
    bool locked = false;
    if (view3d_director_shot_camera(CTX_data_scene(C), &locked) == data->camera) {
      place_camera_write(C, data->camera, data->start_matrix);
    }
  }
  place_camera_exit(op);
}

/** Release: one undo step for the whole drag; nothing to undo if it never moved. */
wmOperatorStatus place_camera_finish(wmOperator *op)
{
  const PlaceCameraData *data = static_cast<PlaceCameraData *>(op->customdata);
  const bool moved = data && data->moved;
  place_camera_exit(op);
  return moved ? OPERATOR_FINISHED : OPERATOR_CANCELLED;
}

/**
 * Directing, cursor in a 3D viewport's WINDOW region, and over the map the
 * painter published this frame — or inside the stage while Aerial is on.
 * Polls carry no event, so the cursor comes from the window's event state
 * (the way `ui_view_drop_poll` finds its view).
 */
bool place_camera_poll(bContext *C)
{
  if (!view3d_director_is_directing(CTX_data_scene(C))) {
    return false;
  }
  const ScrArea *area = CTX_wm_area(C);
  const ARegion *region = CTX_wm_region(C);
  if (!(area && region && area->spacetype == SPACE_VIEW3D &&
        region->regiontype == RGN_TYPE_WINDOW))
  {
    return false;
  }
  const wmWindow *win = CTX_wm_window(C);
  if (!(win && win->runtime && win->runtime->eventstate)) {
    return false;
  }
  const int x = win->runtime->eventstate->xy[0] - region->winrct.xmin;
  const int y = win->runtime->eventstate->xy[1] - region->winrct.ymin;
  if (view3d_director_minimap_contains(region, x, y)) {
    return true;
  }
  return aerial_mode(C) && stage_contains(C, region, x, y);
}

wmOperatorStatus place_camera_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  const ARegion *region = CTX_wm_region(C);
  if (!region) {
    return OPERATOR_CANCELLED | OPERATOR_PASS_THROUGH;
  }
  const bool on_map = view3d_director_minimap_contains(region, event->mval[0], event->mval[1]);
  if (!on_map && !(aerial_mode(C) && stage_contains(C, region, event->mval[0], event->mval[1]))) {
    /* No target under the press after all: leave the click to the viewport. */
    return OPERATOR_CANCELLED | OPERATOR_PASS_THROUGH;
  }

  bool locked = false;
  Object *camera = view3d_director_shot_camera(CTX_data_scene(C), &locked);
  if (!camera) {
    /* Absorbed: nothing under the target should take the press. */
    BKE_report(op->reports, RPT_INFO, "Add a camera to place it");
    return OPERATOR_CANCELLED;
  }
  if (locked) {
    BKE_report(
        op->reports, RPT_INFO, "This take is locked; start a new take to move the camera");
    return OPERATOR_CANCELLED;
  }

  PlaceCameraData *data = MEM_new<PlaceCameraData>(__func__);
  data->camera = camera;
  data->start_matrix = camera->object_to_world();
  data->matrix = data->start_matrix;
  data->on_map = on_map;
  op->customdata = data;
  float xy[2];
  if (!world_xy_at(C, region, data, event->mval, xy)) {
    place_camera_exit(op);
    return OPERATOR_CANCELLED;
  }
  place_camera_apply(C, data, xy);

  WM_event_add_modal_handler(C, op);
  return OPERATOR_RUNNING_MODAL;
}

wmOperatorStatus place_camera_modal(bContext *C, wmOperator *op, const wmEvent *event)
{
  PlaceCameraData *data = static_cast<PlaceCameraData *>(op->customdata);
  if (!data) {
    return OPERATOR_CANCELLED;
  }

  switch (event->type) {
    case MOUSEMOVE:
    case INBETWEEN_MOUSEMOVE: {
      bool locked = false;
      Object *camera = view3d_director_shot_camera(CTX_data_scene(C), &locked);
      if (camera != data->camera || locked) {
        /* Shot switched, camera removed, or the take got locked mid-drag. */
        return place_camera_finish(op);
      }
      const ARegion *region = CTX_wm_region(C);
      float xy[2];
      /* On the map the transform clamps to its world extents. */
      if (region && world_xy_at(C, region, data, event->mval, xy)) {
        place_camera_apply(C, data, xy);
      }
      return OPERATOR_RUNNING_MODAL;
    }
    case LEFTMOUSE:
      if (event->val == KM_RELEASE) {
        return place_camera_finish(op);
      }
      return OPERATOR_RUNNING_MODAL;
    case EVT_ESCKEY:
    case RIGHTMOUSE:
      if (event->val == KM_PRESS) {
        place_camera_cancel(C, op);
        return OPERATOR_CANCELLED;
      }
      return OPERATOR_RUNNING_MODAL;
    default:
      /* A drag owns the pointer; keys keep their meaning after the release. */
      return OPERATOR_RUNNING_MODAL;
  }
}

}  // namespace

void MIXAR_OT_director_place_camera(wmOperatorType *ot)
{
  ot->name = "Place Camera";
  ot->idname = "MIXAR_OT_director_place_camera";
  ot->description =
      "Move the shot camera to the point under the cursor on the aerial map or, in the aerial "
      "view, in the stage, keeping its height and aim";

  ot->invoke = place_camera_invoke;
  ot->modal = place_camera_modal;
  ot->cancel = place_camera_cancel;
  ot->poll = place_camera_poll;

  /* OPTYPE_UNDO, never UNDO_GROUPED: the whole drag is ONE undo step because
   * it is ONE operator call. Not BLOCKING: the modal handler already owns
   * the pointer while it runs. */
  ot->flag = OPTYPE_UNDO;
}

}  // namespace blender
