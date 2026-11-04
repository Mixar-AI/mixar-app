/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Selecting and dragging a canvas frame.
 *
 * This operator sits AHEAD of the graph and media select items in the space
 * keymap and PASSES THROUGH whenever the press did not land on a frame's
 * chrome, exactly as the graph item passes through off-card. That ordering is
 * what implements the universal selection model without touching the
 * 1200-line media operator:
 *
 * - Press the thick TOP STRIP or any BORDER  -> select and drag the FRAME
 *   (its members travel with it, via the shared drag set).
 * - Press the INTERIOR                       -> pass through, so a member
 *   takes the click and open space starts a marquee. This is the rule that
 *   matters most: clicking a thing inside a frame selects THAT THING.
 *
 * The old model was the inverse -- a plain click on a grouped image selected
 * the whole group, reaching the image itself needed a double-click, and
 * Shift+click on it did nothing at all.
 *
 * There is NO manual resize. A frame's rect follows what it holds: it grows to
 * keep a member the user drags outwards, and "Fit to Contents" wraps it back to
 * them. A hand-dragged grip was a second, competing way to say where a frame's
 * edges go, and it fought that automatic grow on every drag -- one had to win,
 * and the one the user never has to think about is the right winner.
 *
 * Renaming lives next door in mixie_moodboard_ops_rename_frame.cc (500-line
 * rule); a double-click on the title strip calls into it.
 */

#include "mixie_moodboard_ops_common.hh"

