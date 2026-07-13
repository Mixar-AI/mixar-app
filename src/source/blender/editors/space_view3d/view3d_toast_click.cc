/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * UI handler for toast notification interaction in the 3D viewport.
 * Runs before all keymaps, ensuring clicks on toast close/action buttons
 * are captured before Sculpt/Paint/Object mode consumes LEFTMOUSE.
 * Also forwards MOUSEMOVE to the Python hover operator (for button
 * highlight feedback) while toasts are visible — gated by a WM ID
 * property so idle viewports pay no per-event cost.
 */

#include "BKE_context.hh"
#include "BKE_idprop.hh"
#include "BKE_screen.hh"

#include "BLI_utildefines.h"

#include "DNA_space_types.h"
#include "DNA_windowmanager_enums.h"
#include "DNA_windowmanager_types.h"

#include "ED_screen.hh"

#include "RNA_access.hh"

#include "WM_api.hh"

#include "view3d_intern.hh"

/* Set by the Python toast timer (toast_timer.py) while any toast is visible.
 * Must stay in sync with TOASTS_VISIBLE_WM_PROP in notifications/constants.py. */
static const char *TOASTS_VISIBLE_WM_PROP = "mixar_toasts_visible";

static bool toast_any_visible(const bContext *C)
{
  const wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm || !wm->id.properties) {
    return false;
  }
  const IDProperty *prop = IDP_GetPropertyFromGroup(wm->id.properties, TOASTS_VISIBLE_WM_PROP);
  if (!prop) {
    return false;
  }
  if (ELEM(prop->type, IDP_INT, IDP_BOOLEAN)) {
    return IDP_int_or_bool_get(prop) != 0;
  }
  return false;
}

/** Call a Python-side toast operator with region-local mouse coordinates.
 * Returns true when the operator reported FINISHED. Gracefully returns
 * false if the operator isn't registered yet (deferred UI module loading). */
static bool toast_call_mouse_op(bContext *C, const wmEvent *event, const char *idname)
{
  wmOperatorType *ot = WM_operatortype_find(idname, true);
  if (!ot) {
    return false;
  }

  PointerRNA op_ptr;
  WM_operator_properties_create_ptr(&op_ptr, ot);
  RNA_int_set(&op_ptr, "mouse_x", event->mval[0]);
  RNA_int_set(&op_ptr, "mouse_y", event->mval[1]);

  wmOperatorStatus result = WM_operator_name_call_ptr(
      C, ot, blender::wm::OpCallContext::ExecDefault, &op_ptr, nullptr);
  WM_operator_properties_free(&op_ptr);

  return (result & OPERATOR_FINISHED) != 0;
}

static int view3d_toast_ui_handler(bContext *C, const wmEvent *event, void * /*userdata*/)
{
  const bool is_press = (event->type == LEFTMOUSE && event->val == KM_PRESS);
  const bool is_move = (event->type == MOUSEMOVE);
  if (!is_press && !is_move) {
    return WM_UI_HANDLER_CONTINUE;
  }

  ScrArea *area = CTX_wm_area(C);
  ARegion *region = CTX_wm_region(C);
  if (!area || area->spacetype != SPACE_VIEW3D || !region) {
    return WM_UI_HANDLER_CONTINUE;
  }

  if (is_move) {
    /* Hover feedback: only while toasts are on screen, never consumes. */
    if (toast_any_visible(C) &&
        toast_call_mouse_op(C, event, "notification.toast_hover")) {
      ED_region_tag_redraw(region);
    }
    return WM_UI_HANDLER_CONTINUE;
  }

  if (toast_call_mouse_op(C, event, "notification.toast_click")) {
    ED_region_tag_redraw(region);
    return WM_UI_HANDLER_BREAK;
  }

  return WM_UI_HANDLER_CONTINUE;
}

static void view3d_toast_ui_handler_remove(bContext * /*C*/, void * /*userdata*/)
{
  /* Nothing to free. */
}

void view3d_toast_click_register(ARegion *region)
{
  WM_event_remove_ui_handler(&region->runtime->handlers,
                             view3d_toast_ui_handler,
                             view3d_toast_ui_handler_remove,
                             nullptr,
                             false);
  WM_event_add_ui_handler(nullptr,
                          &region->runtime->handlers,
                          view3d_toast_ui_handler,
                          view3d_toast_ui_handler_remove,
                          nullptr,
                          eWM_EventHandlerFlag(0));
}
