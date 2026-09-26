/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Operators and keymap for the Zen Mode sliding Scenes drawer. Slide, grip
 * and set mirror the moodboard drawer. The card operators (`click`, `hover`)
 * are in `view3d_scenes_drawer_ops_cards.cc`; registration and the keymap
 * for all of them are here.
 */

#include <algorithm>
#include <cmath>

#include "BLI_listbase_iterator.hh"
#include "BLI_rect.h"
#include "BLI_string.h"

#include "BKE_context.hh"
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
  ScrArea *area = CTX_wm_area(C);
  if (area == nullptr || area->spacetype != SPACE_VIEW3D) {
    area = view3d_scenes_drawer_area_find(C);
  }
  if (area == nullptr) {
    return;
  }
  if (ARegion *region = view3d_scenes_drawer_region_find(area)) {
    ED_region_tag_redraw(region);
  }
  if (ARegion *window = BKE_area_find_region_type(area, RGN_TYPE_WINDOW)) {
    ED_region_tag_redraw_editor_overlays(window);
  }
  /* The transform pill steps aside while the drawer is open (Python skips
   * its draw); it lives in the TOOLS region, which must repaint too. */
  if (ARegion *tools = BKE_area_find_region_type(area, RGN_TYPE_TOOLS)) {
    ED_region_tag_redraw(tools);
  }
}

static ScenesDrawerRuntime *drawer_runtime(const bContext *C)
{
  ARegion *region = view3d_scenes_drawer_region_from_context(C);
  return region != nullptr ? static_cast<ScenesDrawerRuntime *>(region->regiondata) : nullptr;
}

bool view3d_scenes_drawer_op_poll(bContext *C)
{
  return view3d_scenes_drawer_area_find(C) != nullptr;
}

/* --- Slide ------------------------------------------------------------ */

static wmOperatorStatus drawer_update_exec(bContext *C, wmOperator * /*op*/)
{
  const ScenesDrawerRuntime *runtime = drawer_runtime(C);
  if (runtime != nullptr && runtime->slide_held) {
    return OPERATOR_FINISHED;
  }

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

/* --- Grip ------------------------------------------------------------- */

bool view3d_scenes_drawer_grip_hit(const bContext *C, const int xy[2])
{
  return view3d_scenes_drawer_resize_contains_xy(CTX_wm_area(C), CTX_wm_region(C), xy);
}

static wmOperatorStatus drawer_grip_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  if (!view3d_scenes_drawer_grip_hit(C, event->xy)) {
    return OPERATOR_PASS_THROUGH;
  }

  RNA_int_set(op->ptr, "start_xy", event->xy[0]);
  RNA_float_set(op->ptr, "start_amount", view3d_scenes_drawer_display_amount(C));
  RNA_int_set(op->ptr, "start_target", view3d_scenes_drawer_target(C));
  RNA_float_set(op->ptr, "start_width", view3d_scenes_drawer_width(CTX_wm_manager(C)));
  const ARegion *region = CTX_wm_region(C);
  const float inset = (VIEW3D_SCENES_DRAWER_GRIP_WIDTH + VIEW3D_SCENES_DRAWER_PAD) * UI_SCALE_FAC;
  RNA_float_set(op->ptr, "start_travel",
                view3d_scenes_drawer_display_amount(C) * (region->winx - 1 - inset));
  RNA_boolean_set(op->ptr, "dragged", false);
  RNA_boolean_set(op->ptr, "edge_resize",
                  !view3d_scenes_drawer_grip_contains_xy(CTX_wm_area(C), region, event->xy));

  WM_cursor_modal_set(CTX_wm_window(C), WM_CURSOR_X_MOVE);
  WM_event_add_modal_handler(C, op);
  return OPERATOR_RUNNING_MODAL;
}

