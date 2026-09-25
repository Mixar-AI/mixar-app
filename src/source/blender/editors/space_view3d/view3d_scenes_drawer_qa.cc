/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** QA targets for the Scenes drawer: the drawer's own input geometry plus the
 * scene cards the last draw pass laid out. */
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

  rcti grip;
  if (view3d_scenes_drawer_grip_rect_for(area, region, amount, &grip)) {
    push(grip, "scenes_drawer_grip", "drawer_grip", amount_text, -1);
  }
  rcti panel;
  if (view3d_scenes_drawer_panel_rect_for(area, region, amount, &panel)) {
    push(panel, "scenes_drawer_panel", "scenes_drawer", amount_text, 0);
  }
  rcti edge;
  if (view3d_scenes_drawer_edge_rect_for(area, region, amount, &edge)) {
    rcti upper = edge;
    rcti lower = edge;
    upper.ymin = std::max(edge.ymin, grip.ymax + 1);
    lower.ymax = std::min(edge.ymax, grip.ymin - 1);
    const char *cursor = win->cursor == WM_CURSOR_X_MOVE ? "RESIZE_X" : "OTHER";
    if (BLI_rcti_size_y(&upper) > 0) {
      push(upper, "scenes_drawer_edge", "Resize Scenes", cursor, 0);
    }
    if (BLI_rcti_size_y(&lower) > 0) {
      push(lower, "scenes_drawer_edge", "Resize Scenes", cursor, 1);
    }
  }
  if (amount < VIEW3D_SCENES_DRAWER_ACTIVE_AMOUNT) {
    return;
  }
  if (runtime->new_visible) {
    push(runtime->new_rect, "scenes_drawer_new", "+ New scene", "new_scene_tab", -1);
  }
  int index = 0;
  for (const ScenesDrawerCard &card : runtime->cards) {
    push(card.rect, "scenes_drawer_card", card.scene_name, card.session_id, index, card.is_active);
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
