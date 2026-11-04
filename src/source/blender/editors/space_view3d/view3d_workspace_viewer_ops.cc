/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include <algorithm>
#include "MEM_guardedalloc.h"
#include "BLI_listbase.h"
#include "BKE_context.hh"
#include "BKE_main.hh"
#include "BKE_scene.hh"
#include "BKE_screen.hh"
#include "DEG_depsgraph.hh"
#include "DEG_depsgraph_query.hh"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "DRW_engine.hh"
#include "ED_screen.hh"
#include "ED_space_api.hh"
#include "RNA_access.hh"
#include "RNA_define.hh"
#include "UI_interface.hh"
#include "WM_api.hh"
#include "WM_types.hh"
#include "view3d_workspace_viewer.hh"

namespace blender {
namespace {
WorkspaceViewer *active = nullptr;

bool owner_alive(bContext *C, WorkspaceViewer &v)
{
  if (!CTX_wm_screen(C)) { return false; }
  for (ScrArea &item : CTX_wm_screen(C)->areabase) {
    ScrArea *area = &item;
    if (area == v.area && area->spacetype == SPACE_VIEW3D) {
      for (ARegion &region_item : area->regionbase) {
        ARegion *region = &region_item;
        if (region == v.region) { return true; }
      }
    }
  }
  return false;
}

void refresh(bContext *C, WorkspaceViewer &v)
{
  Scene *main = CTX_data_scene(C);
  Main *bmain = CTX_data_main(C);
  Vector<WorkspaceTab> tabs;
  PointerRNA wm = RNA_id_pointer_create(&CTX_wm_manager(C)->id);
  if (PropertyRNA *prop = RNA_struct_find_property(&wm, "mixar_agent_cards")) {
    RNA_PROP_BEGIN (&wm, item, prop) {
      WorkspaceTab tab;
      tab.task_id = RNA_string_get(&item, "task_id");
      tab.name = RNA_string_get(&item, "name");
      tab.ordinal = int(tabs.size());
      tab.available = view3d_workspace_scene(bmain, main, tab.task_id) != nullptr;
      tabs.append(std::move(tab));
    }
    RNA_PROP_END;
  }
  // Keep the selected tab as an honest ended state after its scene/card is removed.
  bool selected_present = false;
  for (const auto &tab : tabs) { selected_present |= tab.task_id == v.task_id; }
  if (!selected_present) {
    for (const auto &old : v.tabs) {
      if (old.task_id == v.task_id) {
        WorkspaceTab ended = old;
        ended.available = false;
        tabs.append(std::move(ended));
        break;
      }
    }
  }
  v.tabs = std::move(tabs);
  Scene *scene = view3d_workspace_scene(bmain, main, v.task_id);
  if (!scene) {
    v.has_render = false; // Never leave a stale frame labelled as live.
    v.scene_uid = 0;
    return;
  }
  if (v.scene_uid != scene->id.session_uid) {
    v.has_render = false;
    v.scene_uid = scene->id.session_uid;
  }
  ViewLayer *layer = static_cast<ViewLayer *>(scene->view_layers.first);
  if (!layer) { return; }
  Depsgraph *depsgraph = BKE_scene_ensure_depsgraph(bmain, scene, layer);
  bool visible_elsewhere = false;
  for (wmWindow &window_item : CTX_wm_manager(C)->windows) {
    wmWindow *window = &window_item;
    visible_elsewhere |= WM_window_get_active_scene(window) == scene;
  }
  // Evaluation belongs to the event loop, NEVER to the draw callback.
  if (depsgraph && !visible_elsewhere &&
      (DEG_id_type_any_updated(depsgraph) || DEG_get_update_count(depsgraph) == 0))
  {
    BKE_scene_graph_update_tagged(depsgraph, bmain);
  }
}

void finish(bContext *C, wmOperator *op)
{
  auto *v = static_cast<WorkspaceViewer *>(op->customdata);
  if (!v) { return; }
  ARegionType *art = BKE_regiontype_from_id(BKE_spacetype_from_id(SPACE_VIEW3D), RGN_TYPE_WINDOW);
  if (v->draw_handle) { ED_region_draw_cb_exit(art, v->draw_handle); }
  WM_event_timer_remove(CTX_wm_manager(C), nullptr, v->timer);
  if (v->region && owner_alive(C, *v)) { ED_area_tag_redraw(v->area); }
  DRW_gpu_context_enable();
  view3d_workspace_viewer_gpu_free(*v);
  DRW_gpu_context_disable();
  if (active == v) { active = nullptr; }
  MEM_delete(v);
  op->customdata = nullptr;
}

wmOperatorStatus invoke(bContext *C, wmOperator *op, const wmEvent *)
{
  if (active) { return OPERATOR_CANCELLED; }
  const std::string task = RNA_string_get(op->ptr, "task_id");
  if (!view3d_workspace_scene(CTX_data_main(C), CTX_data_scene(C), task)) {
    return OPERATOR_CANCELLED;
  }
  ScrArea *area = CTX_wm_area(C);
  if (!area || area->spacetype != SPACE_VIEW3D) { return OPERATOR_CANCELLED; }
  ARegion *region = BKE_area_find_region_type(area, RGN_TYPE_WINDOW);
  if (!region) { return OPERATOR_CANCELLED; }
  auto *v = MEM_new<WorkspaceViewer>(__func__);
  v->area = area;
  v->region = region;
  v->task_id = task;
  v->main_session = view3d_workspace_rna_string(CTX_data_scene(C), "mixie_session_id");
  v->run_id = view3d_workspace_rna_string(CTX_data_scene(C), "mixie_run_id");
  refresh(C, *v);
  v->draw_handle = ED_region_draw_cb_activate(
      region->runtime->type, view3d_workspace_viewer_draw, v, REGION_DRAW_POST_PIXEL);
  v->timer = WM_event_timer_add(CTX_wm_manager(C), CTX_wm_window(C), TIMER, 0.1);
  active = v;
  op->customdata = v;
  WM_event_add_modal_handler(C, op);
  ED_area_tag_redraw(area);
  return OPERATOR_RUNNING_MODAL;
}

wmOperatorStatus modal(bContext *C, wmOperator *op, const wmEvent *event)
{
  auto &v = *static_cast<WorkspaceViewer *>(op->customdata);
  if (!v.region || !owner_alive(C, v) ||
      v.main_session != view3d_workspace_rna_string(CTX_data_scene(C), "mixie_session_id") ||
      v.run_id != view3d_workspace_rna_string(CTX_data_scene(C), "mixie_run_id"))
  {
    finish(C, op);
    return OPERATOR_FINISHED;
  }
  if (event->type == EVT_ESCKEY && event->val == KM_PRESS) {
    finish(C, op);
    return OPERATOR_FINISHED;
  }
  if (event->type == TIMER && event->customdata == v.timer) {
    refresh(C, v);
    ED_region_tag_redraw(v.region);
    return OPERATOR_RUNNING_MODAL;
  }
  // This is a WINDOW-level modal handler, so it sees every event before any
  // region does. Claim only what lands on the viewer's own 3D viewport region
  // (the visual lookup honours overlap, so the Moodboard drawer, toolbar and
  // headers painted over the viewport resolve to themselves). Everything
  // else — the topbar mode slider, the drawer, the island, other areas —
  // must keep working while the preview is open; swallowing it left the user
  // stuck once the drawer slid over the close button.
  if (!ISTIMER(event->type) &&
      ED_area_find_region_xy_visual(v.area, RGN_TYPE_ANY, event->xy) != v.region)
  {
    return OPERATOR_PASS_THROUGH;
  }
  const int x = event->xy[0] - v.region->winrct.xmin;
  const int y = event->xy[1] - v.region->winrct.ymin;
  if (event->type == LEFTMOUSE && event->val == KM_PRESS) {
    if (BLI_rcti_isect_pt(&v.close, x, y)) {
      finish(C, op);
      return OPERATOR_FINISHED;
    }
    if (BLI_rcti_isect_pt(&v.previous, x, y)) { v.scroll -= 240 * UI_SCALE_FAC; }
    else if (BLI_rcti_isect_pt(&v.next, x, y)) { v.scroll += 240 * UI_SCALE_FAC; }
    else if (BLI_rcti_isect_pt(&v.bar, x, y)) {
      for (const auto &tab : v.tabs) {
        if (tab.available && BLI_rcti_isect_pt(&tab.rect, x, y)) {
          v.task_id = tab.task_id;
          v.has_render = false;
          refresh(C, v);
          break;
        }
      }
    }
    else if (!BLI_rcti_isect_pt(&v.image, x, y)) {
      // Outside the preview and its bar: dismiss, the same way the agent
      // island collapses on an outside click. The press is consumed rather
      // than passed on so the dismissing click cannot orbit the scene.
      finish(C, op);
      return OPERATOR_FINISHED;
    }
    v.scroll = std::clamp(v.scroll, 0.0f, v.scroll_max);
    ED_region_tag_redraw(v.region);
    return OPERATOR_RUNNING_MODAL;
  }
  if (BLI_rcti_isect_pt(&v.bar, x, y)) {
    if (event->type == WHEELDOWNMOUSE || event->type == WHEELUPMOUSE) {
      v.scroll += (event->type == WHEELDOWNMOUSE ? 120 : -120) * UI_SCALE_FAC;
    }
    else if (event->type == MOUSEPAN) {
      const int dx = WM_event_absolute_delta_x(event), dy = WM_event_absolute_delta_y(event);
      v.scroll += std::abs(dx) > std::abs(dy) ? -dx : dy;
    }
    v.scroll = std::clamp(v.scroll, 0.0f, v.scroll_max);
    ED_region_tag_redraw(v.region);
  }
  // Other timers/notifications keep agents and the viewport lock alive.
  if (ISTIMER(event->type)) { return OPERATOR_PASS_THROUGH; }
  // Preview is read-only: never orbit, select or edit the main scene behind it.
  return OPERATOR_RUNNING_MODAL;
}
void cancel(bContext *C, wmOperator *op) { finish(C, op); }
void register_operator(wmOperatorType *ot)
{
  ot->name = "View Agent Workspace";
  ot->idname = "VIEW3D_OT_workspace_viewer";
  ot->description =
      "Watch this agent's separate scene; Escape or a click outside closes the preview";
  ot->invoke = invoke;
  ot->modal = modal;
  ot->cancel = cancel;
  RNA_def_string(ot->srna, "task_id", nullptr, 0, "Task", "Workspace task identity");
}
}  // namespace
WorkspaceViewer *view3d_workspace_viewer_active() { return active; }
void view3d_workspace_viewer_register() { WM_operatortype_append(register_operator); }
void view3d_workspace_viewer_region_free(ARegion *region)
{
  if (active && active->region == region) {
    // The modal owns the allocation; invalidate its region before Blender frees it.
    active->region = nullptr;
    DRW_gpu_context_enable();
    view3d_workspace_viewer_gpu_free(*active);
    DRW_gpu_context_disable();
  }
}
}  // namespace blender
