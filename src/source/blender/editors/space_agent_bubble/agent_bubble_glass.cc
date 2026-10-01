/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "agent_bubble_glass.hh"
#include "agent_bubble_intern.hh"

#include "BKE_screen.hh"
#include "DNA_windowmanager_types.h"
#include "ED_mixar_glass.hh"
#include "ED_screen.hh"
#include "WM_api.hh"
#include "WM_types.hh"

namespace blender {

static AgentBubbleGlassState island_glass;
static AgentBubbleGlassState pill_glass;

void agent_bubble_glass_request(const bContext *C, void *ghostwin, const bool pill)
{
  AgentBubbleGlassState &state = pill ? pill_glass : island_glass;
  if (state.request(ghostwin)) {
    WM_event_add_notifier(C, NC_WINDOW, nullptr);
  }
}

void agent_bubble_glass_reset(const void *ghostwin)
{
  island_glass.reset(ghostwin);
  pill_glass.reset(ghostwin);
}

void agent_bubble_glass_region_listener(const wmRegionListenerParams *params)
{
  if (params->notifier->category != NC_WINDOW || params->window == nullptr ||
      params->window->runtime->ghostwin == nullptr)
  {
    return;
  }
  void *ghostwin = params->window->runtime->ghostwin;
  const auto apply = [](void *window) {
    return ui::mixar_glass_window_apply_translucency(window, true);
  };
  const bool island_applied = island_glass.apply(ghostwin, apply);
  const bool pill_applied = pill_glass.apply(ghostwin, apply);
  if (island_applied || pill_applied) {
    ED_area_tag_redraw(params->area);
  }
}

bool agent_bubble_pill_bed_is_transparent()
{
  return pill_glass.transparent;
}

bool agent_bubble_island_bed_is_transparent()
{
  return island_glass.transparent;
}

}  // namespace blender
