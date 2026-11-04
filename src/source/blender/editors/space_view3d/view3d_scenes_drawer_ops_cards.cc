/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Card operators of the sliding Scenes drawer: `click` turns a press
 * on a scene card (or "+ New scene", or a close glyph) into the Python
 * scene-tab operators (`mixie_chat.new_scene_tab` / `switch_scene_tab` /
 * `close_scene_tab` / `reorder_scene_tab`), a vertical drag reorders, and
 * `hover` tracks the pointer for the highlight. Slide, edge resize,
 * registration and the keymap are in `view3d_scenes_drawer_ops.cc`.
 */

#include <algorithm>
#include <cstdlib>
#include <string>

#include "BLI_rect.h"
#include "BLI_time.h"
#include "MEM_guardedalloc.h"

#include "BKE_context.hh"

#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"

#include "RNA_access.hh"
#include "UI_interface_c.hh"
#include "RNA_define.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_scenes_drawer.hh"
#include "view3d_scenes_drawer_motion.hh"

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

/** Use the full card pitch, not clipped hit rectangles, at the scroll edges. */
int view3d_scenes_drawer_drop_slot(const ScenesDrawerRuntime *runtime, const int y)
{
  const float scale = UI_SCALE_FAC;
  const float first_center = runtime->list_rect.ymax + runtime->scroll -
                             0.5f * VIEW3D_SCENES_DRAWER_CARD_H * scale;
  const float pitch = (VIEW3D_SCENES_DRAWER_CARD_H + VIEW3D_SCENES_DRAWER_CARD_GAP) * scale;
  return std::clamp(int(std::ceil((first_center - y) / pitch)), 0, int(runtime->cards.size()));
}

struct ScenesCardDrag {
  wmTimer *timer = nullptr;
  int x = 0;
  int y = 0;
  double last_tick = 0.0;
  double released_at = 0.0;
  bool cancelled = false;
  int settle_index = 0;
};

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
  if (view3d_scenes_drawer_selection_click(C, region, runtime, event)) {
    return OPERATOR_FINISHED;
  }
  bool close = false;
  const int index = drawer_card_at(runtime, event->xy, &close);
  if (index < 0) {
    runtime->selected_uids.clear();
    ED_region_tag_redraw(region);
    rcti panel;
    /* A press on the panel bed is consumed so the viewport behind never
     * orbits; outside the panel it passes through. */
    return view3d_scenes_drawer_panel_rect_for(CTX_wm_area(C), region, runtime->amount, &panel) &&
                   BLI_rcti_isect_pt_v(&panel, event->xy) ?
               OPERATOR_FINISHED :
               OPERATOR_PASS_THROUGH;
  }
  if (close) {
    view3d_scenes_drawer_delete_card(C, runtime->cards[index].scene_uid);
    WM_event_add_notifier(C, NC_SCENE, nullptr);
    ED_region_tag_redraw(region);
    return OPERATOR_FINISHED;
  }
  /* A press on a card: a release in place switches to it, a vertical drag
   * reorders it. Decided in the modal. */
  RNA_int_set(op->ptr, "start_y", event->xy[1]);
  RNA_int_set(op->ptr, "card", index);
  /* The card is remembered by ID session_uid, not by index or name: the list
   * is rebuilt from the tab mirror on every draw, a tab created, closed or
   * reordered mid-drag (a script, the refresh tick) would shift the indices,
   * and a rename or a same-named linked scene would redirect a name. */
  RNA_string_set(op->ptr, "scene_uid", runtime->cards[index].scene_uid.c_str());
  RNA_boolean_set(op->ptr, "dragged", false);
  runtime->drag_index = index;
  runtime->drag_target = -1;
  runtime->drag_scene = runtime->cards[index].scene_uid;
  runtime->drag_offset_y = runtime->cards[index].rect.ymax - event->xy[1];
  auto *drag = MEM_new<ScenesCardDrag>(__func__);
  drag->x = event->xy[0];
  drag->y = event->xy[1];
  op->customdata = drag;
  WM_event_add_modal_handler(C, op);
  return OPERATOR_RUNNING_MODAL;
}

