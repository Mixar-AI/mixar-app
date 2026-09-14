/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * QA harness target provider for the Parallel Agents panel: exports one target
 * per card from `AgentPanelRuntime::cards` — the SAME rects the layout pass
 * wrote and `view3d_agent_panel_card_at` hit-tests against, so a harness click
 * and a user click land on the same card even mid-animation or mid-scroll.
 * Strictly read-only.
 */

#include <string>

#include "BLI_rect.h"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "../interface/interface_qa_inspect.hh"

#include "view3d_agent_panel.hh"
#include "../space_agent_bubble/agent_ui_cat_style.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

void agent_panel_qa_targets(const wmWindow * /*win*/,
                            const ScrArea *area,
                            const ARegion *region,
                            std::vector<MixarQATarget> &r_targets)
{
  if (area->spacetype != SPACE_VIEW3D || region->regiontype != RGN_TYPE_EXECUTE) {
    return;
  }
  /* Read `regiondata` directly, never `runtime_ensure`: a dump must not
   * allocate region data on a panel the user has not opened. */
  const AgentPanelRuntime *runtime = static_cast<const AgentPanelRuntime *>(region->regiondata);
  if (runtime == nullptr) {
    return;
  }

  auto push = [&](const rcti &rect, const char *surface, const char *text, const int index) {
    MixarQATarget t;
    t.rect_win.xmin = region->winrct.xmin + rect.xmin;
    t.rect_win.xmax = region->winrct.xmin + rect.xmax;
    t.rect_win.ymin = region->winrct.ymin + rect.ymin;
    t.rect_win.ymax = region->winrct.ymin + rect.ymax;
    t.surface = surface;
    t.text = text;
    t.index = index;
    r_targets.push_back(std::move(t));
  };

  int index = 0;
  for (const AgentPanelCard &card : runtime->cards) {
    const int i = index++;
    /* A card clipped out of the column is not drawn and not clickable, so it
     * is not a target either — the harness and the user share one answer to
     * "which cards are on screen". */
    if (!view3d_agent_panel_card_visible(runtime, card.rect)) {
      continue;
    }
    /* The card, then its two controls. Exporting the control rects is what
     * keeps the harness off hand-computed offsets — they are the SAME rects
     * the layout pass wrote and the click handler hit-tests, so a metric
     * change moves the targets with the pixels. */
    push(card.rect, "agent_panel_card", card.expanded ? card.task : card.name, i);
    rcti cat_visible;
    if (BLI_rcti_isect(&card.cat_rect, &runtime->column_rect, &cat_visible)) {
      push(cat_visible, "agent_panel_cat", card.task_id, i);
      r_targets.back().value = mixie_cat_style(card.cat_ordinal).name;
    }
    push(card.eye_rect, "agent_panel_eye", "eye", i);
    push(card.action_rect, "agent_panel_dismiss", "dismiss", i);
  }

  /* The chevron sits below the clipped column and is present only while
   * there are agents the stack cannot show. */
  if (BLI_rcti_size_x(&runtime->chevron_rect) > 0) {
    push(runtime->chevron_rect, "agent_panel_chevron", "more", -1);
  }
}

}  // namespace

void view3d_agent_panel_qa_targets_register()
{
  Mixar_qa_register_target_provider(SPACE_VIEW3D, agent_panel_qa_targets);
}

}  // namespace blender
