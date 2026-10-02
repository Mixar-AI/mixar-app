/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Operators and keymap for the sliding Scenes drawer: the slide
 * (update / reveal / toggle / set) and the resize sash on the panel's right
 * edge. The card operators (`click`, `hover`) are in
 * `view3d_scenes_drawer_ops_cards.cc`; registration and the keymap for all
 * of them are here. The region's width follows every amount write
 * (`view3d_scenes_drawer_layout_sync`), which is how the viewport is pushed.
 */

#include <algorithm>
#include <cmath>
#include <cstdlib>

#include "BLI_listbase_iterator.hh"
#include "BLI_rect.h"
#include "BLI_string.h"

#include "BKE_context.hh"
#include "UI_interface_c.hh"
#include "DNA_view3d_types.h"
#include "BKE_main.hh"
#include "BKE_lib_id.hh"
#include "BKE_screen.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "UI_interface.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_scenes_drawer.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

static void drawer_tag_redraw(bContext *C)
{
  /* The host, not the context area: Ctrl+` over a secondary viewport slides
   * the main one's drawer. */
  ScrArea *area = view3d_scenes_drawer_area_find(C);
  if (area == nullptr) {
    return;
  }
  if (ARegion *region = view3d_scenes_drawer_region_find(area)) {
    ED_region_tag_redraw(region);
  }
  if (ARegion *window = BKE_area_find_region_type(area, RGN_TYPE_WINDOW)) {
    ED_region_tag_redraw_editor_overlays(window);
  }
  /* The transform pill (TOOLS region) is re-laid out against the pushed
   * viewport; make sure it repaints on the same frame. */
  if (ARegion *tools = BKE_area_find_region_type(area, RGN_TYPE_TOOLS)) {
    ED_region_tag_redraw(tools);
  }
}

static ScenesDrawerRuntime *drawer_runtime(const bContext *C)
{
  return view3d_scenes_drawer_runtime_ensure(CTX_wm_manager(C),
                                             view3d_scenes_drawer_region_from_context(C));
}

bool view3d_scenes_drawer_op_poll(bContext *C)
{
  return view3d_scenes_drawer_area_find(C) != nullptr;
}

/* --- Slide ------------------------------------------------------------ */

/* One tick of the ease, driven by the Python timer while amount != target
 * (`scene_tabs_props._drawer_tick`, 60 Hz): writes the eased amount into RNA,
 * which sizes the region and tags the area layout — the viewport shifts on
 * the next draw. */
static wmOperatorStatus drawer_update_exec(bContext *C, wmOperator * /*op*/)
{
  const ScenesDrawerRuntime *runtime = drawer_runtime(C);
  const float target = view3d_scenes_drawer_target(C) != 0 ? 1.0f : 0.0f;
  if ((runtime == nullptr || runtime->slide_started_at <= 0.0) &&
      std::fabs(view3d_scenes_drawer_amount(C) - target) >= 0.002f)
  {
    view3d_scenes_drawer_slide_begin(C);
  }

  const float display = view3d_scenes_drawer_display_amount(C);
  if (std::fabs(display - target) < 0.002f) {
    if (view3d_scenes_drawer_amount(C) != target) {
      view3d_scenes_drawer_amount_set(C, target);
      drawer_tag_redraw(C);
    }
    view3d_scenes_drawer_slide_stop(C);
    return OPERATOR_FINISHED;
  }

  view3d_scenes_drawer_amount_set(C, display);
  drawer_tag_redraw(C);
  return OPERATOR_FINISHED;
}

static void VIEW3D_OT_scenes_drawer_update(wmOperatorType *ot)
{
  ot->name = "Update Scenes Drawer";
  ot->idname = "VIEW3D_OT_scenes_drawer_update";
  ot->description = "Advance the scenes drawer one step towards its target";
  ot->exec = drawer_update_exec;
  ot->poll = view3d_scenes_drawer_op_poll;
  ot->flag = 0;
}

static wmOperatorStatus drawer_reveal_exec(bContext *C, wmOperator * /*op*/)
{
  if (view3d_scenes_drawer_target(C) == 0) {
    view3d_scenes_drawer_slide_begin(C);
    view3d_scenes_drawer_target_set(C, 1);
    drawer_tag_redraw(C);
  }
  return OPERATOR_FINISHED;
}

static void VIEW3D_OT_scenes_drawer_reveal(wmOperatorType *ot)
{
  ot->name = "Reveal Scenes Drawer";
  ot->idname = "VIEW3D_OT_scenes_drawer_reveal";
  ot->description = "Slide out the scene tabs without toggling an open drawer";
  ot->exec = drawer_reveal_exec;
  ot->poll = view3d_scenes_drawer_op_poll;
  ot->flag = 0;
}

