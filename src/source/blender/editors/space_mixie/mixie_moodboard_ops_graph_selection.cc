/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief What is selected in the moodboard graph, and how that is set.
 *
 * Split out of `mixie_moodboard_ops_graph.cc` when that unit crossed the
 * 500-line rule. These are the primitives -- deselect everything, select one
 * node, select one link -- and they are deliberately free of the select
 * operator's modal state: the context-menu and resize units call them too.
 */

#include "mixie_moodboard_ops_common.hh"

namespace blender::ed::mixie {

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

bool moodboard_graph_node_pointer(PointerRNA *scene_ptr,
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
  if (!moodboard_graph_node_pointer(scene_ptr, kind, index, &node)) {
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

}  // namespace blender::ed::mixie
