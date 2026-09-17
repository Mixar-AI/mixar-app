/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Resizing a moodboard node card from one of its corner handles.
 *
 * Split out of #mixie_moodboard_ops_graph.cc (500-line rule). The gesture is
 * self-contained: the handle hit-test, the drag math and the Esc restore all
 * work off #MoodboardGraphResizeState, so the graph operator only has to route
 * events here and own the allocation.
 *
 * The geometry and the rule come from the SHARED resize unit
 * (`moodboard_resize_handle_*`), which is the whole point: a card and a
 * reference picture are resized by the same gesture, with the same four corner
 * squares, so the canvas has one way to scale a thing rather than two. A card
 * used to carry a single bottom-right wedge that only ever grew down-right,
 * while a picture had eight handles anchored on the opposite corner.
 */

#include "mixie_moodboard_ops_common.hh"

#include "BLI_rect.h"

namespace blender::ed::mixie {

bool moodboard_graph_resize_handle_hit(PointerRNA *node,
                                       const rctf &node_rect,
                                       const float mouse_x,
                                       const float mouse_y,
                                       const float view_scale,
                                       MoodboardGraphResizeState *r_state)
{
  /* MASK_DETAIL has a fixed square card (controls over an in-card mask
   * thumbnail), so it is deliberately not resizable and shows no handles. */
  if (moodboard_node_is_mask_detail(node)) {
    return false;
  }
  /* The same pixel tolerance a picture's handles use, converted through the
   * view scale: the squares are a fixed screen size, so their grab zone has to
   * be one too, or a zoomed-out card's corners become unclickable. */
  const float tolerance = MOODBOARD_HANDLE_TOLERANCE_PX / std::max(view_scale, 0.001f);
  const int handle = moodboard_resize_handle_at(node_rect, mouse_x, mouse_y, tolerance);
  if (handle == -1) {
    return false;
  }
  r_state->handle = handle;
  r_state->initial_rect = node_rect;
  return true;
}

static void moodboard_graph_resize_drag(PointerRNA *node,
                                        const MoodboardGraphResizeState &state,
                                        const float mouse_x,
                                        const float mouse_y)
{
  /* Uniform scale about the anchored corner, exactly as a picture scales --
   * one factor from the anchor's diagonal, so the card's aspect AT DRAG START
   * is what it keeps and the ratio never jumps mid-gesture.
   * `refresh_node_height` re-derives the height from the result image on the
   * next refresh and preserves the width the user settled on. */
  const float initial_w = BLI_rctf_size_x(&state.initial_rect);
  const float initial_h = BLI_rctf_size_y(&state.initial_rect);
  const float aspect = initial_w > 0.0f ? initial_h / initial_w : 1.0f;
  const float factor = moodboard_resize_scale_factor(
      state.initial_rect, state.handle, mouse_x, mouse_y);
  const float new_w = std::clamp(
      initial_w * factor, MOODBOARD_ACTION_NODE_MIN_W, MOODBOARD_ACTION_NODE_MAX_W);
  rctf placed;
  moodboard_resize_place(state.initial_rect, state.handle, new_w, new_w * aspect, &placed);
  RNA_float_set(node, "width", BLI_rctf_size_x(&placed));
  RNA_float_set(node, "height", BLI_rctf_size_y(&placed));
  RNA_float_set(node, "position_x", placed.xmin);
  RNA_float_set(node, "position_y", placed.ymin);
}

static void moodboard_graph_resize_restore(PointerRNA *node,
                                           const MoodboardGraphResizeState &state)
{
  RNA_float_set(node, "width", BLI_rctf_size_x(&state.initial_rect));
  RNA_float_set(node, "height", BLI_rctf_size_y(&state.initial_rect));
  RNA_float_set(node, "position_x", state.initial_rect.xmin);
  RNA_float_set(node, "position_y", state.initial_rect.ymin);
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
    ui::view2d_region_to_view(
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