static wmOperatorStatus drawer_toggle_exec(bContext *C, wmOperator * /*op*/)
{
  view3d_scenes_drawer_slide_begin(C);
  view3d_scenes_drawer_target_set(C, view3d_scenes_drawer_target(C) != 0 ? 0 : 1);
  drawer_tag_redraw(C);
  return OPERATOR_FINISHED;
}

static void VIEW3D_OT_scenes_drawer_toggle(wmOperatorType *ot)
{
  ot->name = "Toggle Scenes Drawer";
  ot->idname = "VIEW3D_OT_scenes_drawer_toggle";
  ot->description = "Slide the scene tabs drawer in or out (Ctrl+`)";
  ot->exec = drawer_toggle_exec;
  ot->poll = view3d_scenes_drawer_op_poll;
  ot->flag = 0;
}

static wmOperatorStatus drawer_set_exec(bContext *C, wmOperator *op)
{
  view3d_scenes_drawer_slide_stop(C);
  view3d_scenes_drawer_amount_set(C, RNA_float_get(op->ptr, "amount"));
  const float target = RNA_float_get(op->ptr, "target");
  if (target >= 0.0f) {
    view3d_scenes_drawer_target_set(C, target > 0.5f ? 1 : 0);
  }
  drawer_tag_redraw(C);
  return OPERATOR_FINISHED;
}

static void VIEW3D_OT_scenes_drawer_set(wmOperatorType *ot)
{
  ot->name = "Set Scenes Drawer";
  ot->idname = "VIEW3D_OT_scenes_drawer_set";
  ot->description = "Place the scenes drawer at an exact slide amount (scripting, QA)";
  ot->exec = drawer_set_exec;
  ot->poll = view3d_scenes_drawer_op_poll;
  ot->flag = 0;
  RNA_def_float(ot->srna, "amount", 0.0f, 0.0f, 1.0f, "Amount", "0 shut, 1 open", 0.0f, 1.0f);
  RNA_def_float(ot->srna, "target", -1.0f, -1.0f, 1.0f, "Target",
                "Intent to settle on afterwards; negative leaves it alone", -1.0f, 1.0f);
}

/* --- Thumbnails -------------------------------------------------------- */

static void thumb_size(int *r_w, int *r_h)
{
  const float scale = UI_SCALE_FAC;
  *r_w = int(VIEW3D_SCENES_DRAWER_THUMB_W * scale) + 1;
  *r_h = int(VIEW3D_SCENES_DRAWER_THUMB_H * scale) + 1;
}

/* The drawer tick: refresh the SHOWN tab's card from the host viewport's last
 * frame (throttled, only after its depsgraph changed) and drop snapshots of
 * scenes that are gone. Never renders anything: see `_thumbs.cc`. */
static wmOperatorStatus drawer_thumbs_exec(bContext *C, wmOperator * /*op*/)
{
  ScrArea *area = view3d_scenes_drawer_area_find(C);
  ARegion *region = view3d_scenes_drawer_region_find(area);
  ScenesDrawerRuntime *runtime = region ? static_cast<ScenesDrawerRuntime *>(region->regiondata) :
                                          nullptr;
  if (area == nullptr || region == nullptr || runtime == nullptr || (region->flag & RGN_FLAG_HIDDEN) ||
      runtime->amount < VIEW3D_SCENES_DRAWER_ACTIVE_AMOUNT ||
      !view3d_scenes_drawer_snapshots_enabled())
  {
    return OPERATOR_CANCELLED;
  }
  view3d_scenes_drawer_snapshot_evict(CTX_data_main(C));
  ARegion *host = BKE_area_find_region_type(area, RGN_TYPE_WINDOW);
  int thumb_w, thumb_h;
  thumb_size(&thumb_w, &thumb_h);
  if (view3d_scenes_drawer_snapshot_capture(
          C, host, CTX_data_scene(C), thumb_w, thumb_h, /*force=*/false))
  {
    ED_region_tag_redraw(region);
  }
  return OPERATOR_FINISHED;
}

static void VIEW3D_OT_scenes_drawer_thumbs(wmOperatorType *ot)
{
  ot->name = "Refresh Scenes Drawer Thumbnails";
  ot->idname = "VIEW3D_OT_scenes_drawer_thumbs";
  ot->description = "Refresh the shown scene tab's card from the viewport (timer-driven)";
  ot->exec = drawer_thumbs_exec;
  ot->poll = view3d_scenes_drawer_op_poll;
  ot->flag = OPTYPE_INTERNAL;
}

