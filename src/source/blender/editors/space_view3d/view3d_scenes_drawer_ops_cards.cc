/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Card operators of the Zen Mode sliding Scenes drawer: `click` turns a press
 * on a scene card (or "+ New scene", or a close glyph) into the Python
 * scene-tab operators (`mixie_chat.new_scene_tab` / `switch_scene_tab` /
 * `close_scene_tab` / `reorder_scene_tab`), a vertical drag reorders, and
 * `hover` tracks the pointer for the highlight. Slide, edge resize,
 * registration and the keymap are in `view3d_scenes_drawer_ops.cc`.
 */

#include <cstdlib>
#include <string>

#include "BLI_rect.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_scenes_drawer.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/** Run a `mixie_chat.*` operator with an optional `scene_name` property. The
 * scene tabs are Python's (the Director split: native surfaces read RNA and
 * invoke Python operators), so nothing here touches a Scene directly. */
static bool drawer_call_python(bContext *C, const char *idname, const char *scene_name,
                               const int index = -1)
{
  wmOperatorType *ot = WM_operatortype_find(idname, true);
  if (ot == nullptr) {
    return false;
  }
  PointerRNA props = WM_operator_properties_create_ptr(ot);
  if (scene_name != nullptr && RNA_struct_find_property(&props, "scene_name") != nullptr) {
    RNA_string_set(&props, "scene_name", scene_name);
  }
  if (index >= 0 && RNA_struct_find_property(&props, "index") != nullptr) {
    RNA_int_set(&props, "index", index);
  }
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, wm::OpCallContext::ExecDefault, &props, nullptr);
  WM_operator_properties_free(&props);
  return status == OPERATOR_FINISHED;
}

static int drawer_card_at(const ScenesDrawerRuntime *runtime, const int xy[2], bool *r_close)
{
  *r_close = false;
  if (runtime == nullptr || runtime->amount < VIEW3D_SCENES_DRAWER_ACTIVE_AMOUNT) {
    return -1;
  }
  for (int i = 0; i < int(runtime->cards.size()); i++) {
    const ScenesDrawerCard &card = runtime->cards[i];
    if (BLI_rcti_isect_pt_v(&card.close_rect, xy)) {
      *r_close = true;
      return i;
    }
    if (BLI_rcti_isect_pt_v(&card.rect, xy)) {
      return i;
    }
  }
  return -1;
}

/** The slot a pointer at `y` (window px) would drop a dragged card into. */
static int drawer_drop_slot(const ScenesDrawerRuntime *runtime, const int y)
{
  const int count = int(runtime->cards.size());
  for (int i = 0; i < count; i++) {
    if (y >= BLI_rcti_cent_y(&runtime->cards[i].rect)) {
      return i;
    }
  }
  return count > 0 ? count - 1 : 0;
}

static wmOperatorStatus drawer_click_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  ARegion *region = CTX_wm_region(C);
  ScenesDrawerRuntime *runtime = region ? static_cast<ScenesDrawerRuntime *>(region->regiondata) :
                                          nullptr;
  if (runtime == nullptr || runtime->amount < VIEW3D_SCENES_DRAWER_ACTIVE_AMOUNT) {
    return OPERATOR_PASS_THROUGH;
  }
  if (view3d_scenes_drawer_edge_hit(C, event->xy)) {
    return OPERATOR_PASS_THROUGH; /* the edge operator owns it */
  }
  if (runtime->new_visible && BLI_rcti_isect_pt_v(&runtime->new_rect, event->xy)) {
    drawer_call_python(C, "MIXIE_CHAT_OT_new_scene_tab", nullptr);
    WM_event_add_notifier(C, NC_SCENE, nullptr);
    ED_region_tag_redraw(region);
    return OPERATOR_FINISHED;
  }
  bool close = false;
  const int index = drawer_card_at(runtime, event->xy, &close);
  if (index < 0) {
    rcti panel;
    /* A press on the panel bed is consumed so the viewport behind never
     * orbits; outside the panel it passes through. */
    return view3d_scenes_drawer_panel_rect_for(CTX_wm_area(C), region, runtime->amount, &panel) &&
                   BLI_rcti_isect_pt_v(&panel, event->xy) ?
               OPERATOR_FINISHED :
               OPERATOR_PASS_THROUGH;
  }
  if (close) {
    drawer_call_python(C, "MIXIE_CHAT_OT_close_scene_tab", runtime->cards[index].scene_name.c_str());
    WM_event_add_notifier(C, NC_SCENE, nullptr);
    ED_region_tag_redraw(region);
    return OPERATOR_FINISHED;
  }
  /* A press on a card: a release in place switches to it, a vertical drag
   * reorders it. Decided in the modal. */
  RNA_int_set(op->ptr, "start_y", event->xy[1]);
  RNA_int_set(op->ptr, "card", index);
  RNA_boolean_set(op->ptr, "dragged", false);
  runtime->drag_index = index;
  runtime->drag_target = -1;
  WM_event_add_modal_handler(C, op);
  return OPERATOR_RUNNING_MODAL;
}