#include "BLI_rect.h"

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Frame Select / Move
 * \{ */

struct FrameMoveData {
  int index;
  bool moved;
  int initial_region_x;
  int initial_region_y;
  float initial_mouse_x;
  float initial_mouse_y;
  /* The frame's rect when the gesture began. The move is always derived from
   * THIS plus the running delta, never accumulated frame to frame, so a
   * dropped MOUSEMOVE cannot leave the rect out of step with the pointer. */
  rctf initial_rect;
  /* Everything else the selection holds, so a frame dragged as part of a
   * mixed selection carries the rest with it. */
  MoodboardDragSet drag;
};

static bool frame_pointer(PointerRNA *scene_ptr, const int index, PointerRNA *r_frame)
{
  PropertyRNA *frames = RNA_struct_find_property(scene_ptr, "mixie_moodboard_frames");
  if (!frames) {
    return false;
  }
  return RNA_property_collection_lookup_int(scene_ptr, frames, index, r_frame);
}

void moodboard_frames_request_reframe(bContext *C)
{
  /* Membership has exactly ONE definition and it is in Python
   * (`core/frames.resolve_membership`), so both drag ends -- this one and the
   * media/card ones -- go through the same operator rather than each carrying
   * its own copy of the centre-point rule. INTERNAL + no UNDO: the gesture's
   * own operator already pushed a step, and a second one would let Ctrl+Z
   * undo the membership without undoing the move that caused it.
   *
   * Membership is always STICKY and always GROWS the frame: a member nudged
   * past its frame's edge stays a member and the frame stretches to keep
   * covering it, which is what makes a frame a container rather than a
   * tripwire. Nothing asks for the other behaviour any more -- a frame has no
   * manual resize, which was the one gesture that needed a member RELEASED by
   * shrinking the rect past it. */
  wmOperatorType *ot = WM_operatortype_find("MIXIE_OT_moodboard_reframe", true);
  if (ot) {
    WM_operator_name_call_ptr(
        C, ot, blender::wm::OpCallContext::ExecDefault, nullptr, nullptr);
  }
}

static void frame_select_only(PointerRNA *scene_ptr, const int index)
{
  moodboard_deselect_all(scene_ptr);
  moodboard_graph_deselect_nodes(scene_ptr);
  PointerRNA frame;
  if (frame_pointer(scene_ptr, index, &frame)) {
    RNA_boolean_set(&frame, "selected", true);
  }
}

static wmOperatorStatus frame_select_invoke(bContext *C,
                                            wmOperator *op,
                                            const wmEvent *event)
{
  Scene *scene = CTX_data_scene(C);
  ARegion *region = CTX_wm_region(C);
  if (!scene || !region) {
    return OPERATOR_CANCELLED;
  }
  View2D *v2d = &region->v2d;
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);

  float mouse_x, mouse_y;
  ui::view2d_region_to_view(v2d, event->mval[0], event->mval[1], &mouse_x, &mouse_y);

  MoodboardFramePart part = MOODBOARD_FRAME_PART_NONE;
  rctf rect{};
  const int index = moodboard_find_frame_at(
      &scene_ptr, mouse_x, mouse_y, ui::view2d_scale_get_x(v2d), &part, &rect);

  /* Off every frame, or inside one away from its edges: not ours. Passing
   * through is what lets a member take the click and open space inside a
   * frame start a marquee -- press-drag on the interior is a box select, and
   * the way to MOVE a frame is to grab its border. */
  if (index < 0 || part == MOODBOARD_FRAME_PART_NONE ||
      part == MOODBOARD_FRAME_PART_INTERIOR)
  {
    return OPERATOR_PASS_THROUGH;
  }

  PointerRNA frame;
  if (!frame_pointer(&scene_ptr, index, &frame)) {
    return OPERATOR_PASS_THROUGH;
  }

  const bool extend = RNA_boolean_get(op->ptr, "extend");
  const bool already_selected = RNA_boolean_get(&frame, "selected");
  if (extend) {
    /* Shift/Cmd toggles, like every other kind on this canvas. A toggle is a
     * complete gesture: no modal, so releasing does not start a drag. */
    RNA_boolean_set(&frame, "selected", !already_selected);
    ED_area_tag_redraw(CTX_wm_area(C));
    return OPERATOR_FINISHED;
  }
  if (!already_selected) {
    /* An already-selected frame keeps the whole selection so a mixed drag can
     * begin -- the same "already selected, do nothing, allow drag" rule media
     * and cards follow. */
    frame_select_only(&scene_ptr, index);
  }
  ED_area_tag_redraw(CTX_wm_area(C));

  /* A double-click on the name strip renames, which is where a user who wants
   * to change a frame's label reaches first. */
  if (event->val == KM_DBL_CLICK && part == MOODBOARD_FRAME_PART_TOP) {
    wmOperatorType *ot = WM_operatortype_find("MIXIE_OT_moodboard_rename_frame", false);
    if (ot) {
      char frame_id[MIXIE_GRAPH_ID_BUF];
      mixie_rna_string_get_clamped(&frame, "frame_id", frame_id, sizeof(frame_id));
      PointerRNA props = WM_operator_properties_create_ptr(ot);
      RNA_string_set(&props, "frame_id", frame_id);
      WM_operator_name_call_ptr(
          C, ot, blender::wm::OpCallContext::ExecDefault, &props, event);
      WM_operator_properties_free(&props);
      return OPERATOR_FINISHED;
    }
  }

  FrameMoveData *data = MEM_new<FrameMoveData>("MoodboardFrameMove");
  data->index = index;
  data->moved = false;
  data->initial_region_x = event->mval[0];
  data->initial_region_y = event->mval[1];
  data->initial_mouse_x = mouse_x;
  data->initial_mouse_y = mouse_y;
  data->initial_rect = rect;
  /* Captured now, while the positions are the ones the user can see. The set
   * already expands a selected frame into its members
   * (`moodboard_item_frame_selected`), so the frame's contents travel without
   * this operator knowing anything about membership. */
  moodboard_drag_set_capture(&scene_ptr, MOODBOARD_DRAG_ALL, &data->drag);
  op->customdata = data;
  WM_event_add_modal_handler(C, op);
  return OPERATOR_RUNNING_MODAL;
}

