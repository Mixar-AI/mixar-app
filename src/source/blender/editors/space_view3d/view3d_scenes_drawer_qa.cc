/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** QA targets for the Scenes drawer: the panel, its resize sash and the scene
 * cards the last draw pass laid out. The toolbar toggle is an ordinary button
 * (`view3d.scenes_drawer_toggle`), found by its operator. */
#include <algorithm>
#include "BLI_string.h"
#include "DNA_windowmanager_types.h"
#include "WM_api.hh"
#include "../interface/interface_qa_inspect.hh"
#include "view3d_scenes_drawer.hh"

namespace blender {

namespace {

void drawer_qa_targets(const wmWindow *win,
                       const ScrArea *area,
                       const ARegion *region,
                       std::vector<MixarQATarget> &r_targets)
{
  if (area->spacetype != SPACE_VIEW3D || region->regiontype != VIEW3D_SCENES_DRAWER_REGION_TYPE) {
    return;
  }
  const ScenesDrawerRuntime *runtime = static_cast<const ScenesDrawerRuntime *>(region->regiondata);
  if (runtime == nullptr) {
    return;
  }

  auto push = [&](const rcti &rect_win,
                  const char *surface,
                  const std::string &text,
                  const std::string &value,
                  const int index,
                  const bool sel = false) {
    MixarQATarget t;
    t.rect_win = rect_win;
    t.surface = surface;
    t.text = text;
    t.value = value;
    t.index = index;
    t.sel = sel;
    r_targets.push_back(std::move(t));
  };

  const float amount = std::clamp(runtime->amount, 0.0f, 1.0f);
  char amount_text[32];
  SNPRINTF(amount_text, "%.3f", amount);

  rcti panel;
  if (view3d_scenes_drawer_panel_rect_for(area, region, amount, &panel)) {
    push(panel, "scenes_drawer_panel", "scenes_drawer", amount_text, 0);
  }
  rcti edge;
  if (view3d_scenes_drawer_edge_rect_for(area, region, amount, &edge)) {
    const char *cursor = win->cursor == WM_CURSOR_X_MOVE ? "RESIZE_X" : "OTHER";
    push(edge, "scenes_drawer_edge", "Resize Scenes", cursor, 0);
  }
  if (amount < VIEW3D_SCENES_DRAWER_ACTIVE_AMOUNT) {
    return;
  }
  if (runtime->new_visible) {
    push(runtime->new_rect, "scenes_drawer_new", "+ New scene", "new_scene_tab", -1);
  }
  if (!runtime->selected_uids.empty()) {
    push(runtime->bulk_delete_rect, "scenes_drawer_delete_selected", "Delete selected",
         std::to_string(runtime->selected_uids.size()), -1);
    push(runtime->clear_selection_rect, "scenes_drawer_clear_selection", "Clear", "", -1);
  }
  if (BLI_rcti_size_x(&runtime->drag_rect) > 0) {
    /* `drag_scene` is the lifted card's ID session_uid; QA reads its name. */
    const auto lifted = std::find_if(runtime->cards.begin(), runtime->cards.end(),
                                     [&](const ScenesDrawerCard &card) {
                                       return card.scene_uid == runtime->drag_scene;
                                     });
    const std::string label = lifted == runtime->cards.end() ? runtime->drag_scene :
                                                               lifted->scene_name;
    push(runtime->drag_rect, "scenes_drawer_drag", label, "dragging", runtime->drag_index);
  }
  if (BLI_rcti_size_x(&runtime->drop_rect) > 0) {
    push(runtime->drop_rect, "scenes_drawer_drop", "Move scene here", "insertion", runtime->drag_target);
  }
  int index = 0;
  for (const ScenesDrawerCard &card : runtime->cards) {
    if (BLI_rcti_size_x(&card.rect) <= 0) {
      index++;
      continue;
    }
    push(card.rect, "scenes_drawer_card", card.scene_name, card.session_id, index, card.is_active);
    if (runtime->selected_uids.contains(card.scene_uid)) {
      push(card.rect, "scenes_drawer_selection", card.scene_name, card.scene_uid, index, true);
    }
    if (BLI_rcti_size_x(&card.thumb_rect) > 0) {
      push(card.thumb_rect,
           "scenes_drawer_card_thumb",
           card.scene_name,
           view3d_scenes_drawer_snapshot_exists(card.scene_name) ? "snapshot" : "none",
           index);
    }
    if (BLI_rcti_size_x(&card.close_rect) > 0) {
      push(card.close_rect, "scenes_drawer_card_close", card.scene_name, card.session_id, index);
    }
    index++;
  }
}

}  // namespace

void view3d_scenes_drawer_qa_targets_register()
{
  Mixar_qa_register_target_provider(SPACE_VIEW3D, drawer_qa_targets);
}

}  // namespace blender
