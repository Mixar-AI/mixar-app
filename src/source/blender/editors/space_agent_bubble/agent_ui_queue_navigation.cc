/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "BKE_context.hh"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"
#include "ED_screen.hh"
#include "RNA_access.hh"
#include "RNA_define.hh"
#include "WM_api.hh"
#include "WM_types.hh"
#include "agent_ui_draw.hh"
#include "agent_ui_layout.hh"
#include "agent_ui_queue.hh"
#include "agent_ui_queue_intern.hh"
#include <algorithm>

namespace blender {
namespace {
using namespace agent_queue;

bool queue_poll(bContext *C)
{
  const SpaceLink *space = CTX_wm_space_data(C);
  const ARegion *region = CTX_wm_region(C);
  if (!space || space->spacetype != SPACE_AGENT_BUBBLE || !region ||
      region->regiontype != RGN_TYPE_WINDOW)
  {
    return false;
  }
  PointerRNA wm = RNA_id_pointer_create(&CTX_wm_manager(C)->id);
  PropertyRNA *tab = RNA_struct_find_property(&wm, "mixar_bubble_tab");
  int queue;
  return tab && RNA_property_enum_value(C, &wm, tab, "QUEUE", &queue) &&
         RNA_property_enum_get(&wm, tab) == queue &&
         RNA_struct_find_property(&wm, "mixar_queue_offset");
}

wmOperatorStatus navigate(bContext *C, wmOperator *op, const wmEvent *event)
{
  AgentIslandLayout island;
  AgentIslandState state;
  if (!agent_bubble_island_layout_get(C, &state, &island)) {
    return OPERATOR_CANCELLED;
  }
  ARegion *region = CTX_wm_region(C);
  rctf panel = island.panel;
  BLI_rctf_translate(&panel, -float(region->winrct.xmin), -float(region->winrct.ymin));
  if (event && !BLI_rctf_isect_pt(&panel, event->mval[0], event->mval[1])) {
    return OPERATOR_PASS_THROUGH;
  }
  wmWindowManager *wm = CTX_wm_manager(C);
  const int total = agent_queue::total_rows(wm);
  const auto layout = agent_queue::layout(panel, island.scale, total);
  const float maximum = float(std::max(0, total - layout.capacity));
  float offset = std::clamp(agent_queue::offset_get(wm), 0.0f, maximum);
  float delta = RNA_float_get(op->ptr, "delta");
  if (event && event->type == MOUSEPAN) {
    /* Native delta respects the natural-scrolling preference. Keep fractional rows
     * between events; only whole rows are exposed as interactive buttons. */
    delta = float(WM_event_absolute_delta_y(event)) / (layout.row_height + layout.row_gap);
  }
  switch (RNA_enum_get(op->ptr, "action")) {
    case FIRST:
      offset = 0;
      break;
    case LAST:
      offset = maximum;
      break;
    case PAGE:
      offset += delta * layout.capacity;
      break;
    default:
      offset += delta;
      break;
  }
  PointerRNA ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *property = RNA_struct_find_property(&ptr, "mixar_queue_offset");
  RNA_property_float_set(&ptr, property, std::clamp(offset, 0.0f, maximum));
  RNA_property_update(C, &ptr, property);
  ED_region_tag_redraw(region);
  return OPERATOR_FINISHED;
}

wmOperatorStatus queue_exec(bContext *C, wmOperator *op)
{
  return navigate(C, op, nullptr);
}
wmOperatorStatus queue_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  return navigate(C, op, event);
}
}  // namespace

void MIXAR_OT_queue_navigate(wmOperatorType *ot)
{
  static const EnumPropertyItem actions[] = {
      {STEP, "STEP", 0, "Scroll", "Scroll queue rows"},
      {PAGE, "PAGE", 0, "Page", "Move by the visible row count"},
      {FIRST, "FIRST", 0, "First", "Show newest jobs"},
      {LAST, "LAST", 0, "Last", "Show oldest jobs"},
      {0, nullptr, 0, nullptr, nullptr}};
  ot->name = "Browse Queue";
  ot->idname = "MIXAR_OT_queue_navigate";
  ot->description = "Browse generation jobs in the island Queue";
  ot->poll = queue_poll;
  ot->exec = queue_exec;
  ot->invoke = queue_invoke;
  RNA_def_enum(ot->srna, "action", actions, STEP, "Action", "");
  RNA_def_float(ot->srna, "delta", 1, -10000, 10000, "Rows", "", -100, 100);
}
}  // namespace blender