static void drawer_drag_end(ScenesDrawerRuntime *runtime, ARegion *region)
{
  runtime->drag_index = -1;
  runtime->drag_target = -1;
  ED_region_tag_redraw(region);
}

static wmOperatorStatus drawer_click_modal(bContext *C, wmOperator *op, const wmEvent *event)
{
  ARegion *region = CTX_wm_region(C);
  ScenesDrawerRuntime *runtime = region ? static_cast<ScenesDrawerRuntime *>(region->regiondata) :
                                          nullptr;
  const int index = RNA_int_get(op->ptr, "card");
  if (runtime == nullptr || index < 0 || index >= int(runtime->cards.size())) {
    if (runtime) {
      drawer_drag_end(runtime, region);
    }
    return OPERATOR_CANCELLED;
  }
  switch (event->type) {
    case MOUSEMOVE: {
      const int dy = event->xy[1] - RNA_int_get(op->ptr, "start_y");
      if (!RNA_boolean_get(op->ptr, "dragged") &&
          std::abs(dy) <= VIEW3D_SCENES_DRAWER_CARD_DRAG_THRESHOLD)
      {
        break;
      }
      RNA_boolean_set(op->ptr, "dragged", true);
      const int target = drawer_drop_slot(runtime, event->xy[1]);
      if (target != runtime->drag_target) {
        runtime->drag_target = target;
        ED_region_tag_redraw(region);
      }
      break;
    }
    case LEFTMOUSE:
      if (event->val == KM_RELEASE) {
        const std::string scene_name = runtime->cards[index].scene_name;
        if (RNA_boolean_get(op->ptr, "dragged")) {
          const int target = drawer_drop_slot(runtime, event->xy[1]);
          if (target != index) {
            drawer_call_python(C, "MIXIE_CHAT_OT_reorder_scene_tab", scene_name.c_str(), target);
          }
        }
        else {
          drawer_call_python(C, "MIXIE_CHAT_OT_switch_scene_tab", scene_name.c_str());
        }
        drawer_drag_end(runtime, region);
        WM_event_add_notifier(C, NC_SCENE, nullptr);
        return OPERATOR_FINISHED;
      }
      break;
    case EVT_ESCKEY:
      drawer_drag_end(runtime, region);
      return OPERATOR_CANCELLED;
    default:
      break;
  }
  return OPERATOR_RUNNING_MODAL;
}

static void drawer_click_cancel(bContext *C, wmOperator * /*op*/)
{
  ARegion *region = CTX_wm_region(C);
  if (ScenesDrawerRuntime *runtime = region ? static_cast<ScenesDrawerRuntime *>(region->regiondata) : nullptr) {
    drawer_drag_end(runtime, region);
  }
}

void VIEW3D_OT_scenes_drawer_click(wmOperatorType *ot)
{
  ot->name = "Scenes Drawer Click";
  ot->idname = "VIEW3D_OT_scenes_drawer_click";
  ot->description = "Open, switch to, reorder or close a scene tab in the scenes drawer";
  ot->invoke = drawer_click_invoke;
  ot->modal = drawer_click_modal;
  ot->cancel = drawer_click_cancel;
  ot->poll = view3d_scenes_drawer_op_poll;
  ot->flag = 0;
  RNA_def_int(ot->srna, "start_y", 0, 0, 100000, "Start Y", "", 0, 100000);
  RNA_def_int(ot->srna, "card", -1, -1, 1024, "Card", "", -1, 1024);
  RNA_def_boolean(ot->srna, "dragged", false, "Dragged", "");
}

static wmOperatorStatus drawer_hover_invoke(bContext *C, wmOperator * /*op*/, const wmEvent *event)
{
  ARegion *region = CTX_wm_region(C);
  ScenesDrawerRuntime *runtime = region ? static_cast<ScenesDrawerRuntime *>(region->regiondata) :
                                          nullptr;
  if (runtime == nullptr) {
    return OPERATOR_PASS_THROUGH;
  }
  bool close = false;
  const int index = drawer_card_at(runtime, event->xy, &close);
  const bool over_new = runtime->new_visible && runtime->amount >= VIEW3D_SCENES_DRAWER_ACTIVE_AMOUNT &&
                        BLI_rcti_isect_pt_v(&runtime->new_rect, event->xy);
  if (index != runtime->hover || close != runtime->hover_close || over_new != runtime->hover_new) {
    runtime->hover = index;
    runtime->hover_close = close;
    runtime->hover_new = over_new;
    ED_region_tag_redraw(region);
  }
  return OPERATOR_PASS_THROUGH;
}

void VIEW3D_OT_scenes_drawer_hover(wmOperatorType *ot)
{
  ot->name = "Scenes Drawer Hover";
  ot->idname = "VIEW3D_OT_scenes_drawer_hover";
  ot->description = "Track the pointer over the scene cards";
  ot->invoke = drawer_hover_invoke;
  ot->poll = view3d_scenes_drawer_op_poll;
  ot->flag = OPTYPE_INTERNAL;
}

}  // namespace blender
