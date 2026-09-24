/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#include "BLI_string.h"

#include "DNA_windowmanager_types.h"
#include "ED_moodboard_drawer.hh"
#include "ED_screen.hh"
#include "WM_api.hh"
#include "wm_event_types.hh"

#include "mixie_moodboard_canvas.hh"
#include "mixie_moodboard_chrome.hh"
#include "mixie_moodboard_node_layout.hh"

namespace blender::ed::mixie {

rcti moodboard_canvas_host_rect(const bContext *C)
{
  return moodboard_canvas_host_rect(CTX_wm_area(C), CTX_wm_region(C));
}

rcti moodboard_canvas_host_rect(const ScrArea *area, ARegion *region)
{
  if (area->spacetype == SPACE_MIXIE && region->regiontype == RGN_TYPE_WINDOW) {
    return *ED_region_visible_rect(region);
  }
  return moodboard_canvas_draw_rect(area, region);
}

rcti moodboard_canvas_draw_rect(const bContext *C)
{
  return moodboard_canvas_draw_rect(CTX_wm_area(C), CTX_wm_region(C));
}

rcti moodboard_canvas_draw_rect(const ScrArea *area, ARegion *region)
{
  rcti canvas = {0, region->winx, 0, region->winy};
  if (area->spacetype == SPACE_VIEW3D && region->regiontype == RGN_TYPE_TOOL_PROPS) {
    rcti panel;
    if (view3d_moodboard_drawer_panel_rect_for(
            area, region, view3d_moodboard_drawer_runtime_amount(region), &panel))
    {
      canvas = panel;
      BLI_rcti_translate(&canvas, -region->winrct.xmin, -region->winrct.ymin);
    }
  }
  return canvas;
}

rcti moodboard_canvas_controls_rect(const bContext *C)
{
  const ScrArea *area = CTX_wm_area(C);
  ARegion *region = CTX_wm_region(C);
  rcti canvas = moodboard_canvas_draw_rect(area, region);
  rcti edge;
  if (view3d_moodboard_drawer_is_overlay(area, region) &&
      view3d_moodboard_drawer_edge_rect_for(
          area, region, view3d_moodboard_drawer_runtime_amount(region), &edge))
  {
    canvas.xmin = std::max(canvas.xmin, edge.xmax - region->winrct.xmin + 1);
  }
  return canvas;
}

rcti moodboard_visible_canvas_rect(const bContext *C)
{
  return moodboard_visible_canvas_rect(CTX_wm_area(C), CTX_wm_region(C));
}

rcti moodboard_visible_canvas_rect(const ScrArea *area, ARegion *region)
{
  rcti canvas = moodboard_canvas_host_rect(area, region);
  const auto metrics = moodboard_chrome_metrics(UI_SCALE_FAC);
  BLI_rcti_pad(&canvas, -int(metrics.padding), -int(metrics.padding));
  canvas.xmin += int(metrics.control_height + metrics.gap);
  canvas.ymax -= int(metrics.control_height + metrics.gap);
  canvas.xmax = std::max(canvas.xmin, canvas.xmax);
  canvas.ymax = std::max(canvas.ymin, canvas.ymax);
  return canvas;
}

bool moodboard_canvas_point_is_interactive(const ScrArea *area,
                                          const ARegion *region,
                                          const int xy[2])
{
  const rcti content = moodboard_canvas_host_rect(area, const_cast<ARegion *>(region));
  return BLI_rcti_isect_pt(&content,
                         xy[0] - region->winrct.xmin,
                         xy[1] - region->winrct.ymin) &&
         !ui::region_block_find_mouse_over(region, xy, true);
}

bool moodboard_canvas_handler_poll(const wmWindow *win,
                                  const ScrArea *area,
                                  const ARegion *region,
                                  const wmEvent *event)
{
  if (!WM_event_handler_region_v2d_mask_poll(win, area, region, event)) {
    return false;
  }
  /* Preserve the View2D poll's mouse-leave and always-pass event contracts.
   * Hover cleanup and smooth-view timers must reach their handlers even over
   * chrome or with a stale pointer outside the canvas. Region shortcuts such
   * as N also stay available over chrome. Only pointer actions are gated. */
  if (ISKEYBOARD(event->type) || ISTIMER(event->type) ||
      ELEM(event->type, MOUSEMOVE, WINDEACTIVATE))
  {
    return true;
  }
  return moodboard_canvas_point_is_interactive(area, region, event->xy);
}

bool moodboard_node_controls_rect(const bContext *C, View2D *v2d, PointerRNA *node, rcti *r_rect)
{
  if (!RNA_boolean_get(node, "selected")) {
    return false;
  }
  PointerRNA scene = RNA_id_pointer_create(&CTX_data_scene(C)->id);
  char active[MIXIE_GRAPH_ID_BUF], id[MIXIE_GRAPH_ID_BUF];
  mixie_rna_string_get_clamped(&scene, "mixie_moodboard_active_node_id", active, sizeof(active));
  mixie_rna_string_get_clamped(node, "node_id", id, sizeof(id));
  /* Shift-select keeps a single active owner; box-select has no inspector. */
  if (active[0] == '\0' || !STREQ(active, id)) {
    return false;
  }
  rctf card;
  card.xmin = RNA_float_get(node, "position_x");
  card.ymin = RNA_float_get(node, "position_y");
  card.xmax = card.xmin + RNA_float_get(node, "width");
  card.ymax = card.ymin + RNA_float_get(node, "height");
  rcti card_region;
  if (!moodboard_view_rect_to_region(v2d, CTX_wm_region(C), card, &card_region)) {
    return false;
  }
  /* The CARD's own on-screen size decides whether the controls fit, not the
   * slice of it a sidebar or the Zen drawer happens to leave uncovered. The
   * minimum used to be measured after clipping, so pushing a card a little
   * under the sidebar took its visible width below the threshold and removed
   * the prompt, Generate AND Settings in one step, leaving a selected node
   * that still reads "Click this block to type a prompt" and has nothing to
   * click. */
  if (BLI_rcti_size_x(&card_region) <
          std::max(MOODBOARD_GRAPH_CONTROLS_MIN_PX_X, int(186.0f * UI_SCALE_FAC)) ||
      BLI_rcti_size_y(&card_region) <
          std::max(MOODBOARD_GRAPH_CONTROLS_MIN_PX_Y, int(150 * UI_SCALE_FAC)))
  {
    return false;
  }
  const rcti canvas = moodboard_canvas_draw_rect(C);
  if (!BLI_rcti_isect(&card_region, &canvas, nullptr)) {
    return false;
  }
  /* Visibility never changes layout. The native block clips painting and
   * hit targets to the canvas after laying out the whole card. */
  *r_rect = card_region;
  return true;
}

}  // namespace blender::ed::mixie
