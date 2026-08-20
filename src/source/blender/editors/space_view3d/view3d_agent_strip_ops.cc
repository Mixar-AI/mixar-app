/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Agent Scene Strip operators: per-tile camera navigation (modal orbit/pan,
 * wheel zoom) and click-to-activate, plus the strip keymap.
 *
 * The modal operator stores the tile's scene *name* and re-resolves it
 * every event, so a tile rebuild (scene added/removed by an agent during
 * the drag) aborts cleanly instead of dereferencing a stale pointer.
 */

#include <algorithm>
#include <cmath>
#include <string>

#include "MEM_guardedalloc.h"

#include "BLI_math_rotation.h"
#include "BLI_math_vector.h"
#include "BLI_rect.h"

#include "BKE_context.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "ED_screen.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_agent_strip.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Shared Helpers
 * \{ */

enum {
  AGENT_STRIP_NAV_ORBIT = 0,
  AGENT_STRIP_NAV_PAN = 1,
};

static bool agent_strip_region_active(bContext *C)
{
  ScrArea *area = CTX_wm_area(C);
  ARegion *region = CTX_wm_region(C);
  return area && area->spacetype == SPACE_VIEW3D && region &&
         region->regiontype == RGN_TYPE_EXECUTE;
}

static AgentStripRuntime *agent_strip_runtime_from_context(bContext *C)
{
  if (!agent_strip_region_active(C)) {
    return nullptr;
  }
  return static_cast<AgentStripRuntime *>(CTX_wm_region(C)->regiondata);
}

static bool agent_strip_op_poll(bContext *C)
{
  return agent_strip_region_active(C);
}

/** Request an immediate re-render of the tile (bypasses the rate limit so
 * navigation feels live) and redraw the region. */
static void tile_tag_navigation_update(bContext *C, AgentStripTile *tile)
{
  tile->dirty = true;
  tile->last_render_time = 0.0;
  ED_region_tag_redraw(CTX_wm_region(C));
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Camera Math
 * \{ */

static void camera_orbit(AgentStripCamera *cam, const float dx, const float dy)
{
  const float sensitivity = 0.007f;
  float q[4];

  /* Turntable: horizontal drag rotates around world Z... */
  axis_angle_to_quat_single(q, 'Z', dx * sensitivity);
  mul_qt_qtqt(cam->viewquat, cam->viewquat, q);

  /* ...vertical drag around the view-local X axis (world-space direction =
   * inverse view rotation applied to view X — viewinv[0] in RegionView3D). */
  float invq[4];
  float xaxis[3] = {1.0f, 0.0f, 0.0f};
  invert_qt_qt_normalized(invq, cam->viewquat);
  mul_qt_v3(invq, xaxis);
  axis_angle_to_quat(q, xaxis, dy * sensitivity);
  mul_qt_qtqt(cam->viewquat, cam->viewquat, q);

  normalize_qt(cam->viewquat);
}

static void camera_pan(AgentStripCamera *cam, const float dx, const float dy, const int tile_h)
{
  /* World units per pixel at the orbit pivot's depth. */
  const float world_per_px = (2.0f * cam->dist * tanf(AGENT_STRIP_FOV_Y * 0.5f)) /
                             float(std::max(tile_h, 1));

  /* Same convention as View3D viewmove: ofs moves by (prev - cur) so the
   * scene follows the cursor. */
  float delta[3] = {-dx * world_per_px, -dy * world_per_px, 0.0f};
  float invq[4];
  invert_qt_qt_normalized(invq, cam->viewquat);
  mul_qt_v3(invq, delta);
  add_v3_v3(cam->ofs, delta);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Tile Navigate Operator (modal orbit / pan)
 * \{ */

struct TileNavOpData {
  std::string scene_name;
  AgentStripCamera init_cam;
  int mode;
  int prev_xy[2];
  int tile_h;
};

static void tile_navigate_exit(wmOperator *op)
{
  TileNavOpData *data = static_cast<TileNavOpData *>(op->customdata);
  MEM_delete(data);
  op->customdata = nullptr;
}

static void tile_navigate_restore(bContext *C, wmOperator *op)
{
  TileNavOpData *data = static_cast<TileNavOpData *>(op->customdata);
  AgentStripRuntime *runtime = agent_strip_runtime_from_context(C);
  AgentStripTile *tile = runtime ? view3d_agent_strip_tile_find_named(runtime,
                                                                      data->scene_name.c_str()) :
                                   nullptr;
  if (tile) {
    tile->cam = data->init_cam;
    tile_tag_navigation_update(C, tile);
  }
}

static wmOperatorStatus tile_navigate_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  AgentStripRuntime *runtime = agent_strip_runtime_from_context(C);
  if (!runtime) {
    return OPERATOR_PASS_THROUGH;
  }
  AgentStripTile *tile = view3d_agent_strip_tile_at(runtime, event->mval);
  if (!tile) {
    return OPERATOR_PASS_THROUGH;
  }

  TileNavOpData *data = MEM_new<TileNavOpData>("TileNavOpData");
  data->scene_name = tile->scene_name;
  data->init_cam = tile->cam;
  data->mode = RNA_enum_get(op->ptr, "mode");
  data->prev_xy[0] = event->xy[0];
  data->prev_xy[1] = event->xy[1];
  data->tile_h = BLI_rcti_size_y(&tile->rect) + 1;
  op->customdata = data;

  WM_event_add_modal_handler(C, op);
  return OPERATOR_RUNNING_MODAL;
}

static wmOperatorStatus tile_navigate_modal(bContext *C, wmOperator *op, const wmEvent *event)
{
  TileNavOpData *data = static_cast<TileNavOpData *>(op->customdata);
  AgentStripRuntime *runtime = agent_strip_runtime_from_context(C);
  AgentStripTile *tile = runtime ? view3d_agent_strip_tile_find_named(runtime,
                                                                      data->scene_name.c_str()) :
                                   nullptr;
  if (!tile) {
    /* Scene removed mid-drag. */
    tile_navigate_exit(op);
    return OPERATOR_CANCELLED;
  }

  switch (event->type) {
    case MOUSEMOVE: {
      const float dx = float(event->xy[0] - data->prev_xy[0]);
      const float dy = float(event->xy[1] - data->prev_xy[1]);
      data->prev_xy[0] = event->xy[0];
      data->prev_xy[1] = event->xy[1];

      if (data->mode == AGENT_STRIP_NAV_PAN) {
        camera_pan(&tile->cam, dx, dy, data->tile_h);
      }
      else {
        camera_orbit(&tile->cam, dx, dy);
      }
      tile_tag_navigation_update(C, tile);
      break;
    }
    case LEFTMOUSE:
    case MIDDLEMOUSE:
      if (event->val == KM_RELEASE) {
        tile_navigate_exit(op);
        return OPERATOR_FINISHED;
      }
      break;
    case EVT_ESCKEY:
    case RIGHTMOUSE:
      if (event->val == KM_PRESS) {
        tile_navigate_restore(C, op);
        tile_navigate_exit(op);
        return OPERATOR_CANCELLED;
      }
      break;
    default:
      break;
  }

  return OPERATOR_RUNNING_MODAL;
}

static void tile_navigate_cancel(bContext *C, wmOperator *op)
{
  tile_navigate_restore(C, op);
  tile_navigate_exit(op);
}

static void VIEW3D_OT_agent_strip_navigate(wmOperatorType *ot)
{
  static const EnumPropertyItem nav_mode_items[] = {
      {AGENT_STRIP_NAV_ORBIT, "ORBIT", 0, "Orbit", "Rotate the tile's view around its pivot"},
      {AGENT_STRIP_NAV_PAN, "PAN", 0, "Pan", "Move the tile's view pivot"},
      {0, nullptr, 0, nullptr, nullptr},
  };

  ot->name = "Navigate Agent Scene Tile";
  ot->idname = "VIEW3D_OT_agent_strip_navigate";
  ot->description = "Orbit or pan the viewport of the agent scene tile under the cursor";

  ot->invoke = tile_navigate_invoke;
  ot->modal = tile_navigate_modal;
  ot->cancel = tile_navigate_cancel;
  ot->poll = agent_strip_op_poll;

  ot->flag = OPTYPE_BLOCKING;

  RNA_def_enum(ot->srna, "mode", nav_mode_items, AGENT_STRIP_NAV_ORBIT, "Mode", "");
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Tile Zoom Operator (wheel)
 * \{ */

static wmOperatorStatus tile_zoom_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  AgentStripRuntime *runtime = agent_strip_runtime_from_context(C);
  if (!runtime) {
    return OPERATOR_PASS_THROUGH;
  }
  AgentStripTile *tile = view3d_agent_strip_tile_at(runtime, event->mval);
  if (!tile) {
    return OPERATOR_PASS_THROUGH;
  }

  const int delta = RNA_int_get(op->ptr, "delta");
  const float factor = 1.15f;
  tile->cam.dist = (delta > 0) ? tile->cam.dist / factor : tile->cam.dist * factor;
  tile->cam.dist = std::clamp(tile->cam.dist, 0.01f, 10000.0f);

  tile_tag_navigation_update(C, tile);
  return OPERATOR_FINISHED;
}

static void VIEW3D_OT_agent_strip_zoom(wmOperatorType *ot)
{
  ot->name = "Zoom Agent Scene Tile";
  ot->idname = "VIEW3D_OT_agent_strip_zoom";
  ot->description = "Zoom the viewport of the agent scene tile under the cursor";

  ot->invoke = tile_zoom_invoke;
  ot->poll = agent_strip_op_poll;

  ot->flag = 0;

  RNA_def_int(ot->srna, "delta", 1, -1, 1, "Delta", "Zoom direction", -1, 1);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Activate Scene Operator (click)
 * \{ */

static wmOperatorStatus activate_scene_invoke(bContext *C,
                                              wmOperator * /*op*/,
                                              const wmEvent *event)
{
  AgentStripRuntime *runtime = agent_strip_runtime_from_context(C);
  if (!runtime) {
    return OPERATOR_PASS_THROUGH;
  }
  AgentStripTile *tile = view3d_agent_strip_tile_at(runtime, event->mval);
  if (!tile) {
    return OPERATOR_PASS_THROUGH;
  }

  if (tile->scene != CTX_data_scene(C)) {
    WM_window_set_active_scene(CTX_data_main(C), C, CTX_wm_window(C), tile->scene);
    WM_event_add_notifier(C, NC_SPACE | ND_SPACE_AGENT_STRIP, nullptr);
  }
  ED_region_tag_redraw(CTX_wm_region(C));

  return OPERATOR_FINISHED;
}

static void VIEW3D_OT_agent_strip_activate_scene(wmOperatorType *ot)
{
  ot->name = "Activate Agent Scene";
  ot->idname = "VIEW3D_OT_agent_strip_activate_scene";
  ot->description = "Make the clicked tile's scene the active scene of this window";

  ot->invoke = activate_scene_invoke;
  ot->poll = agent_strip_op_poll;

  ot->flag = 0;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Registration & Keymap
 * \{ */

void view3d_agent_strip_operatortypes()
{
  WM_operatortype_append(VIEW3D_OT_agent_strip_navigate);
  WM_operatortype_append(VIEW3D_OT_agent_strip_zoom);
  WM_operatortype_append(VIEW3D_OT_agent_strip_activate_scene);
}

void view3d_agent_strip_keymap(wmKeyConfig *keyconf)
{
  wmKeyMap *keymap = WM_keymap_ensure(
      keyconf, "Agent Scene Strip", SPACE_VIEW3D, RGN_TYPE_EXECUTE);
  wmKeyMapItem *kmi;

  /* Click: make the clicked tile's scene the window's active scene. */
  KeyMapItem_Params click_params{};
  click_params.type = LEFTMOUSE;
  click_params.value = KM_CLICK;
  WM_keymap_add_item(keymap, "VIEW3D_OT_agent_strip_activate_scene", &click_params);

  /* LMB drag: orbit. Shift+LMB drag: pan. */
  KeyMapItem_Params drag_params{};
  drag_params.type = LEFTMOUSE;
  drag_params.value = KM_PRESS_DRAG;
  drag_params.direction = KM_ANY;
  kmi = WM_keymap_add_item(keymap, "VIEW3D_OT_agent_strip_navigate", &drag_params);
  RNA_enum_set(kmi->ptr, "mode", AGENT_STRIP_NAV_ORBIT);

  KeyMapItem_Params drag_pan_params{};
  drag_pan_params.type = LEFTMOUSE;
  drag_pan_params.value = KM_PRESS_DRAG;
  drag_pan_params.direction = KM_ANY;
  drag_pan_params.modifier = KM_SHIFT;
  kmi = WM_keymap_add_item(keymap, "VIEW3D_OT_agent_strip_navigate", &drag_pan_params);
  RNA_enum_set(kmi->ptr, "mode", AGENT_STRIP_NAV_PAN);

  /* MMB: orbit / Shift+MMB: pan — View3D muscle memory. */
  KeyMapItem_Params mmb_params{};
  mmb_params.type = MIDDLEMOUSE;
  mmb_params.value = KM_PRESS;
  kmi = WM_keymap_add_item(keymap, "VIEW3D_OT_agent_strip_navigate", &mmb_params);
  RNA_enum_set(kmi->ptr, "mode", AGENT_STRIP_NAV_ORBIT);

  KeyMapItem_Params mmb_pan_params{};
  mmb_pan_params.type = MIDDLEMOUSE;
  mmb_pan_params.value = KM_PRESS;
  mmb_pan_params.modifier = KM_SHIFT;
  kmi = WM_keymap_add_item(keymap, "VIEW3D_OT_agent_strip_navigate", &mmb_pan_params);
  RNA_enum_set(kmi->ptr, "mode", AGENT_STRIP_NAV_PAN);

  /* Wheel: zoom the hovered tile. */
  KeyMapItem_Params wheel_up_params{};
  wheel_up_params.type = WHEELUPMOUSE;
  wheel_up_params.value = KM_PRESS;
  kmi = WM_keymap_add_item(keymap, "VIEW3D_OT_agent_strip_zoom", &wheel_up_params);
  RNA_int_set(kmi->ptr, "delta", 1);

  KeyMapItem_Params wheel_down_params{};
  wheel_down_params.type = WHEELDOWNMOUSE;
  wheel_down_params.value = KM_PRESS;
  kmi = WM_keymap_add_item(keymap, "VIEW3D_OT_agent_strip_zoom", &wheel_down_params);
  RNA_int_set(kmi->ptr, "delta", -1);
}

/** \} */
}  // namespace blender