static wmOperatorStatus frame_move_modal(bContext *C,
                                          wmOperator *op,
                                          const wmEvent *event,
                                          FrameMoveData *data,
                                          PointerRNA *scene_ptr,
                                          PointerRNA *frame,
                                          ARegion *region)
{
  if (event->type == MOUSEMOVE) {
    /* The same threshold every other drag on this canvas applies: a click
     * that wobbles a pixel is a click, not a nudge. */
    const int dx = event->mval[0] - data->initial_region_x;
    const int dy = event->mval[1] - data->initial_region_y;
    data->moved = data->moved ||
                  dx * dx + dy * dy >=
                      int(MOODBOARD_DRAG_THRESHOLD_PX * MOODBOARD_DRAG_THRESHOLD_PX);
    if (!data->moved) {
      return OPERATOR_RUNNING_MODAL;
    }
    float mouse_x, mouse_y;
    ui::view2d_region_to_view(
        &region->v2d, event->mval[0], event->mval[1], &mouse_x, &mouse_y);
    float new_x = data->initial_rect.xmin + mouse_x - data->initial_mouse_x;
    float new_y = data->initial_rect.ymin + mouse_y - data->initial_mouse_y;
    if (event->modifier & KM_CTRL) {
      /* Snap the FRAME's own corner, not the cursor, and move everything else
       * by the same delta -- so the arrangement inside keeps its shape and
       * only the anchor lands on the grid. One rule, shared with both other
       * drags on this canvas. */
      const float grid = MOODBOARD_SNAP_GRID;
      new_x = std::round(new_x / grid) * grid;
      new_y = std::round(new_y / grid) * grid;
    }
    moodboard_drag_set_apply(scene_ptr,
                             data->drag,
                             new_x - data->initial_rect.xmin,
                             new_y - data->initial_rect.ymin);
    RNA_float_set(frame, "position_x", new_x);
    RNA_float_set(frame, "position_y", new_y);
    ED_area_tag_redraw(CTX_wm_area(C));
    return OPERATOR_RUNNING_MODAL;
  }
  if (event->type == LEFTMOUSE && event->val == KM_RELEASE) {
    /* Deliberately NO reframe here. A frame that travelled must not swallow
     * whatever it passed over: its own members came with it and keep their
     * membership, and nothing else was part of the gesture. Membership is
     * re-resolved when an ITEM moves, or when the frame is RESIZED. */
    MEM_delete(data);
    op->customdata = nullptr;
    return OPERATOR_FINISHED;
  }
  if (ELEM(event->type, EVT_ESCKEY, RIGHTMOUSE)) {
    moodboard_drag_set_restore(scene_ptr, data->drag);
    RNA_float_set(frame, "position_x", data->initial_rect.xmin);
    RNA_float_set(frame, "position_y", data->initial_rect.ymin);
    MEM_delete(data);
    op->customdata = nullptr;
    ED_area_tag_redraw(CTX_wm_area(C));
    return OPERATOR_CANCELLED;
  }
  return OPERATOR_RUNNING_MODAL;
}

static wmOperatorStatus frame_select_modal(bContext *C,
                                            wmOperator *op,
                                            const wmEvent *event)
{
  FrameMoveData *data = static_cast<FrameMoveData *>(op->customdata);
  if (!data) {
    return OPERATOR_CANCELLED;
  }
  Scene *scene = CTX_data_scene(C);
  ARegion *region = CTX_wm_region(C);
  if (!scene || !region) {
    /* A modal outlives its invocation: a file load or an area close mid-drag
     * leaves the context without a scene or a region. CANCELLED runs
     * ot->cancel, which frees the customdata. */
    return OPERATOR_CANCELLED;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PointerRNA frame;
  if (!frame_pointer(&scene_ptr, data->index, &frame)) {
    /* The frame was deleted under the drag (an undo, another window). */
    return OPERATOR_CANCELLED;
  }

  return frame_move_modal(C, op, event, data, &scene_ptr, &frame, region);
}

static void frame_select_cancel(bContext * /*C*/, wmOperator *op)
{
  FrameMoveData *data = static_cast<FrameMoveData *>(op->customdata);
  if (data) {
    MEM_delete(data);
    op->customdata = nullptr;
  }
}

/** \} */

}  // namespace blender::ed::mixie


namespace blender {
void MIXIE_OT_moodboard_frame_select(wmOperatorType *ot)
{
  ot->name = "Select Moodboard Frame";
  ot->idname = "MIXIE_OT_moodboard_frame_select";
  ot->description =
      "Select a frame by its border or title strip and drag it with its "
      "contents";
  ot->invoke = blender::ed::mixie::frame_select_invoke;
  ot->modal = blender::ed::mixie::frame_select_modal;
  ot->cancel = blender::ed::mixie::frame_select_cancel;
  ot->poll = blender::ed::mixie::moodboard_poll;
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_BLOCKING;

  /* PROP_SKIP_SAVE, for the same load-bearing reason it is on the media and
   * card select operators: this is a REGISTER operator, so
   * `WM_operator_last_properties_init` refills any non-skip property the
   * invocation did not set from the previous run -- and the plain-click keymap
   * item sets nothing. Without the flag, ONE Shift-click would remember
   * `extend = true` and every later plain press would take the toggle branch,
   * which returns FINISHED and installs no modal: frames could no longer be
   * dragged at all. */
  PropertyRNA *prop = RNA_def_boolean(
      ot->srna,
      "extend",
      false,
      "Extend",
      "Toggle this frame in the existing selection instead of replacing it");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
}
}  // namespace blender