/* Called by the Python tab switch BEFORE the windows move to another scene:
 * the leaving tab's last drawn frame becomes its card. Works with the drawer
 * shut too, so the cards have pictures when it opens. */
static wmOperatorStatus drawer_snapshot_exec(bContext *C, wmOperator * /*op*/)
{
  if (!view3d_scenes_drawer_snapshots_enabled()) {
    return OPERATOR_CANCELLED;
  }
  ScrArea *area = view3d_scenes_drawer_area_find(C);
  ARegion *host = area ? BKE_area_find_region_type(area, RGN_TYPE_WINDOW) : nullptr;
  if (host == nullptr) {
    return OPERATOR_CANCELLED;
  }
  int thumb_w, thumb_h;
  thumb_size(&thumb_w, &thumb_h);
  if (!view3d_scenes_drawer_snapshot_capture(
          C, host, CTX_data_scene(C), thumb_w, thumb_h, /*force=*/true))
  {
    return OPERATOR_CANCELLED;
  }
  if (ARegion *region = view3d_scenes_drawer_region_find(area)) {
    ED_region_tag_redraw(region);
  }
  return OPERATOR_FINISHED;
}

static void VIEW3D_OT_scenes_drawer_snapshot(wmOperatorType *ot)
{
  ot->name = "Snapshot Scene Tab";
  ot->idname = "VIEW3D_OT_scenes_drawer_snapshot";
  ot->description = "Keep the viewport's last frame as the shown scene tab's card picture";
  ot->exec = drawer_snapshot_exec;
  ot->poll = view3d_scenes_drawer_op_poll;
  ot->flag = OPTYPE_INTERNAL;
}

/* --- Edge resize ------------------------------------------------------ */

bool view3d_scenes_drawer_edge_hit(const bContext *C, const int xy[2])
{
  return view3d_scenes_drawer_resize_contains_xy(CTX_wm_area(C), CTX_wm_region(C), xy);
}

static wmOperatorStatus drawer_edge_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  if (!view3d_scenes_drawer_edge_hit(C, event->xy)) {
    return OPERATOR_PASS_THROUGH;
  }
  RNA_int_set(op->ptr, "start_xy", event->xy[0]);
  RNA_float_set(op->ptr, "start_width", view3d_scenes_drawer_width(CTX_wm_manager(C)));
  RNA_boolean_set(op->ptr, "dragged", false);
  WM_cursor_modal_set(CTX_wm_window(C), WM_CURSOR_X_MOVE);
  WM_event_add_modal_handler(C, op);
  return OPERATOR_RUNNING_MODAL;
}

static wmOperatorStatus drawer_edge_modal(bContext *C, wmOperator *op, const wmEvent *event)
{
  switch (event->type) {
    case MOUSEMOVE: {
      const int dx = event->xy[0] - RNA_int_get(op->ptr, "start_xy");
      if (!RNA_boolean_get(op->ptr, "dragged") &&
          std::abs(dx) <= VIEW3D_SCENES_DRAWER_DRAG_THRESHOLD)
      {
        break;
      }
      RNA_boolean_set(op->ptr, "dragged", true);
      /* Dragging RIGHT widens. The width alone changes; the drawer stays open
       * and the region (and the viewport beside it) follow the new width. */
      const float area_width = float(BLI_rcti_size_x(&CTX_wm_area(C)->totrct) + 1) /
                               UI_SCALE_FAC;
      const float max_width = std::max(area_width - float(VIEW3D_SCENES_DRAWER_MIN_WIDTH),
                                       float(VIEW3D_SCENES_DRAWER_MIN_WIDTH));
      const float width = std::clamp(
          RNA_float_get(op->ptr, "start_width") + float(dx) / UI_SCALE_FAC,
          float(VIEW3D_SCENES_DRAWER_MIN_WIDTH),
          max_width);
      view3d_scenes_drawer_width_set(C, width);
      drawer_tag_redraw(C);
      break;
    }
    case LEFTMOUSE:
      if (event->val == KM_RELEASE) {
        WM_cursor_modal_restore(CTX_wm_window(C));
        return OPERATOR_FINISHED;
      }
      break;
    case EVT_ESCKEY:
      view3d_scenes_drawer_width_set(C, RNA_float_get(op->ptr, "start_width"));
      drawer_tag_redraw(C);
      WM_cursor_modal_restore(CTX_wm_window(C));
      return OPERATOR_FINISHED;
    default:
      break;
  }
  return OPERATOR_RUNNING_MODAL;
}

static void drawer_edge_cancel(bContext *C, wmOperator * /*op*/)
{
  if (wmWindow *win = CTX_wm_window(C)) {
    WM_cursor_modal_restore(win);
  }
}

