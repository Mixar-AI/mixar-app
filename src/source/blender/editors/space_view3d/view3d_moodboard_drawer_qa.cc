/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** QA targets share the drawer's native input geometry. */
#include <algorithm>
#include "BLI_string.h"
#include "DNA_windowmanager_types.h"
#include "WM_api.hh"
#include "../interface/interface_qa_inspect.hh"
#include "view3d_moodboard_drawer.hh"

namespace blender {
/* -------------------------------------------------------------------- */
/** \name QA targets
 * \{ */

namespace {

void drawer_qa_targets(const wmWindow *win,
                       const ScrArea *area,
                       const ARegion *region,
                       std::vector<MixarQATarget> &r_targets)
{
  if (area->spacetype != SPACE_VIEW3D || region->regiontype != RGN_TYPE_TOOL_PROPS) {
    return;
  }
  /* Read `regiondata` directly, never `runtime_ensure`: a dump must not
   * allocate region data on a region the user has not opened. */
  const MoodboardDrawerRuntime *runtime =
      static_cast<const MoodboardDrawerRuntime *>(region->regiondata);
  if (runtime == nullptr) {
    return;
  }

  auto push = [&](const rcti &rect_win,
                  const char *surface,
                  const char *text,
                  const char *value,
                  const int index) {
    MixarQATarget t;
    t.rect_win = rect_win;
    t.surface = surface;
    t.text = text;
    t.value = value;
    t.index = index;
    r_targets.push_back(std::move(t));
  };

  const float amount = std::clamp(runtime->amount, 0.0f, 1.0f);
  char amount_text[32];
  SNPRINTF(amount_text, "%.3f", amount);

  /* The grip rides the panel's leading edge, so it is the one target that is
   * meaningful in both the open and the shut state. It is exported in WINDOW
   * coordinates even though it lives in a region, so the harness clicks the
   * same pixels the user does. */
  rcti grip;
  if (view3d_moodboard_drawer_grip_rect_for(area, region, amount, &grip)) {
    push(grip, "moodboard_drawer_grip", "drawer_grip", amount_text, -1);
  }

  /* The visible slice of the panel. A shut drawer exports no panel target at
   * all, so a harness cannot click a panel that is not on screen. */
  rcti panel;
  if (view3d_moodboard_drawer_panel_rect_for(area, region, amount, &panel)) {
    push(panel, "moodboard_drawer_panel", "moodboard_drawer", amount_text, 0);
  }
  rcti edge;
  if (view3d_moodboard_drawer_edge_rect_for(area, region, amount, &edge)) {
    /* Keep semantic edge targets off the tab, whose click toggles. */
    rcti upper = edge;
    rcti lower = edge;
    upper.ymin = std::max(edge.ymin, grip.ymax + 1);
    lower.ymax = std::min(edge.ymax, grip.ymin - 1);
    const char *cursor = win->cursor == WM_CURSOR_X_MOVE ? "RESIZE_X" : "OTHER";
    if (BLI_rcti_size_y(&upper) > 0) {
      push(upper, "moodboard_drawer_edge", "Resize Moodboard", cursor, 0);
    }
    if (BLI_rcti_size_y(&lower) > 0) {
      push(lower, "moodboard_drawer_edge", "Resize Moodboard", cursor, 1);
    }
  }
}

}  // namespace

void view3d_moodboard_drawer_qa_targets_register()
{
  Mixar_qa_register_target_provider(SPACE_VIEW3D, drawer_qa_targets);
}

/** \} */

}  // namespace blender
