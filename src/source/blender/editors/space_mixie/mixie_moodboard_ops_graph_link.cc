/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief What a released moodboard noodle means.
 *
 * Split out of #mixie_moodboard_ops_graph.cc: the drop resolution is one
 * decision with several outcomes (connect to a socket, connect to a card,
 * offer the continuation menu, or stand down), and it owns the scene state
 * that carries the drop point into the Python-drawn menu.
 */

#include "mixie_moodboard_ops_common.hh"

namespace blender::ed::mixie {

static wmOperatorStatus call_connect_operator(bContext *C,
                                              const char *from_node_id,
                                              const MoodboardGraphSocketHit &target,
                                              const wmEvent *event)
{
  wmOperatorType *ot = WM_operatortype_find("MIXIE_OT_moodboard_connect_nodes", false);
  if (!ot) {
    return OPERATOR_CANCELLED;
  }
  PointerRNA props;
  WM_operator_properties_create_ptr(&props, ot);
  RNA_string_set(&props, "from_node_id", from_node_id);
  RNA_string_set(&props, "to_node_id", target.node_id);
  /* Empty when the drop landed on a card rather than one of its sockets: the
   * operator reads that as "the first free compatible input". */
  RNA_string_set(&props, "to_socket", target.socket_id);
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, ot, blender::wm::OpCallContext::ExecDefault, &props, event);
  WM_operator_properties_free(&props);
  return status;
}

/**
 * Record where a released noodle landed, so the continuation menu it opens can
 * drop the node it creates under the cursor instead of beside its source.
 *
 * `WM_OT_call_menu` hands the drawing to Python, so the scene is the only
 * channel between this modal and the menu that builds the buttons.
 */
static void set_link_drop_anchor(PointerRNA *scene_ptr,
                                 const bool active,
                                 const float x,
                                 const float y)
{
  PropertyRNA *flag = RNA_struct_find_property(scene_ptr, "mixie_moodboard_link_drop_active");
  if (!flag) {
    return;
  }
  RNA_property_boolean_set(scene_ptr, flag, active);
  if (active) {
    RNA_float_set(scene_ptr, "mixie_moodboard_link_drop_x", x);
    RNA_float_set(scene_ptr, "mixie_moodboard_link_drop_y", y);
  }
}

void moodboard_graph_clear_link_drop_anchor(PointerRNA *scene_ptr)
{
  set_link_drop_anchor(scene_ptr, false, 0.0f, 0.0f);
}

static wmOperatorStatus call_output_menu(bContext *C,
                                         PointerRNA *scene_ptr,
                                         const char *source_node_id,
                                         const wmEvent *event)
{
  PropertyRNA *source = RNA_struct_find_property(scene_ptr, "mixie_moodboard_output_source_id");
  wmOperatorType *menu_type = WM_operatortype_find("WM_OT_call_menu", false);
  if (!source || !menu_type) {
    return OPERATOR_CANCELLED;
  }
  RNA_property_string_set(scene_ptr, source, source_node_id);
  PointerRNA props;
  WM_operator_properties_create_ptr(&props, menu_type);
  RNA_string_set(&props, "name", "MIXIE_MT_moodboard_output_menu");
  const wmOperatorStatus status = WM_operator_name_call_ptr(
      C, menu_type, blender::wm::OpCallContext::InvokeRegionWin, &props, event);
  WM_operator_properties_free(&props);
  return status;
}

/** Whether a released noodle landed on something that already owns the canvas. */
static bool graph_drop_is_occupied(PointerRNA *scene_ptr, const float x, const float y)
{
  rctf rect{};
  if (moodboard_find_asset_node_under_mouse(scene_ptr, x, y, &rect) >= 0) {
    return true;
  }
  if (moodboard_find_image_under_mouse(
          scene_ptr, x, y, nullptr, nullptr, nullptr, nullptr, nullptr) >= 0)
  {
    return true;
  }
  return moodboard_find_textbox_under_mouse(
             scene_ptr, x, y, nullptr, nullptr, nullptr, nullptr) >= 0;
}

/** Resolve the action card under the drop into a socket-less connect target. */
static bool graph_drop_card_target(PointerRNA *scene_ptr,
                                   const float x,
                                   const float y,
                                   MoodboardGraphSocketHit *r_target)
{
  rctf rect{};
  const int index = moodboard_find_action_node_under_mouse(scene_ptr, x, y, &rect);
  PropertyRNA *nodes = RNA_struct_find_property(scene_ptr, "mixie_moodboard_action_nodes");
  PointerRNA node;
  if (index < 0 || !nodes ||
      !RNA_property_collection_lookup_int(scene_ptr, nodes, index, &node))
  {
    return false;
  }
  *r_target = MoodboardGraphSocketHit{};
  mixie_rna_string_get_clamped(&node, "node_id", r_target->node_id, sizeof(r_target->node_id));
  return true;
}

wmOperatorStatus moodboard_graph_link_release(bContext *C,
                                              PointerRNA *scene_ptr,
                                              View2D *v2d,
                                              const wmEvent *event,
                                              const char *from_node_id,
                                              const bool moved)
{
  MoodboardGraphSocketHit target{};
  if (moodboard_find_input_socket_under_mouse(
          scene_ptr, v2d, event->mval[0], event->mval[1], &target))
  {
    return call_connect_operator(C, from_node_id, target, event);
  }
  if (!moved) {
    /* A plain click on the output handle: no noodle was pulled anywhere, so
     * the menu keeps placing its node beside the source. The anchor was
     * cleared when this drag began. */
    return call_output_menu(C, scene_ptr, from_node_id, event);
  }

  float drop_x, drop_y;
  ui::view2d_region_to_view(v2d, event->mval[0], event->mval[1], &drop_x, &drop_y);

  /* Missed the sockets but landed on an inference card: continue into it
   * through its first free compatible input, the way the socket drop would
   * have. */
  MoodboardGraphSocketHit card{};
  if (graph_drop_card_target(scene_ptr, drop_x, drop_y, &card)) {
    /* Released back onto the node it started from: nothing to connect and
     * nowhere to put a card, so end quietly rather than reporting a cycle the
     * user never asked for. */
    if (STREQ(card.node_id, from_node_id)) {
      return OPERATOR_CANCELLED;
    }
    return call_connect_operator(C, from_node_id, card, event);
  }
  /* Anything else already owning this spot leaves nowhere to put a new card,
   * so only genuinely free canvas offers the continuation menu. */
  if (graph_drop_is_occupied(scene_ptr, drop_x, drop_y)) {
    return OPERATOR_CANCELLED;
  }
  /* Dragging a noodle into open canvas IS the request for a next node: offer
   * the same continuation menu the output handle opens, anchored so the node
   * it creates lands where the noodle was released. */
  set_link_drop_anchor(scene_ptr, true, drop_x, drop_y);
  return call_output_menu(C, scene_ptr, from_node_id, event);
}

}  // namespace blender::ed::mixie