static void VIEW3D_OT_scenes_drawer_edge(wmOperatorType *ot)
{
  ot->name = "Scenes Drawer Edge";
  ot->idname = "VIEW3D_OT_scenes_drawer_edge";
  ot->description = "Drag the panel's right edge to resize the scenes drawer";
  ot->invoke = drawer_edge_invoke;
  ot->modal = drawer_edge_modal;
  ot->cancel = drawer_edge_cancel;
  ot->poll = view3d_scenes_drawer_op_poll;
  ot->flag = 0;
  RNA_def_int(ot->srna, "start_xy", 0, 0, 100000, "Start X", "", 0, 100000);
  RNA_def_float(ot->srna, "start_width", 300.0f, 1.0f, 100000.0f, "Start Width", "", 1.0f, 100000.0f);
  RNA_def_boolean(ot->srna, "dragged", false, "Dragged", "");
}

void view3d_scenes_drawer_operatortypes()
{
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_update);
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_reveal);
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_toggle);
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_set);
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_edge);
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_selection);
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_click);
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_hover);
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_scroll);
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_thumbs);
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_snapshot);
}

void view3d_scenes_drawer_keymap(wmKeyConfig *keyconf)
{
  wmKeyMap *grip = WM_keymap_ensure(
      keyconf, "Scenes Drawer Grip", SPACE_VIEW3D, VIEW3D_SCENES_DRAWER_REGION_TYPE);

  KeyMapItem_Params press{};
  press.type = LEFTMOUSE;
  press.value = KM_PRESS;
  WM_keymap_add_item(grip, "VIEW3D_OT_scenes_drawer_edge", &press);
  press.modifier = KM_ANY;
  WM_keymap_add_item(grip, "VIEW3D_OT_scenes_drawer_click", &press);
  press.value = KM_DBL_CLICK;
  WM_keymap_add_item(grip, "VIEW3D_OT_scenes_drawer_click", &press);
  for (const int modifier : {KM_CTRL, KM_OSKEY}) {
    KeyMapItem_Params select{};
    select.type = EVT_AKEY;
    select.value = KM_PRESS;
    select.modifier = modifier;
    WM_keymap_add_item(grip, "VIEW3D_OT_scenes_drawer_selection", &select);
  }
  for (const int type : {EVT_DELKEY, EVT_BACKSPACEKEY, EVT_ESCKEY}) {
    KeyMapItem_Params select{};
    select.type = type;
    select.value = KM_PRESS;
    WM_keymap_add_item(grip, "VIEW3D_OT_scenes_drawer_selection", &select);
  }
  KeyMapItem_Params move{};
  move.type = MOUSEMOVE;
  move.value = KM_ANY;
  WM_keymap_add_item(grip, "VIEW3D_OT_scenes_drawer_hover", &move);
  /* Wheel notches and the trackpad pan scroll the cards; the operator passes
   * the event through when nothing overflows. */
  KeyMapItem_Params wheel_down{};
  wheel_down.type = WHEELDOWNMOUSE;
  wheel_down.value = KM_PRESS;
  wmKeyMapItem *kmi = WM_keymap_add_item(grip, "VIEW3D_OT_scenes_drawer_scroll", &wheel_down);
  RNA_int_set(kmi->ptr, "delta", 1);
  KeyMapItem_Params wheel_up{};
  wheel_up.type = WHEELUPMOUSE;
  wheel_up.value = KM_PRESS;
  kmi = WM_keymap_add_item(grip, "VIEW3D_OT_scenes_drawer_scroll", &wheel_up);
  RNA_int_set(kmi->ptr, "delta", -1);
  KeyMapItem_Params pan{};
  pan.type = MOUSEPAN;
  pan.value = KM_ANY;
  WM_keymap_add_item(grip, "VIEW3D_OT_scenes_drawer_scroll", &pan);

  /* Ctrl+` pairs with the moodboard's ` on the right edge. */
  KeyMapItem_Params key{};
  key.type = EVT_ACCENTGRAVEKEY;
  key.value = KM_PRESS;
  key.modifier = KM_CTRL;
  wmKeyMap *toggle = WM_keymap_ensure(keyconf, "Scenes Drawer", SPACE_VIEW3D, RGN_TYPE_WINDOW);
  WM_keymap_add_item(toggle, "VIEW3D_OT_scenes_drawer_toggle", &key);
  wmKeyMap *window = WM_keymap_ensure(keyconf, "Window", SPACE_EMPTY, RGN_TYPE_WINDOW);
  WM_keymap_add_item(window, "VIEW3D_OT_scenes_drawer_toggle", &key);
}

}  // namespace blender