static wmOperatorStatus drawer_grip_modal(bContext *C, wmOperator *op, const wmEvent *event)
{
  switch (event->type) {
    case MOUSEMOVE: {
      const int start_xy = RNA_int_get(op->ptr, "start_xy");
      const int dx = event->xy[0] - start_xy;

      if (!RNA_boolean_get(op->ptr, "dragged") &&
          std::abs(dx) <= VIEW3D_SCENES_DRAWER_DRAG_THRESHOLD)
      {
        break;
      }
      RNA_boolean_set(op->ptr, "dragged", true);
      view3d_scenes_drawer_slide_hold(C);

      /* Left edge: dragging RIGHT opens / widens, dragging left shuts. */
      const float inset = (VIEW3D_SCENES_DRAWER_GRIP_WIDTH + VIEW3D_SCENES_DRAWER_PAD) *
                          UI_SCALE_FAC;
      const float max_width = BLI_rcti_size_x(&CTX_wm_area(C)->totrct) + 1;
      const float min_width = std::min(float(VIEW3D_SCENES_DRAWER_MIN_WIDTH) * UI_SCALE_FAC,
                                       max_width);
      const float min_travel = RNA_boolean_get(op->ptr, "edge_resize") ?
                                   std::max(min_width - 1 - inset, 0.0f) :
                                   0.0f;
      const float travel = std::clamp(RNA_float_get(op->ptr, "start_travel") + dx,
                                      min_travel,
                                      std::max(max_width - 1 - inset, min_travel));
      const float width = std::max(travel + 1 + inset, min_width);
      view3d_scenes_drawer_width_set(C, width / UI_SCALE_FAC);
      view3d_scenes_drawer_amount_set(C, travel / std::max(width - 1 - inset, 1.0f));
      drawer_tag_redraw(C);
      break;
    }

    case LEFTMOUSE:
      if (event->val == KM_RELEASE) {
        if (RNA_boolean_get(op->ptr, "dragged")) {
          const bool open = view3d_scenes_drawer_amount(C) >= 0.999f;
          view3d_scenes_drawer_slide_stop(C);
          if (open) {
            view3d_scenes_drawer_amount_set(C, 1.0f);
          }
          else {
            const float width = view3d_scenes_drawer_width(CTX_wm_manager(C));
            const float start_width = RNA_float_get(op->ptr, "start_width");
            const float amount = view3d_scenes_drawer_amount(C) * width / start_width;
            view3d_scenes_drawer_width_set(C, start_width);
            view3d_scenes_drawer_amount_set(C, amount);
            if (amount > 0.0f) {
              view3d_scenes_drawer_slide_begin(C);
            }
          }
          view3d_scenes_drawer_target_set(C, open ? 1 : 0);
        }
        else if (!RNA_boolean_get(op->ptr, "edge_resize")) {
          view3d_scenes_drawer_slide_begin(C);
          view3d_scenes_drawer_target_set(C, view3d_scenes_drawer_target(C) != 0 ? 0 : 1);
        }
        drawer_tag_redraw(C);
        WM_cursor_modal_restore(CTX_wm_window(C));
        return OPERATOR_FINISHED;
      }
      break;

    case EVT_ESCKEY:
      view3d_scenes_drawer_slide_stop(C);
      view3d_scenes_drawer_width_set(C, RNA_float_get(op->ptr, "start_width"));
      view3d_scenes_drawer_amount_set(C, RNA_float_get(op->ptr, "start_amount"));
      view3d_scenes_drawer_target_set(C, RNA_int_get(op->ptr, "start_target"));
      drawer_tag_redraw(C);
      WM_cursor_modal_restore(CTX_wm_window(C));
      return OPERATOR_FINISHED;

    default:
      break;
  }
  return OPERATOR_RUNNING_MODAL;
}

static void drawer_grip_cancel(bContext *C, wmOperator * /*op*/)
{
  if (wmWindow *win = CTX_wm_window(C)) {
    WM_cursor_modal_restore(win);
  }
}

static void VIEW3D_OT_scenes_drawer_grip(wmOperatorType *ot)
{
  ot->name = "Scenes Drawer Grip";
  ot->idname = "VIEW3D_OT_scenes_drawer_grip";
  ot->description = "Drag the edge or tab to resize; click the tab to toggle the scenes drawer";
  ot->invoke = drawer_grip_invoke;
  ot->modal = drawer_grip_modal;
  ot->cancel = drawer_grip_cancel;
  ot->poll = view3d_scenes_drawer_op_poll;
  ot->flag = 0;

  RNA_def_int(ot->srna, "start_xy", 0, 0, 100000, "Start X", "", 0, 100000);
  RNA_def_float(ot->srna, "start_amount", 0.0f, 0.0f, 1.0f, "Start Amount", "", 0.0f, 1.0f);
  RNA_def_int(ot->srna, "start_target", 0, 0, 1, "Start Target", "", 0, 1);
  RNA_def_float(ot->srna, "start_width", 300.0f, 1.0f, 100000.0f, "Start Width", "", 1.0f, 100000.0f);
  RNA_def_float(ot->srna, "start_travel", 0.0f, 0.0f, 100000.0f, "Start Travel", "", 0.0f, 100000.0f);
  RNA_def_boolean(ot->srna, "dragged", false, "Dragged", "");
  RNA_def_boolean(ot->srna, "edge_resize", false, "Edge Resize", "");
}

void view3d_scenes_drawer_operatortypes()
{
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_update);
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_reveal);
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_toggle);
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_set);
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_grip);
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_click);
  WM_operatortype_append(VIEW3D_OT_scenes_drawer_hover);
}

void view3d_scenes_drawer_keymap(wmKeyConfig *keyconf)
{
  wmKeyMap *grip = WM_keymap_ensure(
      keyconf, "Scenes Drawer Grip", SPACE_VIEW3D, VIEW3D_SCENES_DRAWER_REGION_TYPE);

  KeyMapItem_Params press{};
  press.type = LEFTMOUSE;
  press.value = KM_PRESS;
  WM_keymap_add_item(grip, "VIEW3D_OT_scenes_drawer_grip", &press);
  WM_keymap_add_item(grip, "VIEW3D_OT_scenes_drawer_click", &press);
  KeyMapItem_Params move{};
  move.type = MOUSEMOVE;
  move.value = KM_ANY;
  WM_keymap_add_item(grip, "VIEW3D_OT_scenes_drawer_hover", &move);

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
