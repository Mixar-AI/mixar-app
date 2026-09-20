/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Hit-testing for moodboard links, sockets, cards and embedded media.
 */

#include "mixie_draw_moodboard_intern.hh"
#include "mixie_moodboard_graph_geometry.hh"

#include "BLI_string.h"

namespace blender::ed::mixie {

static float point_segment_distance_squared(const float px,
                                            const float py,
                                            const float ax,
                                            const float ay,
                                            const float bx,
                                            const float by)
{
  const float dx = bx - ax;
  const float dy = by - ay;
  const float length_squared = dx * dx + dy * dy;
  const float t = length_squared > 0.0f ?
                      std::clamp(((px - ax) * dx + (py - ay) * dy) / length_squared,
                                 0.0f,
                                 1.0f) :
                      0.0f;
  const float offset_x = px - (ax + t * dx);
  const float offset_y = py - (ay + t * dy);
  return offset_x * offset_x + offset_y * offset_y;
}

int moodboard_find_link_under_mouse(PointerRNA *scene_ptr,
                                    View2D *v2d,
                                    const int mouse_region_x,
                                    const int mouse_region_y,
                                    const float max_distance_px)
{
  PropertyRNA *links = RNA_struct_find_property(scene_ptr, "mixie_moodboard_links");
  if (!links) {
    return -1;
  }
  float nearest = max_distance_px * max_distance_px;
  int nearest_index = -1;
  int index = 0;
  /* Same one-pass cache the draw path uses; without it each link re-scans the
   * whole image collection and re-acquires an ImBuf just to read an aspect. */
  MoodboardGraphCache cache;
  moodboard_graph_cache_build(scene_ptr, &cache);
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(scene_ptr, links, &iter);
  while (iter.valid) {
    float x1, y1, x2, y2;
    if (moodboard_graph_link_endpoints(scene_ptr, &iter.ptr, &x1, &y1, &x2, &y2, &cache)) {
      float coords[MOODBOARD_GRAPH_LINK_RESOLUTION + 1][2];
      moodboard_graph_link_curve_coords(x1, y1, x2, y2, coords);
      float previous_x, previous_y;
      ui::view2d_view_to_region_fl(v2d, coords[0][0], coords[0][1], &previous_x, &previous_y);
      for (int segment = 1; segment <= MOODBOARD_GRAPH_LINK_RESOLUTION; segment++) {
        float current_x, current_y;
        ui::view2d_view_to_region_fl(
            v2d, coords[segment][0], coords[segment][1], &current_x, &current_y);
        const float distance = point_segment_distance_squared(float(mouse_region_x),
                                                              float(mouse_region_y),
                                                              previous_x,
                                                              previous_y,
                                                              current_x,
                                                              current_y);
        if (distance <= nearest) {
          nearest = distance;
          nearest_index = index;
        }
        previous_x = current_x;
        previous_y = current_y;
      }
    }
    index++;
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
  return nearest_index;
}

static bool region_socket_hit(View2D *v2d,
                              const int mouse_x,
                              const int mouse_y,
                              const float socket_x,
                              const float socket_y,
                              const bool output = false)
{
  float region_x, region_y;
  ui::view2d_view_to_region_fl(v2d, socket_x, socket_y, &region_x, &region_y);
  const float dx = float(mouse_x) - region_x;
  const float dy = float(mouse_y) - region_y;
  /* Painting and QA read these same UI-scaled metrics. The hit disc includes
   * the visible socket rim and keeps small, zoomed-out sockets reachable. */
  const float radius = moodboard_socket_hit_radius_px(v2d, output);
  return dx * dx + dy * dy <= radius * radius;
}

static bool collection_output_hit(PointerRNA *scene_ptr,
                                  View2D *v2d,
                                  const char *collection_name,
                                  const int mouse_x,
                                  const int mouse_y,
                                  MoodboardGraphSocketHit *r_hit)
{
  PropertyRNA *collection = RNA_struct_find_property(scene_ptr, collection_name);
  const int count = collection ? RNA_property_collection_length(scene_ptr, collection) : 0;
  for (int index = count - 1; index >= 0; index--) {
    PointerRNA node;
    RNA_property_collection_lookup_int(scene_ptr, collection, index, &node);
    rctf rect{};
    rect.xmin = RNA_float_get(&node, "position_x");
    rect.ymin = RNA_float_get(&node, "position_y");
    rect.xmax = rect.xmin + RNA_float_get(&node, "width");
    rect.ymax = rect.ymin + RNA_float_get(&node, "height");
    const float output_x = rect.xmax + MOODBOARD_GRAPH_SOCKET_OFFSET;
    if (region_socket_hit(v2d, mouse_x, mouse_y, output_x, BLI_rctf_cent_y(&rect), true)) {
      mixie_rna_string_get_clamped(
          &node, "node_id", r_hit->node_id, sizeof(r_hit->node_id));
      BLI_strncpy(r_hit->socket_id, "output", sizeof(r_hit->socket_id));
      r_hit->x = output_x;
      r_hit->y = BLI_rctf_cent_y(&rect);
      return true;
    }
  }
  return false;
}

bool moodboard_find_output_socket_under_mouse(PointerRNA *scene_ptr,
                                               View2D *v2d,
                                               const int mouse_x,
                                               const int mouse_y,
                                               MoodboardGraphSocketHit *r_hit)
{
  if (collection_output_hit(scene_ptr,
                            v2d,
                            "mixie_moodboard_action_nodes",
                            mouse_x,
                            mouse_y,
                            r_hit) ||
      collection_output_hit(scene_ptr,
                            v2d,
                            "mixie_moodboard_asset_nodes",
                            mouse_x,
                            mouse_y,
                            r_hit))
  {
    return true;
  }
  PropertyRNA *media = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  const int count = media ? RNA_property_collection_length(scene_ptr, media) : 0;
  for (int index = count - 1; index >= 0; index--) {
    PointerRNA item;
    RNA_property_collection_lookup_int(scene_ptr, media, index, &item);
    PropertyRNA *embedded = RNA_struct_find_property(&item, "embedded_node_id");
    if (embedded && RNA_property_string_length(&item, embedded) > 0) {
      continue;
    }
    /* Media that never got a graph id (a board saved before the migration ran)
     * has no addressable output: a hit would start a link drag whose
     * from_node_id is empty, minting a permanently unresolvable link. */
    PropertyRNA *id_prop = RNA_struct_find_property(&item, "node_id");
    if (!id_prop || RNA_property_string_length(&item, id_prop) == 0) {
      continue;
    }
    rctf rect{};
    if (moodboard_graph_media_rect(&item, &rect) &&
        region_socket_hit(v2d,
                          mouse_x,
                          mouse_y,
                          rect.xmax + MOODBOARD_GRAPH_SOCKET_OFFSET,
                          BLI_rctf_cent_y(&rect),
                          true))
    {
      mixie_rna_string_get_clamped(
          &item, "node_id", r_hit->node_id, sizeof(r_hit->node_id));
      BLI_strncpy(r_hit->socket_id, "output", sizeof(r_hit->socket_id));
      r_hit->x = rect.xmax + MOODBOARD_GRAPH_SOCKET_OFFSET;
      r_hit->y = BLI_rctf_cent_y(&rect);
      return true;
    }
  }
  return false;
}

bool moodboard_find_input_socket_under_mouse(PointerRNA *scene_ptr,
                                              View2D *v2d,
                                              const int mouse_x,
                                              const int mouse_y,
                                              MoodboardGraphSocketHit *r_hit)
{
  bool found = false;
  float nearest_distance = 0.0f;
  PropertyRNA *nodes = RNA_struct_find_property(scene_ptr, "mixie_moodboard_action_nodes");
  const int node_count = nodes ? RNA_property_collection_length(scene_ptr, nodes) : 0;
  for (int node_index = node_count - 1; node_index >= 0; node_index--) {
    PointerRNA node;
    RNA_property_collection_lookup_int(scene_ptr, nodes, node_index, &node);
    PropertyRNA *sockets = RNA_struct_find_property(&node, "input_sockets");
    const int socket_count = sockets ? RNA_property_collection_length(&node, sockets) : 0;
    for (int socket_index = 0; socket_index < socket_count; socket_index++) {
      float x, y;
      if (!moodboard_graph_action_socket_position(&node, socket_index, &x, &y)) {
        continue;
      }
      if (!region_socket_hit(v2d, mouse_x, mouse_y, x, y)) {
        continue;
      }
      float region_x, region_y;
      ui::view2d_view_to_region_fl(v2d, x, y, &region_x, &region_y);
      const float dx = float(mouse_x) - region_x;
      const float dy = float(mouse_y) - region_y;
      const float distance = dx * dx + dy * dy;
      /* Generous hit discs can overlap at overview. Choose the closest
       * centre; strict comparison retains reverse node order on a tie. */
      if (found && distance >= nearest_distance) {
        continue;
      }
      PointerRNA socket;
      RNA_property_collection_lookup_int(&node, sockets, socket_index, &socket);
      mixie_rna_string_get_clamped(
          &node, "node_id", r_hit->node_id, sizeof(r_hit->node_id));
      mixie_rna_string_get_clamped(
          &socket, "socket_id", r_hit->socket_id, sizeof(r_hit->socket_id));
      r_hit->x = x;
      r_hit->y = y;
      nearest_distance = distance;
      found = true;
    }
  }
  return found;
}

static int find_node_in_collection(PointerRNA *scene_ptr,
                                   const char *collection_name,
                                   const float mouse_x,
                                   const float mouse_y,
                                   rctf *r_rect)
{
  PropertyRNA *collection = RNA_struct_find_property(scene_ptr, collection_name);
  const int count = collection ? RNA_property_collection_length(scene_ptr, collection) : 0;
  for (int index = count - 1; index >= 0; index--) {
    PointerRNA node;
    RNA_property_collection_lookup_int(scene_ptr, collection, index, &node);
    rctf rect{};
    rect.xmin = RNA_float_get(&node, "position_x");
    rect.ymin = RNA_float_get(&node, "position_y");
    rect.xmax = rect.xmin + RNA_float_get(&node, "width");
    rect.ymax = rect.ymin + RNA_float_get(&node, "height");
    if (BLI_rctf_isect_pt(&rect, mouse_x, mouse_y)) {
      if (r_rect) {
        *r_rect = rect;
      }
      return index;
    }
  }
  return -1;
}

bool moodboard_graph_node_id_selected(PointerRNA *scene_ptr, const char *node_id)
{
  /* The graph cache is keyed by node id and holds only rects, while `selected`
   * lives on the item itself -- and an id can belong to a media item, an action
   * node or an asset node, so all three collections are searched. */
  if (!node_id || node_id[0] == '\0') {
    return false;
  }
  for (const char *collection_name : {"mixie_moodboard_images",
                                      "mixie_moodboard_action_nodes",
                                      "mixie_moodboard_asset_nodes"})
  {
    PropertyRNA *prop = RNA_struct_find_property(scene_ptr, collection_name);
    const int count = prop ? RNA_property_collection_length(scene_ptr, prop) : 0;
    for (int index = 0; index < count; index++) {
      PointerRNA item;
      RNA_property_collection_lookup_int(scene_ptr, prop, index, &item);
      char id[MIXIE_GRAPH_ID_BUF];
      mixie_rna_string_get_clamped(&item, "node_id", id, sizeof(id));
      if (STREQ(id, node_id)) {
        return RNA_boolean_get(&item, "selected");
      }
    }
  }
  return false;
}

bool moodboard_node_is_mask_detail(PointerRNA *node)
{
  /* The enum persists as an index, so resolve the identifier rather than
   * comparing raw values — a catalog/enum reorder must not silently make a
   * different node type unresizable. */
  if (!node) {
    return false;
  }
  PropertyRNA *prop = RNA_struct_find_property(node, "action_type");
  if (!prop) {
    return false;
  }
  const char *id = nullptr;
  RNA_property_enum_identifier(nullptr, node, prop, RNA_property_enum_get(node, prop), &id);
  return id && STREQ(id, "MASK_DETAIL");
}

void moodboard_graph_node_preview_bounds(const rctf &node_rect, rctf *r_bounds)
{
  /* Single source of truth for the preview rect. The draw path, the floating
   * toolbar and the playback hit-test all need it; recomputing the inset in
   * each would let the play button's pixels and its click region drift apart
   * without anything failing loudly. */
  r_bounds->xmin = node_rect.xmin + MOODBOARD_GRAPH_PREVIEW_INSET;
  r_bounds->xmax = node_rect.xmax - MOODBOARD_GRAPH_PREVIEW_INSET;
  r_bounds->ymin = node_rect.ymin + MOODBOARD_GRAPH_PREVIEW_INSET;
  r_bounds->ymax = node_rect.ymax - MOODBOARD_GRAPH_PREVIEW_INSET;
}

int moodboard_find_embedded_media_index(PointerRNA *scene_ptr, const char *node_id)
{
  if (!node_id || node_id[0] == '\0') {
    return -1;
  }
  PropertyRNA *media = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  const int count = media ? RNA_property_collection_length(scene_ptr, media) : 0;
  for (int index = 0; index < count; index++) {
    PointerRNA item;
    RNA_property_collection_lookup_int(scene_ptr, media, index, &item);
    if (moodboard_graph_string_prop_equals(&item, "embedded_node_id", node_id)) {
      return index;
    }
  }
  return -1;
}

int moodboard_find_node_preview_video_under_mouse(PointerRNA *scene_ptr,
                                                 const float mouse_x,
                                                 const float mouse_y,
                                                 rctf *r_node_rect)
{
  /* Returns an index into `mixie_moodboard_images`, the same space
   * `moodboard_toggle_video_playback` and the hover monitor use. Returning a
   * node index here would make the hover monitor stop playback on the first
   * mouse-move, because it compares against `playback.item_index`. */
  rctf rect{};
  const int node_index = moodboard_find_action_node_under_mouse(
      scene_ptr, mouse_x, mouse_y, &rect);
  if (node_index < 0) {
    return -1;
  }
  PropertyRNA *nodes = RNA_struct_find_property(scene_ptr, "mixie_moodboard_action_nodes");
  PointerRNA node;
  if (!nodes || !RNA_property_collection_lookup_int(scene_ptr, nodes, node_index, &node)) {
    return -1;
  }
  char node_id[MIXIE_GRAPH_ID_BUF];
  mixie_rna_string_get_clamped(&node, "node_id", node_id, sizeof(node_id));
  const int media_index = moodboard_find_embedded_media_index(scene_ptr, node_id);
  if (media_index < 0 || !moodboard_item_is_video(scene_ptr, media_index)) {
    return -1;
  }
  if (r_node_rect) {
    *r_node_rect = rect;
  }
  return media_index;
}

int moodboard_find_action_node_under_mouse(PointerRNA *scene_ptr,
                                           const float mouse_x,
                                           const float mouse_y,
                                           rctf *r_rect)
{
  return find_node_in_collection(
      scene_ptr, "mixie_moodboard_action_nodes", mouse_x, mouse_y, r_rect);
}

int moodboard_find_asset_node_under_mouse(PointerRNA *scene_ptr,
                                          const float mouse_x,
                                          const float mouse_y,
                                          rctf *r_rect)
{
  return find_node_in_collection(
      scene_ptr, "mixie_moodboard_asset_nodes", mouse_x, mouse_y, r_rect);
}

}  // namespace blender::ed::mixie
