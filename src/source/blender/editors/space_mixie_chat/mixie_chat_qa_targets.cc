/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * QA harness target provider: exports the chat's custom-drawn clickable
 * geometry (message action/gate buttons, feedback stars, steps/thinking
 * headers) from the SAME layout cache the click hit-testing reads
 * (mixie_chat_hit_testing.cc), so QA click targets can never drift from what
 * users actually click. Read-only.
 */

#include <algorithm>

#include "BLI_rect.h"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "UI_view2d.hh"

#include "../interface/interface_qa_inspect.hh"

#include "mixie_chat_layout_data.hh"
#include "mixie_chat_ui_types.hh"

namespace {

bool view_rect_to_window(const ARegion *region, const rctf &view, rcti *r_win)
{
  if (!(view.xmax > view.xmin) || !(view.ymax > view.ymin)) {
    return false;
  }
  View2D *v2d = &const_cast<ARegion *>(region)->v2d;
  float x0, y0, x1, y1;
  UI_view2d_view_to_region_fl(v2d, view.xmin, view.ymin, &x0, &y0);
  UI_view2d_view_to_region_fl(v2d, view.xmax, view.ymax, &x1, &y1);
  r_win->xmin = region->winrct.xmin + int(std::min(x0, x1));
  r_win->xmax = region->winrct.xmin + int(std::max(x0, x1));
  r_win->ymin = region->winrct.ymin + int(std::min(y0, y1));
  r_win->ymax = region->winrct.ymin + int(std::max(y0, y1));
  return true;
}

void chat_qa_targets(const wmWindow * /*win*/,
                     const ScrArea *area,
                     const ARegion *region,
                     std::vector<MixarQATarget> &r_targets)
{
  if (region->regiontype != RGN_TYPE_WINDOW) {
    return;
  }
  SpaceMixieChat *smixie = static_cast<SpaceMixieChat *>(area->spacedata.first);
  if (smixie == nullptr) {
    return;
  }
  const blender::Vector<MessageLayoutData> &cache = mixie_chat_get_layout_cache(smixie);

  for (const MessageLayoutData &layout : cache) {
    for (int i = 0; i < layout.slot_action_count; i++) {
      const ActionSlotData &action = layout.slot_actions[i];
      MixarQATarget t;
      if (!view_rect_to_window(region, action.bounds, &t.rect_win)) {
        continue;
      }
      t.surface = "chat_action";
      t.text = action.label;
      t.value = action.value;
      t.index = i;
      r_targets.push_back(std::move(t));
    }
    if (layout.has_feedback) {
      for (const FeedbackStarData &star : layout.feedback_stars) {
        MixarQATarget t;
        if (!view_rect_to_window(region, star.bounds, &t.rect_win)) {
          continue;
        }
        t.surface = "chat_star";
        t.text = layout.bubble_id;
        t.index = star.star_index;
        r_targets.push_back(std::move(t));
      }
      MixarQATarget t;
      if (view_rect_to_window(region, layout.feedback_comment_bounds, &t.rect_win)) {
        t.surface = "chat_feedback_comment";
        t.text = layout.bubble_id;
        r_targets.push_back(std::move(t));
      }
    }
    if (layout.has_steps) {
      MixarQATarget t;
      if (view_rect_to_window(region, layout.steps_header_bounds, &t.rect_win)) {
        t.surface = "chat_steps_header";
        t.text = layout.steps_summary;
        t.value = layout.bubble_id;
        r_targets.push_back(std::move(t));
      }
    }
    if (layout.has_thinking) {
      MixarQATarget t;
      if (view_rect_to_window(region, layout.thinking_header_bounds, &t.rect_win)) {
        t.surface = "chat_thinking_header";
        t.text = "thinking";
        t.value = layout.bubble_id;
        r_targets.push_back(std::move(t));
      }
    }
  }
}

}  // namespace

void mixie_chat_qa_targets_register()
{
  Mixar_qa_register_target_provider(SPACE_MIXIE_CHAT, chat_qa_targets);
  /* The floating Agent Bubble: SpaceAgentBubble is layout-identical to
   * SpaceMixieChat and renders chat history through the same code (see
   * space_agent_bubble.cc), so the same layout-cache targets apply — this is
   * what makes gate buttons / rating stars clickable inside the bubble. */
  Mixar_qa_register_target_provider(SPACE_AGENT_BUBBLE, chat_qa_targets);
}
