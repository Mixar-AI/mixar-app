/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Resizing a moodboard node card from its bottom-right grip.
 *
 * Split out of #mixie_moodboard_ops_graph.cc (500-line rule). The gesture is
 * self-contained: the grip hit-test, the drag math and the Esc restore all
 * work off #MoodboardGraphResizeState, so the graph operator only has to route
 * events here and own the allocation.
 */

#include "mixie_moodboard_ops_common.hh"

#include "BLI_rect.h"

namespace blender::ed::mixie {

bool moodboard_graph_resize_grip_hit(PointerRNA *node,
                                     const rctf &node_rect,
                                     const float mouse_x,
                                     const float mouse_y,
                                     MoodboardGraphResizeState *r_state)
{
  /* MASK_DETAIL has a fixed square card (controls over an in-card mask
   * thumbnail), so it is deliberately not resizable and shows no grip. */
  if (moodboard_node_is_mask_detail(node)) {
    return false;
  }
  /* The grip box is CANVAS units, exactly like the triangle the draw pass
   * paints, so the two can't drift apart at any zoom. */
  const float grip = MOODBOARD_NODE_RESIZE_GRIP;
  if (mouse_x < node_rect.xmax - grip || mouse_x > node_rect.xmax ||
      mouse_y < node_rect.ymin || mouse_y > node_rect.ymin + grip)
  {
    return false;
  }
  r_state->initial_mouse_x = mouse_x;
  r_state->initial_mouse_y = mouse_y;
  r_state->initial_y = RNA_float_get(node, "position_y");
  r_state->initial_width = RNA_float_get(node, "width");
  r_state->initial_height = RNA_float_get(node, "height");
  return true;
}

static void moodboard_graph_resize_drag(PointerRNA *node,
                                        const MoodboardGraphResizeState &state,
                                        const float mouse_x,
                                        const float mouse_y)
{
  /* Height follows the card's aspect AT DRAG START, so the ratio never jumps
   * mid-gesture. `refresh_node_height` re-derives it from the result image on
   * the next refresh and preserves the width the user settled on. */
  const float aspect = state.initial_width > 0.0f ?
                           state.initial_height / state.initial_width :
                           1.0f;
  /* Grow on a rightward OR downward drag, whichever is larger; the vertical
   * delta maps back to a width delta through the aspect. */
  const float dx = mouse_x - state.initial_mouse_x;
  const float dy_down = state.initial_mouse_y - mouse_y;
  float new_w = state.initial_width + std::max(dx, dy_down / std::max(aspect, 0.01f));
  new_w = std::clamp(new_w, MOODBOARD_ACTION_NODE_MIN_W, MOODBOARD_ACTION_NODE_MAX_W);
  const float new_h = new_w * aspect;
  /* The TOP edge is held fixed, so the card grows down-right from where the
   * user grabbed it rather than sliding out from under the cursor. */
  const float top = state.initial_y + state.initial_height;
  RNA_float_set(node, "width", new_w);
  RNA_float_set(node, "height", new_h);
  RNA_float_set(node, "position_y", top - new_h);
}

static void moodboard_graph_resize_restore(PointerRNA *node,
                                           const MoodboardGraphResizeState &state)
{
  RNA_float_set(node, "width", state.initial_width);
  RNA_float_set(node, "height", state.initial_height);
  RNA_float_set(node, "position_y", state.initial_y);
}

wmOperatorStatus moodboard_graph_resize_modal(bContext *C,
                                              ARegion *region,
                                              PointerRNA *node,
                                              const MoodboardGraphResizeState &state,
                                              const wmEvent *event,
                                              bool *r_done)
{
  *r_done = false;
  if (event->type == MOUSEMOVE) {
    float mouse_x, mouse_y;
    UI_view2d_region_to_view(
        &region->v2d, event->mval[0], event->mval[1], &mouse_x, &mouse_y);
    moodboard_graph_resize_drag(node, state, mouse_x, mouse_y);
    ED_area_tag_redraw(CTX_wm_area(C));
    return OPERATOR_RUNNING_MODAL;
  }
  if (event->type == LEFTMOUSE && event->val == KM_RELEASE) {
    *r_done = true;
    return OPERATOR_FINISHED;
  }
  if (ELEM(event->type, EVT_ESCKEY, RIGHTMOUSE)) {
    moodboard_graph_resize_restore(node, state);
    ED_area_tag_redraw(CTX_wm_area(C));
    *r_done = true;
    return OPERATOR_CANCELLED;
  }
  return OPERATOR_RUNNING_MODAL;
}

}  // namespace blender::ed::mixie
