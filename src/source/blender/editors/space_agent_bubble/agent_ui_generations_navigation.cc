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
#include "agent_ui_generations.hh"
#include "agent_ui_generations_intern.hh"
#include "agent_ui_layout.hh"
#include <algorithm>
#include "../interface/interface_intern.hh"

namespace blender {
/* The native default comparison ignores operator properties. A hovered slot
 * would otherwise retain the old asset/library when scrolling or refiltering. */
bool agent_ui_generations_button_identity(const ui::Button *a, const ui::Button *b)
{
  return a->optype == b->optype && a->opptr && b->opptr &&
         RNA_string_get(a->opptr, "data_path") == RNA_string_get(b->opptr, "data_path") &&
         RNA_string_get(a->opptr, "value") == RNA_string_get(b->opptr, "value");
}

namespace {
enum { STEP, PAGE, FIRST, LAST };

bool library_poll(bContext *C)
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
  int library;
  return tab && RNA_property_enum_value(C, &wm, tab, "GENERATIONS", &library) &&
         RNA_property_enum_get(&wm, tab) == library &&
         RNA_struct_find_property(&wm, "mixar_generations_scroll");
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
  GenPaneData data;
  agent_ui_generations_gather(C, &data);
  const GenFrame frame = agent_ui_generations_frame(panel, island.scale);
  const auto grid = agent_ui_generations_grid_metrics(frame, data);
  const auto libraries = agent_ui_generations_library_metrics(frame, data);
  const bool rail = event && data.source == GEN_SOURCE_LIBRARY && event->mval[0] < frame.rail_div_x;
  const float maximum = rail ? libraries.max_scroll : grid.max_scroll;
  const float page = rail ? BLI_rctf_size_y(&libraries.view) : BLI_rctf_size_y(&grid.view);
  const float pitch = rail ? libraries.pitch : grid.pitch_y;
  float offset = rail ? libraries.offset : grid.offset;
  const float direction = RNA_float_get(op->ptr, "delta");
  float delta = direction * pitch * 0.3f;
  if (event && event->type == MOUSEPAN) {
    /* Match View2D panning. xy already incorporates the OS scroll-direction
     * preference; absolute_delta would undo it on traditional scrolling. */
    delta = float(event->xy[1] - event->prev_xy[1]);
  }
  switch (RNA_enum_get(op->ptr, "action")) {
    case FIRST:
      offset = 0;
      break;
    case LAST:
      offset = maximum;
      break;
    case PAGE:
      offset += direction * page;
      break;
    default:
      offset += delta;
      break;
  }
  PointerRNA wm = RNA_id_pointer_create(&CTX_wm_manager(C)->id);
  PropertyRNA *property = RNA_struct_find_property(
      &wm, rail ? "mixar_generations_library_scroll" : "mixar_generations_scroll");
  RNA_property_float_set(
      &wm, property, maximum > 0 ? std::clamp(100.0f * offset / maximum, 0.0f, 100.0f) : 0.0f);
  RNA_property_update(C, &wm, property);
  ED_region_tag_redraw(region);
  return OPERATOR_FINISHED;
}
wmOperatorStatus library_exec(bContext *C, wmOperator *op)
{
  return navigate(C, op, nullptr);
}
wmOperatorStatus library_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  return navigate(C, op, event);
}
}  // namespace

void MIXAR_OT_generations_navigate(wmOperatorType *ot)
{
  static const EnumPropertyItem actions[] = {
      {STEP, "STEP", 0, "Scroll", "Scroll library content"},
      {PAGE, "PAGE", 0, "Page", "Move by the viewport height"},
      {FIRST, "FIRST", 0, "First", "Show the first items"},
      {LAST, "LAST", 0, "Last", "Show the last items"},
      {0, nullptr, 0, nullptr, nullptr}};
  ot->name = "Browse Library";
  ot->idname = "MIXAR_OT_generations_navigate";
  ot->description = "Scroll Library assets or connected libraries under the pointer";
  ot->poll = library_poll;
  ot->exec = library_exec;
  ot->invoke = library_invoke;
  RNA_def_enum(ot->srna, "action", actions, STEP, "Action", "");
  RNA_def_float(ot->srna, "delta", 1, -10000, 10000, "Rows", "", -100, 100);
}
}  // namespace blender
