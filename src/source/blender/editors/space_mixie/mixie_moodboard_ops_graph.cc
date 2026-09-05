/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Selection, movement, and context dispatch for moodboard graph cards.
 */

#include "mixie_moodboard_ops_common.hh"

#include "BLI_rect.h"

namespace blender::ed::mixie {

struct GraphMoveData {
  bool link_drag;
  bool moved;
  bool resize;
  /* The drag began by pulling an EXISTING link off an input, so releasing on
   * empty canvas means "leave it disconnected", not "offer me a new node". */
  bool detached;
  GraphNodeKind kind;
  int index;
  float initial_mouse_x;
  float initial_mouse_y;
  float initial_x;
  float initial_y;
  /* Every OTHER selected item this drag carries -- cards, pictures and text
   * boxes alike. The grabbed card keeps its own initial_x/y above because the
   * snap anchors on it. */
  MoodboardDragSet drag;
  MoodboardGraphResizeState resize_state;
  int initial_region_x;
  int initial_region_y;
  char from_node_id[MIXIE_GRAPH_ID_BUF];
};

static const char *graph_collection_name(const GraphNodeKind kind)
{
  return kind == GRAPH_ACTION ? "mixie_moodboard_action_nodes" :
                                "mixie_moodboard_asset_nodes";
}

void moodboard_graph_deselect_nodes(PointerRNA *scene_ptr)
{
  for (const char *collection_name : {"mixie_moodboard_action_nodes",
                                      "mixie_moodboard_asset_nodes",
                                      "mixie_moodboard_links"})
  {
    PropertyRNA *collection = RNA_struct_find_property(scene_ptr, collection_name);
    if (!collection) {
      continue;
    }
    CollectionPropertyIterator iter{};
    RNA_property_collection_begin(scene_ptr, collection, &iter);
    while (iter.valid) {
      PropertyRNA *selected = RNA_struct_find_property(&iter.ptr, "selected");
      if (selected) {
        RNA_property_boolean_set(&iter.ptr, selected, false);
      }
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }
  RNA_string_set(scene_ptr, "mixie_moodboard_active_node_id", "");
}

bool moodboard_graph_select_link(PointerRNA *scene_ptr, const int index)
{
  PropertyRNA *links = RNA_struct_find_property(scene_ptr, "mixie_moodboard_links");
  PointerRNA link;
  if (!links || !RNA_property_collection_lookup_int(scene_ptr, links, index, &link)) {
    return false;
  }
  moodboard_deselect_all(scene_ptr);
  moodboard_graph_deselect_nodes(scene_ptr);
  RNA_boolean_set(&link, "selected", true);
  return true;
}

static bool graph_node_pointer(PointerRNA *scene_ptr,
                               const GraphNodeKind kind,
                               const int index,
                               PointerRNA *r_node)
{
  PropertyRNA *collection = RNA_struct_find_property(scene_ptr, graph_collection_name(kind));
  return collection &&
         RNA_property_collection_lookup_int(scene_ptr, collection, index, r_node);
}

void moodboard_graph_select_node(PointerRNA *scene_ptr,
                                 const GraphNodeKind kind,
                                 const int index,
                                 PointerRNA *r_node)
{
  moodboard_deselect_all(scene_ptr);
  moodboard_graph_deselect_nodes(scene_ptr);
  PointerRNA node;
  if (!graph_node_pointer(scene_ptr, kind, index, &node)) {
    return;
  }
  RNA_boolean_set(&node, "selected", true);
  char node_id[MIXIE_GRAPH_ID_BUF];
  mixie_rna_string_get_clamped(&node, "node_id", node_id, sizeof(node_id));
  RNA_string_set(scene_ptr, "mixie_moodboard_active_node_id", node_id);
  if (r_node) {
    *r_node = node;
  }
}

static wmOperatorStatus call_node_operator(bContext *C,
                                           const char *operator_idname,
                                           const char *node_id,
                                           const wmEvent *event)
{
  wmOperatorType *ot = WM_operatortype_find(operator_idname, false);
  if (!ot) {
    return OPERATOR_CANCELLED;
  }
  PointerRNA props;
  WM_operator_properties_create_ptr(&props, ot);
  RNA_string_set(&props, "node_id", node_id);
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, blender::wm::OpCallContext::ExecDefault, &props, event);
  WM_operator_properties_free(&props);
  return status;
}

/* Begin dragging a noodle that hangs from `from_node_id`'s output. Shared by
 * the output handle (a new link) and by detaching an existing one from an input
 * -- the two differ only in whether a link was just removed, which is what the
 * release has to know. */
static wmOperatorStatus start_link_drag(bContext *C,
                                        wmOperator *op,
                                        Scene *scene,
                                        PointerRNA *scene_ptr,
                                        const wmEvent *event,
                                        const char *from_node_id,
                                        const float anchor_x,
                                        const float anchor_y,
                                        const bool detached)
{
  GraphMoveData *data = MEM_new<GraphMoveData>("MoodboardGraphLinkDrag");
  data->link_drag = true;
  data->moved = false;
  data->resize = false;
  data->detached = detached;
  data->initial_region_x = event->mval[0];
  data->initial_region_y = event->mval[1];
  BLI_strncpy(data->from_node_id, from_node_id, sizeof(data->from_node_id));
  op->customdata = data;
  moodboard_graph_clear_link_drop_anchor(scene_ptr);
  moodboard_graph_link_drag_begin(scene, anchor_x, anchor_y);
  WM_event_add_modal_handler(C, op);
  ED_area_tag_redraw(CTX_wm_area(C));
  return OPERATOR_RUNNING_MODAL;
}

static wmOperatorStatus graph_select_invoke(bContext *C,
                                            wmOperator *op,
                                            const wmEvent *event)
{
  Scene *scene = CTX_data_scene(C);
  ARegion *region = CTX_wm_region(C);
  if (!scene || !region) {
    return OPERATOR_PASS_THROUGH;
  }
  const bool extend = RNA_boolean_get(op->ptr, "extend");
  float mouse_x, mouse_y;
  UI_view2d_region_to_view(&region->v2d, event->mval[0], event->mval[1], &mouse_x, &mouse_y);
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  if (RNA_struct_find_property(&scene_ptr, "mixie_moodboard_context_x")) {
    RNA_float_set(&scene_ptr, "mixie_moodboard_context_x", mouse_x);
    RNA_float_set(&scene_ptr, "mixie_moodboard_context_y", mouse_y);
  }

  /* A CONNECTED input socket is a handle for its link. Checked before anything
   * else, because the socket sits on the card and any later test swallows it. */
  char detached_from[MIXIE_GRAPH_ID_BUF];
  if (!extend && moodboard_graph_detach_input(
                     C, &scene_ptr, &region->v2d, event, detached_from,
                     sizeof(detached_from)))
  {
    return start_link_drag(
        C, op, scene, &scene_ptr, event, detached_from, mouse_x, mouse_y, true);
  }

  MoodboardGraphSocketHit output{};
  if (!extend &&
      moodboard_find_output_socket_under_mouse(
          &scene_ptr, &region->v2d, event->mval[0], event->mval[1], &output))
  {
    return start_link_drag(
        C, op, scene, &scene_ptr, event, output.node_id, output.x, output.y, false);
  }

  GraphNodeKind kind = GRAPH_ACTION;
  rctf node_rect{};
  int index = moodboard_find_action_node_under_mouse(&scene_ptr, mouse_x, mouse_y, &node_rect);
  if (index < 0) {
    kind = GRAPH_ASSET;
    index = moodboard_find_asset_node_under_mouse(&scene_ptr, mouse_x, mouse_y, &node_rect);
  }
  if (index < 0) {
    if (extend) {
      /* Shift-click on anything but a card belongs to the media extend
       * operator bound behind this one. */
      return OPERATOR_PASS_THROUGH;
    }
    if (moodboard_find_image_under_mouse(
            &scene_ptr, mouse_x, mouse_y, nullptr, nullptr, nullptr, nullptr, nullptr) >= 0 ||
        moodboard_find_textbox_under_mouse(
            &scene_ptr, mouse_x, mouse_y, nullptr, nullptr, nullptr, nullptr) >= 0)
    {
      return OPERATOR_PASS_THROUGH;
    }
    index = moodboard_find_link_under_mouse(
        &scene_ptr, &region->v2d, event->mval[0], event->mval[1], 9.0f);
    if (index < 0 || !moodboard_graph_select_link(&scene_ptr, index)) {
      return OPERATOR_PASS_THROUGH;
    }
    ED_area_tag_redraw(CTX_wm_area(C));
    return OPERATOR_FINISHED;
  }

  if (extend) {
    /* Toggle this card in the existing selection (media stays selected too, so
     * a mixed sweep can feed group actions), matching Shift-click on media. */
    PointerRNA node;
    if (!graph_node_pointer(&scene_ptr, kind, index, &node)) {
      return OPERATOR_CANCELLED;
    }
    const bool now_selected = !RNA_boolean_get(&node, "selected");
    RNA_boolean_set(&node, "selected", now_selected);
    char node_id[MIXIE_GRAPH_ID_BUF];
    mixie_rna_string_get_clamped(&node, "node_id", node_id, sizeof(node_id));
    char active_id[MIXIE_GRAPH_ID_BUF];
    mixie_rna_string_get_clamped(
        &scene_ptr, "mixie_moodboard_active_node_id", active_id, sizeof(active_id));
    if (now_selected) {
      RNA_string_set(&scene_ptr, "mixie_moodboard_active_node_id", node_id);
    }
    else if (STREQ(active_id, node_id)) {
      RNA_string_set(&scene_ptr, "mixie_moodboard_active_node_id", "");
    }
    ED_area_tag_redraw(CTX_wm_area(C));
    return OPERATOR_FINISHED;
  }

  PointerRNA node;
  if (!graph_node_pointer(&scene_ptr, kind, index, &node)) {
    return OPERATOR_CANCELLED;
  }
  /* A plain press on a card that is ALREADY selected keeps the selection and
   * only makes this card active -- the same rule media follows ("if already
   * selected, do nothing, allow drag"). Reselecting unconditionally wiped the
   * rest of the selection before the drag could start, which is why a picture
   * and a card selected together came apart the moment the card was grabbed. */
  if (RNA_boolean_get(&node, "selected")) {
    char active_id[MIXIE_GRAPH_ID_BUF];
    mixie_rna_string_get_clamped(&node, "node_id", active_id, sizeof(active_id));
    RNA_string_set(&scene_ptr, "mixie_moodboard_active_node_id", active_id);
  }
  else {
    moodboard_graph_select_node(&scene_ptr, kind, index, &node);
  }
  ED_area_tag_redraw(CTX_wm_area(C));

  char node_id[MIXIE_GRAPH_ID_BUF];
  mixie_rna_string_get_clamped(&node, "node_id", node_id, sizeof(node_id));
  if (kind == GRAPH_ASSET) {
    if (event->val == KM_DBL_CLICK) {
      return call_node_operator(
          C, "MIXIE_OT_moodboard_select_asset_objects", node_id, event);
    }
  }
  else {
    /* Bottom-right grip resizes the card, like resizing an image tile. Checked
     * before the playback and move paths so a corner drag resizes rather than
     * moving the node or toggling its video. */
    MoodboardGraphResizeState resize_state{};
    if (moodboard_graph_resize_grip_hit(&node, node_rect, mouse_x, mouse_y, &resize_state)) {
      GraphMoveData *rdata = MEM_new<GraphMoveData>("MoodboardGraphResize");
      rdata->link_drag = false;
      rdata->moved = false;
      rdata->resize = true;
      rdata->detached = false;
      rdata->kind = kind;
      rdata->index = index;
      rdata->resize_state = resize_state;
      op->customdata = rdata;
      WM_event_add_modal_handler(C, op);
      return OPERATOR_RUNNING_MODAL;
    }
    /* A generated movie lives inside its node and is excluded from the
     * standalone-tile hit-test that normally starts playback, so the node owns
     * that gesture. Handled before the move modal is installed: that branch has
     * no drag threshold and would slide the card on the click's first move. */
    wmOperatorStatus playback = OPERATOR_PASS_THROUGH;
    if (moodboard_graph_node_video_click(
            C, &scene_ptr, &region->v2d, node_rect, node_id, mouse_x, mouse_y,
            event->val == KM_DBL_CLICK, op->reports, &playback))
    {
      return playback;
    }
  }

  GraphMoveData *data = MEM_new<GraphMoveData>("MoodboardGraphMove");
  data->link_drag = false;
  data->moved = false;
  data->resize = false;
  data->detached = false;
  data->kind = kind;
  data->index = index;
  data->initial_mouse_x = mouse_x;
  data->initial_mouse_y = mouse_y;
  data->initial_region_x = event->mval[0];
  data->initial_region_y = event->mval[1];
  data->initial_x = RNA_float_get(&node, "position_x");
  data->initial_y = RNA_float_get(&node, "position_y");
  /* Everything else the selection holds travels with this card -- other cards,
   * pictures and text boxes. Captured now, while the positions are still the
   * ones the user sees. */
  moodboard_drag_set_capture(&scene_ptr, MOODBOARD_DRAG_ALL, &data->drag);
  op->customdata = data;
  WM_event_add_modal_handler(C, op);
  return OPERATOR_RUNNING_MODAL;
}

static wmOperatorStatus graph_select_modal(bContext *C,
                                           wmOperator *op,
                                           const wmEvent *event)
{
  GraphMoveData *data = static_cast<GraphMoveData *>(op->customdata);
  if (!data) {
    return OPERATOR_CANCELLED;
  }
  Scene *scene = CTX_data_scene(C);
  ARegion *region = CTX_wm_region(C);
  if (!scene || !region) {
    /* invoke() guards these, but a modal outlives its invocation: a file load
     * or area close mid-drag leaves the context without a scene or region.
     * Returning CANCELLED runs ot->cancel, which frees customdata and ends
     * the link-drag preview. */
    return OPERATOR_CANCELLED;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  if (data->link_drag) {
    if (event->type == MOUSEMOVE) {
      const int dx = event->mval[0] - data->initial_region_x;
      const int dy = event->mval[1] - data->initial_region_y;
      data->moved = data->moved ||
                    dx * dx + dy * dy >=
                        int(MOODBOARD_DRAG_THRESHOLD_PX * MOODBOARD_DRAG_THRESHOLD_PX);
      if (!data->moved) {
        return OPERATOR_RUNNING_MODAL;
      }
      float mouse_x, mouse_y;
      UI_view2d_region_to_view(
          &region->v2d, event->mval[0], event->mval[1], &mouse_x, &mouse_y);
      moodboard_graph_link_drag_update(scene, mouse_x, mouse_y);
      ED_area_tag_redraw(CTX_wm_area(C));
      return OPERATOR_RUNNING_MODAL;
    }
    if (event->type == LEFTMOUSE && event->val == KM_RELEASE) {
      /* Read everything the resolution needs before the drag data is freed. */
      char from_node_id[MIXIE_GRAPH_ID_BUF];
      BLI_strncpy(from_node_id, data->from_node_id, sizeof(from_node_id));
      const bool moved = data->moved;
      const bool detached = data->detached;
      moodboard_graph_link_drag_end(scene);
      MEM_delete(data);
      op->customdata = nullptr;
      ED_area_tag_redraw(CTX_wm_area(C));
      return moodboard_graph_link_release(
          C, &scene_ptr, &region->v2d, event, from_node_id, moved, detached);
    }
    if (ELEM(event->type, EVT_ESCKEY, RIGHTMOUSE)) {
      moodboard_graph_link_drag_end(scene);
      MEM_delete(data);
      op->customdata = nullptr;
      ED_area_tag_redraw(CTX_wm_area(C));
      return OPERATOR_CANCELLED;
    }
    return OPERATOR_RUNNING_MODAL;
  }
  PointerRNA node;
  if (!graph_node_pointer(&scene_ptr, data->kind, data->index, &node)) {
    return OPERATOR_CANCELLED;
  }

  if (data->resize) {
    bool done = false;
    const wmOperatorStatus status = moodboard_graph_resize_modal(
        C, region, &node, data->resize_state, event, &done);
    if (done) {
      MEM_delete(data);
      op->customdata = nullptr;
    }
    return status;
  }

  if (event->type == MOUSEMOVE) {
    /* Same threshold every media drag applies: a click that wobbles a pixel is
     * a click, not a request to nudge the card. */
    const int dx = event->mval[0] - data->initial_region_x;
    const int dy = event->mval[1] - data->initial_region_y;
    data->moved = data->moved ||
                  dx * dx + dy * dy >=
                      int(MOODBOARD_DRAG_THRESHOLD_PX * MOODBOARD_DRAG_THRESHOLD_PX);
    if (!data->moved) {
      return OPERATOR_RUNNING_MODAL;
    }
    float mouse_x, mouse_y;
    UI_view2d_region_to_view(
        &region->v2d, event->mval[0], event->mval[1], &mouse_x, &mouse_y);
    float new_x = data->initial_x + mouse_x - data->initial_mouse_x;
    float new_y = data->initial_y + mouse_y - data->initial_mouse_y;
    if (event->modifier & KM_CTRL) {
      /* Snap the GRABBED card's own corner to the canvas grid, not the cursor:
       * the user is placing the CARD, and snapping the pointer would leave it
       * off-grid by wherever they happened to grab it. Everything else in the
       * selection then moves by the same delta, so the arrangement keeps its
       * shape and only the anchor lands on the grid -- the media drag's rule. */
      const float grid = MOODBOARD_SNAP_GRID;
      new_x = std::round(new_x / grid) * grid;
      new_y = std::round(new_y / grid) * grid;
    }
    /* The rest of the selection moves by the delta the grabbed card just took,
     * so the arrangement keeps its shape. The set contains the grabbed card too
     * and would place it identically; it is still written explicitly below, so
     * that a card missing from the capture is at worst a selection bug and
     * never a card that has stopped following the mouse. */
    moodboard_drag_set_apply(
        &scene_ptr, data->drag, new_x - data->initial_x, new_y - data->initial_y);
    RNA_float_set(&node, "position_x", new_x);
    RNA_float_set(&node, "position_y", new_y);
    ED_area_tag_redraw(CTX_wm_area(C));
    return OPERATOR_RUNNING_MODAL;
  }
  if (event->type == LEFTMOUSE && event->val == KM_RELEASE) {
    MEM_delete(data);
    op->customdata = nullptr;
    return OPERATOR_FINISHED;
  }
  if (ELEM(event->type, EVT_ESCKEY, RIGHTMOUSE)) {
    moodboard_drag_set_restore(&scene_ptr, data->drag);
    RNA_float_set(&node, "position_x", data->initial_x);
    RNA_float_set(&node, "position_y", data->initial_y);
    MEM_delete(data);
    op->customdata = nullptr;
    ED_area_tag_redraw(CTX_wm_area(C));
    return OPERATOR_CANCELLED;
  }
  return OPERATOR_RUNNING_MODAL;
}

static void graph_select_cancel(bContext *C, wmOperator *op)
{
  GraphMoveData *data = static_cast<GraphMoveData *>(op->customdata);
  if (data) {
    if (data->link_drag) {
      moodboard_graph_link_drag_end(CTX_data_scene(C));
    }
    MEM_delete(data);
    op->customdata = nullptr;
  }
}

}  // namespace blender::ed::mixie

void MIXIE_OT_moodboard_graph_select(wmOperatorType *ot)
{
  ot->name = "Select Moodboard Graph Node";
  ot->idname = "MIXIE_OT_moodboard_graph_select";
  ot->description = "Select and move an inference or 3D asset node";
  ot->invoke = blender::ed::mixie::graph_select_invoke;
  ot->modal = blender::ed::mixie::graph_select_modal;
  ot->cancel = blender::ed::mixie::graph_select_cancel;
  ot->poll = blender::ed::mixie::moodboard_poll;
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_BLOCKING;
  /* PROP_SKIP_SAVE is load-bearing, exactly as on the media select operator.
   * This is a REGISTER operator, so `WM_operator_last_properties_init` refills
   * any non-skip property the invocation did not set from the previous run --
   * and the plain-click keymap item sets nothing. Without this, ONE Shift or
   * Cmd click remembered `extend = true`, every later plain click took the
   * toggle branch (which returns FINISHED and installs no modal), and cards
   * could no longer be dragged at all: a press just selected or deselected
   * them. Media kept working only because its operator already had the flag. */
  PropertyRNA *prop = RNA_def_boolean(
      ot->srna,
      "extend",
      false,
      "Extend",
      "Toggle this card in the existing selection instead of replacing it");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
}