static void drawer_drag_end(bContext *C, wmOperator *op, ScenesDrawerRuntime *runtime,
                            ARegion *region)
{
  auto *drag = static_cast<ScenesCardDrag *>(op->customdata);
  if (drag) {
    if (drag->timer) {
      WM_event_timer_remove(CTX_wm_manager(C), CTX_wm_window(C), drag->timer);
      WM_cursor_modal_restore(CTX_wm_window(C));
    }
    MEM_delete(drag);
    op->customdata = nullptr;
  }
  if (runtime) {
    runtime->drag_index = -1;
    runtime->drag_target = -1;
    runtime->drag_scene.clear();
    runtime->drag_settling = false;
    runtime->card_rows.clear();
    runtime->drag_rect = runtime->drop_rect = {};
    ED_region_tag_redraw(region);
  }
}

/* The current index of the card the drag started on, or -1 when its tab is
 * gone (a bounds check alone would act on whichever card took its slot). */
static int drawer_card_index_of(const ScenesDrawerRuntime *runtime, const char *scene_uid)
{
  for (int i = 0; i < int(runtime->cards.size()); i++) {
    if (runtime->cards[i].scene_uid == scene_uid) {
      return i;
    }
  }
  return -1;
}

static void drawer_settle_begin(ScenesDrawerRuntime *runtime, ScenesCardDrag *drag,
                                const int index, const bool cancelled)
{
  drag->released_at = BLI_time_now_seconds();
  drag->last_tick = drag->released_at;
  drag->cancelled = cancelled;
  drag->settle_index = index;
  runtime->drag_settling = true;
  runtime->drag_preview_top = BLI_rcti_size_y(&runtime->drag_rect) > 0 ?
                                  runtime->drag_rect.ymax : runtime->drag_y + runtime->drag_offset_y;
  runtime->drop_rect = {};
}

