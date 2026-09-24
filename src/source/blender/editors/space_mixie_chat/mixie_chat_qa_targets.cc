/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * QA harness target provider: exports the chat's custom-drawn clickable
 * geometry (message action/gate buttons, feedback votes, steps/thinking
 * headers) from the SAME layout cache the click hit-testing reads
 * (mixie_chat_hit_testing.cc), so QA click targets can never drift from what
 * users actually click. Read-only.
 */

#include <algorithm>

#include "BLI_rect.h"
#include "BLI_string.h"

#include "BKE_global.hh"
#include "BKE_main.hh"

#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_windowmanager_types.h"

#include "UI_view2d.hh"

#include "../interface/interface_qa_inspect.hh"

#include "mixie_chat_history_intern.hh"
#include "mixie_chat_intern.hh"
#include "mixie_chat_rules_intern.hh"
#include "mixie_chat_layout_data.hh"
#include "mixie_chat_ui_types.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

bool view_rect_to_window(const ARegion *region, const rctf &view, rcti *r_win)
{
  if (!(view.xmax > view.xmin) || !(view.ymax > view.ymin)) {
    return false;
  }
  View2D *v2d = &const_cast<ARegion *>(region)->v2d;
  float x0, y0, x1, y1;
  blender::ui::view2d_view_to_region_fl(v2d, view.xmin, view.ymin, &x0, &y0);
  blender::ui::view2d_view_to_region_fl(v2d, view.xmax, view.ymax, &x1, &y1);
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
    for (int i = 0; i < layout.action_button_count; i++) {
      const ChatActionButton &button = layout.action_buttons[i];
      MixarQATarget t;
      if (button.type != CHAT_ACTION_COPY ||
          !view_rect_to_window(region, button.bounds, &t.rect_win)) {
        continue;
      }
      t.surface = "chat_message_copy";
      t.text = "Copy response";
      t.value = layout.bubble_id;
      t.index = layout.message_index;
      r_targets.push_back(std::move(t));
    }
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
      for (const FeedbackVoteData &vote : layout.feedback_votes) {
        MixarQATarget t;
        if (!view_rect_to_window(region, vote.bounds, &t.rect_win)) {
          continue;
        }
        t.surface = "chat_feedback_vote";
        t.text = vote.rating == 5 ? "Thumbs up" : "Thumbs down";
        t.value = layout.bubble_id;
        t.index = vote.rating;
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
      /* Once the block is expanded, each row carrying a second level is
       * separately clickable (mixie_chat.toggle_step_row) — mirror the exact
       * guards mixie_chat_handle_steps_click uses, or QA would offer rows
       * that swallow the click and toggle nothing. */
      if (!layout.steps_collapsed) {
        for (int i = 0; i < layout.slot_step_count; i++) {
          const StepItemSlotData &step = layout.slot_steps[i];
          if (step.detail[0] == '\0') {
            continue;
          }
          MixarQATarget row;
          if (!view_rect_to_window(region, step.row_bounds, &row.rect_win)) {
            continue;
          }
          row.surface = "chat_step_row";
          row.text = step.label;
          row.value = layout.bubble_id;
          row.detail = step.id;
          row.index = i;
          row.sel = step.expanded;
          r_targets.push_back(std::move(row));
        }
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

  /* The past-chats / checkpoints card (screen-space, region-local rects):
   * its rows and close button, read from the same hit rects the events use.
   * `sel` on a row = armed (Delete? / Revert?); `detail` on a checkpoint row
   * = its section ("Turns", "Reverted turns", "Safety copies"). */
  MixieChatRuntime *rt = mixie_chat_ensure_runtime(smixie);
  if (rt != nullptr && rt->rules_overlay_active) {
    const auto add_rules_target = [&](const char *surface, const rctf &bounds,
                                      const char *text = "", int index = -1,
                                      bool selected = false, bool enabled = true,
                                      bool in_list = false) {
      rctf visible = bounds;
      visible.xmin = std::max(visible.xmin, 0.0f);
      visible.ymin = std::max(visible.ymin, 0.0f);
      visible.xmax = std::min(visible.xmax, float(region->winx));
      visible.ymax = std::min(visible.ymax, float(region->winy));
      if (visible.xmax <= visible.xmin || visible.ymax <= visible.ymin) {
        return;
      }
      if (in_list) {
        visible.ymin = std::max(visible.ymin, rt->rules_list_bounds.ymin);
        visible.ymax = std::min(visible.ymax, rt->rules_list_bounds.ymax);
        if (visible.ymax <= visible.ymin) {
          return;
        }
      }
      MixarQATarget target;
      target.surface = surface;
      target.text = text;
      target.index = index;
      target.sel = selected;
      target.enabled = enabled;
      target.rect_win = {region->winrct.xmin + int(visible.xmin),
                         region->winrct.xmin + int(visible.xmax),
                         region->winrct.ymin + int(visible.ymin),
                         region->winrct.ymin + int(visible.ymax)};
      r_targets.push_back(std::move(target));
    };
    add_rules_target("chat_rules_panel", rt->rules_panel_bounds, "Project Rules");
    add_rules_target("chat_rules_editor", rt->rules_text_bounds, "Rule text");
    add_rules_target("chat_rules_submit", rt->rules_submit_bounds,
                     rt->rules_editing_index >= 0 ? "Save" : "Add Rule", -1, false,
                     mixie_chat_rules_can_submit(rt));
    add_rules_target("chat_rules_close", rt->rules_close_bounds, "Close");
    add_rules_target("chat_rules_list", rt->rules_list_bounds, "Rules");
    for (const RuleRowHit &row : rt->rules_rows) {
      add_rules_target("chat_rules_toggle", row.toggle_bounds, "Enabled", row.index,
                       row.enabled, true, true);
      add_rules_target("chat_rules_edit", row.edit_bounds, "Edit", row.index,
                       rt->rules_editing_index == row.index, true, true);
      add_rules_target("chat_rules_scope",
                       mixie_chat_rules_scope_choice_bounds(row.scope_bounds, false),
                       RULES_SCOPE_PROJECT, row.index, !row.is_global, true, true);
      add_rules_target("chat_rules_scope",
                       mixie_chat_rules_scope_choice_bounds(row.scope_bounds, true),
                       RULES_SCOPE_GLOBAL, row.index, row.is_global, true, true);
      add_rules_target("chat_rules_delete", row.delete_bounds, "Delete", row.index,
                       rt->rules_confirm_delete == row.index, true, true);
    }
  }
  if (rt != nullptr && rt->history_overlay_active) {
    wmWindowManager *wm = static_cast<wmWindowManager *>(G_MAIN->wm.first);
    const bool checkpoints = (mixie_chat_history_read_mode(wm) == HistoryMode::Checkpoints);
    const bool locked = checkpoints && mixie_chat_history_read_locked(wm);
    const char *row_surface = checkpoints ? "chat_checkpoint_row" : "chat_history_row";
    auto region_rect = [region](const rctf &r, rcti *r_win) {
      if (r.xmax <= r.xmin || r.ymax <= r.ymin) {
        return false;
      }
      r_win->xmin = region->winrct.xmin + int(r.xmin);
      r_win->xmax = region->winrct.xmin + int(r.xmax);
      r_win->ymin = region->winrct.ymin + int(r.ymin);
      r_win->ymax = region->winrct.ymin + int(r.ymax);
      return true;
    };
    int index = 0;
    for (const HistoryRowHit &row : rt->history_rows) {
      /* Only rows inside the list viewport are clickable. */
      rctf visible = row.bounds;
      visible.ymin = std::max(visible.ymin, rt->history_list_bounds.ymin);
      visible.ymax = std::min(visible.ymax, rt->history_list_bounds.ymax);
      MixarQATarget t;
      if (region_rect(visible, &t.rect_win)) {
        t.surface = row_surface;
        t.text = row.title;
        t.value = row.session_id;
        t.index = index;
        t.enabled = !locked;
        t.sel = STREQ(rt->history_confirm_id, row.session_id);
        if (checkpoints) {
          t.detail = row.group;
        }
        r_targets.push_back(std::move(t));
      }
      index++;
    }
    MixarQATarget close;
    if (region_rect(rt->history_close_bounds, &close.rect_win)) {
      close.surface = checkpoints ? "chat_checkpoints_close" : "chat_history_close";
      close.text = "close";
      r_targets.push_back(std::move(close));
    }
  }
}

}  // namespace

void mixie_chat_qa_targets_register()
{
  /* The floating Agent Bubble: SpaceAgentBubble is layout-identical to
   * SpaceMixieChat and renders chat history through the same code (see
   * space_agent_bubble.cc), so the same layout-cache targets apply — this is
   * what makes gate buttons / feedback votes clickable inside the bubble. */
  Mixar_qa_register_target_provider(SPACE_AGENT_BUBBLE, chat_qa_targets);
}

}  // namespace blender
