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

enum GraphNodeKind { GRAPH_ACTION = 0, GRAPH_ASSET = 1 };

struct GraphMoveData {
  bool link_drag;
  bool moved;
  GraphNodeKind kind;
  int index;
  float initial_mouse_x;
  float initial_mouse_y;
  float initial_x;
  float initial_y;
  int initial_region_x;
  int initial_region_y;
  char from_node_id[MIXIE_GRAPH_ID_BUF];
};

static const char *graph_collection_name(const GraphNodeKind kind)
{
  return kind == GRAPH_ACTION ? "mixie_moodboard_action_nodes" :
                                "mixie_moodboard_asset_nodes";
}

static void deselect_graph_nodes(PointerRNA *scene_ptr)
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

static bool select_graph_link(PointerRNA *scene_ptr, const int index)
{
  PropertyRNA *links = RNA_struct_find_property(scene_ptr, "mixie_moodboard_links");
  PointerRNA link;
  if (!links || !RNA_property_collection_lookup_int(scene_ptr, links, index, &link)) {
    return false;
  }
  moodboard_deselect_all(scene_ptr);
  deselect_graph_nodes(scene_ptr);
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

static void select_graph_node(PointerRNA *scene_ptr,
                              const GraphNodeKind kind,
                              const int index,
                              PointerRNA *r_node)
{
  moodboard_deselect_all(scene_ptr);
  deselect_graph_nodes(scene_ptr);
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

  MoodboardGraphSocketHit output{};
  if (!extend &&
      moodboard_find_output_socket_under_mouse(
          &scene_ptr, &region->v2d, event->mval[0], event->mval[1], &output))
  {
    GraphMoveData *data = MEM_new<GraphMoveData>("MoodboardGraphLinkDrag");
    data->link_drag = true;
    data->moved = false;
    data->initial_region_x = event->mval[0];
    data->initial_region_y = event->mval[1];
    BLI_strncpy(data->from_node_id, output.node_id, sizeof(data->from_node_id));
    op->customdata = data;
    moodboard_graph_clear_link_drop_anchor(&scene_ptr);
    moodboard_graph_link_drag_begin(scene, output.x, output.y);
    WM_event_add_modal_handler(C, op);
    ED_area_tag_redraw(CTX_wm_area(C));
    return OPERATOR_RUNNING_MODAL;
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
    if (index < 0 || !select_graph_link(&scene_ptr, index)) {
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
  select_graph_node(&scene_ptr, kind, index, &node);
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
    /* A generated movie lives inside its node, so it is excluded from the
     * standalone-tile hit-test that normally starts playback. Toggle it here
     * from the same gestures an uploaded movie accepts — the centred
     * play/pause affordance, or a double-click anywhere on the tile. */
    const int media_index = moodboard_find_embedded_media_index(&scene_ptr, node_id);
    if (media_index >= 0 && moodboard_item_is_video(&scene_ptr, media_index)) {
      rctf preview_bounds{};
      moodboard_graph_node_preview_bounds(node_rect, &preview_bounds);
      const float view_scale = std::max(UI_view2d_scale_get_x(&region->v2d), 0.001f);
      const float play_radius = MOODBOARD_VIDEO_PLAY_RADIUS_PX / view_scale;
      const float delta_x = mouse_x - BLI_rctf_cent_x(&preview_bounds);
      const float delta_y = mouse_y - BLI_rctf_cent_y(&preview_bounds);
      const bool play_button_hit = delta_x * delta_x + delta_y * delta_y <=
                                   play_radius * play_radius;
      if (event->val == KM_DBL_CLICK || play_button_hit) {
        /* Return before the move modal is installed: the node-move branch has
         * no drag threshold and would slide the card on the first mouse-move
         * of the same click. */
        return moodboard_toggle_video_playback(C, &scene_ptr, media_index, op->reports) ?
                   OPERATOR_FINISHED :
                   OPERATOR_CANCELLED;
      }
    }
  }

  GraphMoveData *data = MEM_new<GraphMoveData>("MoodboardGraphMove");
  data->link_drag = false;
  data->moved = false;
  data->kind = kind;
  data->index = index;
  data->initial_mouse_x = mouse_x;
  data->initial_mouse_y = mouse_y;
  data->initial_region_x = event->mval[0];
  data->initial_region_y = event->mval[1];
  data->initial_x = RNA_float_get(&node, "position_x");
  data->initial_y = RNA_float_get(&node, "position_y");
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
      moodboard_graph_link_drag_end(scene);
      MEM_delete(data);
      op->customdata = nullptr;
      ED_area_tag_redraw(CTX_wm_area(C));
      return moodboard_graph_link_release(
          C, &scene_ptr, &region->v2d, event, from_node_id, moved);
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
    RNA_float_set(&node, "position_x", data->initial_x + mouse_x - data->initial_mouse_x);
    RNA_float_set(&node, "position_y", data->initial_y + mouse_y - data->initial_mouse_y);
    ED_area_tag_redraw(CTX_wm_area(C));
    return OPERATOR_RUNNING_MODAL;
  }
  if (event->type == LEFTMOUSE && event->val == KM_RELEASE) {
    MEM_delete(data);
    op->customdata = nullptr;
    return OPERATOR_FINISHED;
  }
  if (ELEM(event->type, EVT_ESCKEY, RIGHTMOUSE)) {
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

static wmOperatorStatus graph_context_invoke(bContext *C,
                                             wmOperator * /*op*/,
                                             const wmEvent *event)
{
  Scene *scene = CTX_data_scene(C);
  ARegion *region = CTX_wm_region(C);
  if (!scene || !region) {
    return OPERATOR_CANCELLED;
  }
  float mouse_x, mouse_y;
  UI_view2d_region_to_view(&region->v2d, event->mval[0], event->mval[1], &mouse_x, &mouse_y);
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  if (RNA_struct_find_property(&scene_ptr, "mixie_moodboard_context_x")) {
    RNA_float_set(&scene_ptr, "mixie_moodboard_context_x", mouse_x);
    RNA_float_set(&scene_ptr, "mixie_moodboard_context_y", mouse_y);
  }

  moodboard_graph_clear_link_drop_anchor(&scene_ptr);

  rctf rect{};
  int index = moodboard_find_action_node_under_mouse(&scene_ptr, mouse_x, mouse_y, &rect);
  if (index >= 0) {
    select_graph_node(&scene_ptr, GRAPH_ACTION, index, nullptr);
  }
  else {
    index = moodboard_find_asset_node_under_mouse(&scene_ptr, mouse_x, mouse_y, &rect);
    if (index >= 0) {
      select_graph_node(&scene_ptr, GRAPH_ASSET, index, nullptr);
    }
    else {
      float x, y, scale, width, height;
      index = moodboard_find_image_under_mouse(
          &scene_ptr, mouse_x, mouse_y, &x, &y, &scale, &width, &height);
      if (index >= 0) {
        PropertyRNA *images = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
        PointerRNA image;
        RNA_property_collection_lookup_int(&scene_ptr, images, index, &image);
        if (!RNA_boolean_get(&image, "selected")) {
          moodboard_deselect_all(&scene_ptr);
          RNA_boolean_set(&image, "selected", true);
        }
        deselect_graph_nodes(&scene_ptr);
      }
      else {
        index = moodboard_find_link_under_mouse(
            &scene_ptr, &region->v2d, event->mval[0], event->mval[1], 9.0f);
        if (index >= 0) {
          select_graph_link(&scene_ptr, index);
        }
      }
    }
  }
  ED_area_tag_redraw(CTX_wm_area(C));

  wmOperatorType *menu_type = WM_operatortype_find("WM_OT_call_menu", false);
  if (!menu_type) {
    return OPERATOR_CANCELLED;
  }
  PointerRNA props;
  WM_operator_properties_create_ptr(&props, menu_type);
  RNA_string_set(&props, "name", "MIXIE_MT_moodboard_context_menu");
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, menu_type, blender::wm::OpCallContext::InvokeRegionWin, &props, event);
  WM_operator_properties_free(&props);
  return status;
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
  RNA_def_boolean(ot->srna,
                  "extend",
                  false,
                  "Extend",
                  "Toggle this card in the existing selection instead of replacing it");
}

void MIXIE_OT_moodboard_context_menu(wmOperatorType *ot)
{
  ot->name = "Moodboard Context Menu";
  ot->idname = "MIXIE_OT_moodboard_context_menu";
  ot->description = "Resolve the node under the pointer and open its context menu";
  ot->invoke = blender::ed::mixie::graph_context_invoke;
  ot->poll = blender::ed::mixie::moodboard_poll;
}