static wmOperatorStatus drawer_click_modal(bContext *C, wmOperator *op, const wmEvent *event)
{
  ARegion *region = CTX_wm_region(C);
  ScenesDrawerRuntime *runtime = region ? static_cast<ScenesDrawerRuntime *>(region->regiondata) :
                                          nullptr;
  char scene_prop[MAX_ID_NAME];
  RNA_string_get(op->ptr, "scene_uid", scene_prop);
  const int index = runtime ? drawer_card_index_of(runtime, scene_prop) : -1;
  if (runtime == nullptr || index < 0 || !view3d_scenes_drawer_host_active(C) ||
      view3d_scenes_drawer_amount(C) < VIEW3D_SCENES_DRAWER_ACTIVE_AMOUNT) {
    drawer_drag_end(C, op, runtime, region);
    return OPERATOR_CANCELLED;
  }
  auto *drag = static_cast<ScenesCardDrag *>(op->customdata);
  /* Finish the short landing ease before releasing the modal's timer. */
  if (runtime->drag_settling) {
    if (ISMOUSE_BUTTON(event->type) && event->val == KM_PRESS) {
      /* A new press lands the card at once and is handled by whoever it is
       * for (a second drag, a header pill): the ease never swallows input. */
      const bool cancelled = drag->cancelled;
      drawer_drag_end(C, op, runtime, region);
      return (cancelled ? OPERATOR_CANCELLED : OPERATOR_FINISHED) | OPERATOR_PASS_THROUGH;
    }
    if (event->type == TIMER && event->customdata == drag->timer) {
      const double now = BLI_time_now_seconds();
      const float target_top = runtime->list_rect.ymax + runtime->scroll -
                               drag->settle_index * (VIEW3D_SCENES_DRAWER_CARD_H +
                                                     VIEW3D_SCENES_DRAWER_CARD_GAP) * UI_SCALE_FAC;
      runtime->drag_preview_top = view3d_scenes_drawer::follow_position(
          runtime->drag_preview_top, target_top, now - drag->last_tick);
      drag->last_tick = now;
      ED_region_tag_redraw(region);
      if (now - drag->released_at >= view3d_scenes_drawer::CARD_SETTLE_SECONDS) {
        const bool cancelled = drag->cancelled;
        drawer_drag_end(C, op, runtime, region);
        return cancelled ? OPERATOR_CANCELLED : OPERATOR_FINISHED;
      }
    }
    return OPERATOR_RUNNING_MODAL;
  }
  /* Keep the drag highlight on the right card if the list shifted. */
  runtime->drag_index = index;
  switch (event->type) {
    case MOUSEMOVE: {
      drag->x = event->xy[0];
      drag->y = event->xy[1];
      const int dy = event->xy[1] - RNA_int_get(op->ptr, "start_y");
      if (!RNA_boolean_get(op->ptr, "dragged") &&
          std::abs(dy) <= VIEW3D_SCENES_DRAWER_CARD_DRAG_THRESHOLD * UI_SCALE_FAC)
      {
        break;
      }
      RNA_boolean_set(op->ptr, "dragged", true);
      if (drag->timer == nullptr) {
        drag->timer = WM_event_timer_add(CTX_wm_manager(C), CTX_wm_window(C), TIMER, 1.0 / 60.0);
        WM_cursor_modal_set(CTX_wm_window(C), WM_CURSOR_HAND);
        drag->last_tick = BLI_time_now_seconds();
        runtime->cards_draw_time = drag->last_tick;
      }
      runtime->drag_y = drag->y;
      runtime->drag_target = view3d_scenes_drawer_drop_slot(runtime, drag->y);
      ED_region_tag_redraw(region);
      break;
    }
    case TIMER: {
      if (event->customdata != drag->timer || drag->timer == nullptr) {
        break;
      }
      const double now = BLI_time_now_seconds();
      const float dt = float(std::clamp(now - drag->last_tick, 0.0, 0.05));
      drag->last_tick = now;
      ED_region_tag_redraw(region); /* Siblings keep easing even with a stationary pointer. */
      const rcti &list = runtime->list_rect;
      if (drag->x < list.xmin || drag->x > list.xmax) {
        break;
      }
      const float band = 28.0f * UI_SCALE_FAC;
      float speed = 0.0f;
      if (drag->y > list.ymax - band) {
        speed = -std::clamp((drag->y - (list.ymax - band)) / band, 0.0f, 1.0f);
      }
      else if (drag->y < list.ymin + band) {
        speed = std::clamp((list.ymin + band - drag->y) / band, 0.0f, 1.0f);
      }
      runtime->scroll = std::clamp(runtime->scroll + speed * 420.0f * dt * UI_SCALE_FAC,
                                   0.0f, runtime->scroll_max);
      runtime->drag_target = view3d_scenes_drawer_drop_slot(runtime, drag->y);
      ED_region_tag_redraw(region);
      break;
    }
    case LEFTMOUSE:
      if (event->val == KM_RELEASE) {
        rcti panel;
        if (!view3d_scenes_drawer_panel_rect_for(CTX_wm_area(C), region, runtime->amount, &panel) ||
            !BLI_rcti_isect_pt_v(&panel, event->xy)) {
          if (drag->timer) {
            drawer_settle_begin(runtime, drag, index, true);
            return OPERATOR_RUNNING_MODAL;
          }
          drawer_drag_end(C, op, runtime, region);
          return OPERATOR_CANCELLED;
        }
        const std::string scene_name = runtime->cards[index].scene_name;
        if (RNA_boolean_get(op->ptr, "dragged")) {
          /* `reorder_scene_tab` removes the card first and inserts at the
           * index: a slot past the dragged card shifts down by one. */
          const int slot = view3d_scenes_drawer_drop_slot(runtime, event->xy[1]);
          const int target = slot > index ? slot - 1 : slot;
          const bool moved = target == index || drawer_call_python(
              C, "MIXIE_CHAT_OT_reorder_scene_tab", scene_name.c_str(), target);
          drawer_settle_begin(runtime, drag, moved ? target : index, !moved);
          WM_event_add_notifier(C, NC_SCENE, nullptr);
          return OPERATOR_RUNNING_MODAL;
        }
        else {
          runtime->selected_uids.clear();
          runtime->selection_anchor = runtime->cards[index].scene_uid;
          drawer_call_python(C, "MIXIE_CHAT_OT_switch_scene_tab", scene_name.c_str());
        }
        drawer_drag_end(C, op, runtime, region);
        WM_event_add_notifier(C, NC_SCENE, nullptr);
        return OPERATOR_FINISHED;
      }
      break;
    case RIGHTMOUSE:
    case EVT_ESCKEY:
      if (drag->timer) {
        drawer_settle_begin(runtime, drag, index, true);
        return OPERATOR_RUNNING_MODAL;
      }
      drawer_drag_end(C, op, runtime, region);
      return OPERATOR_CANCELLED;
    default:
      break;
  }
  return OPERATOR_RUNNING_MODAL;
}

