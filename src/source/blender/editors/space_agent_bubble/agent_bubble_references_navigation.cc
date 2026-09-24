/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "BKE_context.hh"
#include "BKE_screen.hh"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "ED_screen.hh"
#include "RNA_access.hh"
#include "RNA_define.hh"
#include "UI_interface_c.hh"
#include "WM_api.hh"
#include "WM_types.hh"
#include "agent_bubble_references.hh"
#include <algorithm>

namespace blender {
void agent_bubble_references_region_init(wmWindowManager *wm, ARegion *region)
{
  wmKeyMap *keymap = WM_keymap_ensure(
      wm->runtime->defaultconf, "Agent Bubble References", SPACE_AGENT_BUBBLE, RGN_TYPE_UI);
  WM_event_add_keymap_handler(&region->runtime->handlers, keymap);
  ui::region_handlers_add(&region->runtime->handlers);
  WM_event_add_dropbox_handler(
      &region->runtime->handlers,
      WM_dropboxmap_find("Agent Chat Composer", SPACE_AGENT_BUBBLE, RGN_TYPE_TOOLS));
}

namespace {
bool reference_poll(bContext *C)
{
  const ARegion *region = CTX_wm_region(C);
  if (!region || region->regiontype != RGN_TYPE_UI || !agent_bubble_references_visible(C)) {
    return false;
  }
  PointerRNA ptr = RNA_id_pointer_create(&CTX_wm_manager(C)->id);
  return RNA_struct_find_property(&ptr, AGENT_REFERENCE_SCROLL) != nullptr;
}

wmOperatorStatus navigate(bContext *C, wmOperator *op, const wmEvent *event)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  ARegion *region = CTX_wm_region(C);
  const auto g = agent_bubble_reference_geometry(CTX_wm_window(C),
                                                 region,
                                                 agent_bubble_reference_count(C),
                                                 agent_bubble_reference_fraction(wm));
  if (event && !BLI_rctf_isect_pt(&g.view, event->mval[0], event->mval[1])) {
    return OPERATOR_PASS_THROUGH;
  }
  float offset = g.offset;
  if (g.max_scroll > 0) {
    if (event && event->type == MOUSEPAN) {
      offset += WM_event_absolute_delta_y(event);
    }
    else {
      offset += RNA_float_get(op->ptr, "delta") * g.row_pitch * 0.3f;
    }
  }
  PointerRNA ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *property = RNA_struct_find_property(&ptr, AGENT_REFERENCE_SCROLL);
  RNA_property_float_set(
      &ptr, property, g.max_scroll > 0 ? std::clamp(offset / g.max_scroll, 0.0f, 1.0f) : 0.0f);
  RNA_property_update(C, &ptr, property);
  ED_region_tag_redraw(region);
  return OPERATOR_FINISHED;
}
wmOperatorStatus reference_exec(bContext *C, wmOperator *op)
{
  return navigate(C, op, nullptr);
}
wmOperatorStatus reference_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  return navigate(C, op, event);
}
}  // namespace

void MIXAR_OT_reference_scroll(wmOperatorType *ot)
{
  ot->name = "Scroll References";
  ot->idname = "MIXAR_OT_reference_scroll";
  ot->description = "Browse attached reference images";
  ot->poll = reference_poll;
  ot->exec = reference_exec;
  ot->invoke = reference_invoke;
  RNA_def_float(ot->srna, "delta", 1, -10000, 10000, "Distance", "", -100, 100);
}
}  // namespace blender