static void drawer_click_cancel(bContext *C, wmOperator *op)
{
  ARegion *region = CTX_wm_region(C);
  auto *runtime = region ? static_cast<ScenesDrawerRuntime *>(region->regiondata) : nullptr;
  drawer_drag_end(C, op, runtime, region);
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
  RNA_def_string(ot->srna, "scene_uid", nullptr, MAX_ID_NAME, "Scene",
                 "ID session_uid of the tab the press landed on");
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
  const bool over_delete = !runtime->selected_uids.empty() &&
                           BLI_rcti_isect_pt_v(&runtime->bulk_delete_rect, event->xy);
  if (index != runtime->hover || close != runtime->hover_close || over_new != runtime->hover_new ||
      over_delete != runtime->hover_delete) {
    runtime->hover = index;
    runtime->hover_close = close;
    runtime->hover_new = over_new;
    runtime->hover_delete = over_delete;
    ED_region_tag_redraw(region);
  }
  return OPERATOR_PASS_THROUGH;
}

/* --- Scroll ------------------------------------------------------------ */

static wmOperatorStatus drawer_scroll_exec(bContext *C, wmOperator *op)
{
  ARegion *region = CTX_wm_region(C);
  ScenesDrawerRuntime *runtime = region ? static_cast<ScenesDrawerRuntime *>(region->regiondata) :
                                          nullptr;
  if (runtime == nullptr || runtime->scroll_max <= 0.0f) {
    /* Nothing to scroll: the wheel belongs to whatever is behind. */
    return OPERATOR_PASS_THROUGH;
  }
  const float step = VIEW3D_SCENES_DRAWER_SCROLL_STEP * UI_SCALE_FAC;
  runtime->scroll = std::clamp(
      runtime->scroll + float(RNA_int_get(op->ptr, "delta")) * step, 0.0f, runtime->scroll_max);
  ED_region_tag_redraw(region);
  return OPERATOR_FINISHED;
}

static wmOperatorStatus drawer_scroll_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  if (event->type != MOUSEPAN) {
    return drawer_scroll_exec(C, op);
  }
  /* Trackpad: pixel for pixel with the gesture. `WM_event_absolute_delta_y`
   * already honours the natural-scrolling preference (see the agent panel). */
  ARegion *region = CTX_wm_region(C);
  ScenesDrawerRuntime *runtime = region ? static_cast<ScenesDrawerRuntime *>(region->regiondata) :
                                          nullptr;
  if (runtime == nullptr || runtime->scroll_max <= 0.0f) {
    return OPERATOR_PASS_THROUGH;
  }
  runtime->scroll = std::clamp(
      runtime->scroll + float(WM_event_absolute_delta_y(event)), 0.0f, runtime->scroll_max);
  ED_region_tag_redraw(region);
  return OPERATOR_FINISHED;
}

void VIEW3D_OT_scenes_drawer_scroll(wmOperatorType *ot)
{
  ot->name = "Scroll Scenes Drawer";
  ot->idname = "VIEW3D_OT_scenes_drawer_scroll";
  ot->description = "Scroll the scene tab cards";
  ot->invoke = drawer_scroll_invoke;
  ot->exec = drawer_scroll_exec;
  ot->poll = view3d_scenes_drawer_op_poll;
  ot->flag = OPTYPE_INTERNAL;
  RNA_def_int(ot->srna, "delta", 1, -100, 100, "Delta", "Wheel notches, positive scrolls down", -10, 10);
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
