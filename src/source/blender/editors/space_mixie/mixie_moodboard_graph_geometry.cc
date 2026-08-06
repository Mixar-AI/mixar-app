/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Shared geometry and hit-testing for moodboard graph sockets and links.
 */

#include "mixie_draw_moodboard_intern.hh"

#include "BKE_curve.hh"

#include "BLI_string.h"

namespace blender::ed::mixie {

void mixie_rna_property_string_get_clamped(PointerRNA *ptr,
                                           PropertyRNA *prop,
                                           char *dst,
                                           const int dst_maxncpy)
{
  if (!dst || dst_maxncpy <= 0) {
    return;
  }
  dst[0] = '\0';
  if (!prop || RNA_property_type(prop) != PROP_STRING) {
    return;
  }
  const int length = RNA_property_string_length(ptr, prop);
  if (length < dst_maxncpy) {
    /* Fits, including the terminator: no allocation on the common path. */
    RNA_property_string_get(ptr, prop, dst);
    return;
  }
  int allocated_length = 0;
  char *value = RNA_property_string_get_alloc(ptr, prop, nullptr, 0, &allocated_length);
  if (value) {
    BLI_strncpy(dst, value, dst_maxncpy);
    MEM_freeN(value);
  }
}

void mixie_rna_string_get_clamped(PointerRNA *ptr,
                                  const char *name,
                                  char *dst,
                                  const int dst_maxncpy)
{
  mixie_rna_property_string_get_clamped(
      ptr, RNA_struct_find_property(ptr, name), dst, dst_maxncpy);
}

struct LinkDragPreview {
  /* Keyed on the scene's session UID rather than its pointer: a raw Scene *
   * kept in a static outlives the scene across a file load, and a freshly
   * allocated Scene landing on the same address would resurrect a stale drag
   * preview. Session UIDs are never reused within a session. */
  uint32_t scene_uid = 0;
  bool active = false;
  float x1 = 0.0f;
  float y1 = 0.0f;
  float x2 = 0.0f;
  float y2 = 0.0f;
};

static LinkDragPreview g_link_drag;

static uint32_t scene_drag_uid(const Scene *scene)
{
  return scene ? scene->id.session_uid : 0;
}

static bool string_prop_equals(PointerRNA *ptr, const char *name, const char *value)
{
  PropertyRNA *prop = RNA_struct_find_property(ptr, name);
  if (!prop || RNA_property_type(prop) != PROP_STRING) {
    return false;
  }
  /* Compare by length first so an over-long stored value cannot match a
   * shorter id purely because the copy truncated to it. */
  const int length = RNA_property_string_length(ptr, prop);
  if (length != int(strlen(value))) {
    return false;
  }
  char buffer[MIXIE_GRAPH_ID_BUF];
  mixie_rna_property_string_get_clamped(ptr, prop, buffer, sizeof(buffer));
  return STREQ(buffer, value);
}

static bool rect_from_collection(PointerRNA *scene_ptr,
                                 const char *collection_name,
                                 const char *node_id,
                                 rctf *r_rect,
                                 PointerRNA *r_item = nullptr)
{
  PropertyRNA *collection = RNA_struct_find_property(scene_ptr, collection_name);
  if (!collection) {
    return false;
  }
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(scene_ptr, collection, &iter);
  while (iter.valid) {
    if (string_prop_equals(&iter.ptr, "node_id", node_id)) {
      r_rect->xmin = RNA_float_get(&iter.ptr, "position_x");
      r_rect->ymin = RNA_float_get(&iter.ptr, "position_y");
      r_rect->xmax = r_rect->xmin + RNA_float_get(&iter.ptr, "width");
      r_rect->ymax = r_rect->ymin + RNA_float_get(&iter.ptr, "height");
      if (r_item) {
        *r_item = iter.ptr;
      }
      RNA_property_collection_end(&iter);
      return true;
    }
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
  return false;
}

static bool media_rect(PointerRNA *item, rctf *r_rect)
{
  PointerRNA image_ptr = RNA_pointer_get(item, "image");
  Image *image = static_cast<Image *>(image_ptr.data);
  if (!image) {
    return false;
  }
  float aspect = 1.0f;
  void *lock = nullptr;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  if (ibuf && ibuf->x > 0) {
    aspect = float(ibuf->y) / float(ibuf->x);
  }
  BKE_image_release_ibuf(image, ibuf, lock);
  const float width = MOODBOARD_IMAGE_BASE_SIZE * RNA_float_get(item, "scale");
  r_rect->xmin = RNA_float_get(item, "position_x");
  r_rect->ymin = RNA_float_get(item, "position_y");
  r_rect->xmax = r_rect->xmin + width;
  r_rect->ymax = r_rect->ymin + width * aspect;
  return true;
}

static bool media_rect_from_id(PointerRNA *scene_ptr, const char *node_id, rctf *r_rect)
{
  PropertyRNA *items = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  if (!items) {
    return false;
  }
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(scene_ptr, items, &iter);
  while (iter.valid) {
    if (string_prop_equals(&iter.ptr, "node_id", node_id) && media_rect(&iter.ptr, r_rect)) {
      RNA_property_collection_end(&iter);
      return true;
    }
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
  return false;
}

static bool output_position(PointerRNA *scene_ptr, const char *node_id, float *r_x, float *r_y)
{
  rctf rect{};
  if (media_rect_from_id(scene_ptr, node_id, &rect) ||
      rect_from_collection(scene_ptr, "mixie_moodboard_action_nodes", node_id, &rect) ||
      rect_from_collection(scene_ptr, "mixie_moodboard_asset_nodes", node_id, &rect))
  {
    *r_x = rect.xmax + MOODBOARD_GRAPH_SOCKET_OFFSET;
    *r_y = BLI_rctf_cent_y(&rect);
    return true;
  }
  return false;
}

bool moodboard_graph_action_socket_position(PointerRNA *node,
                                            const int socket_index,
                                            float *r_x,
                                            float *r_y)
{
  PropertyRNA *sockets = RNA_struct_find_property(node, "input_sockets");
  const int count = sockets ? RNA_property_collection_length(node, sockets) : 0;
  if (socket_index < 0 || socket_index >= count) {
    return false;
  }
  int visible_count = 0;
  int visible_index = -1;
  for (int index = 0; index < count; index++) {
    PointerRNA socket;
    RNA_property_collection_lookup_int(node, sockets, index, &socket);
    if (!RNA_boolean_get(&socket, "visible")) {
      continue;
    }
    if (index == socket_index) {
      visible_index = visible_count;
    }
    visible_count++;
  }
  if (visible_index < 0) {
    return false;
  }
  const float height = RNA_float_get(node, "height");
  const float available = std::max(height - 48.0f, 0.0f);
  const float spacing = visible_count > 1 ?
                            std::min(36.0f, available / float(visible_count - 1)) :
                            0.0f;
  *r_x = RNA_float_get(node, "position_x") - MOODBOARD_GRAPH_SOCKET_OFFSET;
  *r_y = RNA_float_get(node, "position_y") + height * 0.5f +
         spacing * (float(visible_count - 1) * 0.5f - float(visible_index));
  return true;
}

static bool socket_position_in_node(PointerRNA *node,
                                    const char *socket_id,
                                    float *r_x,
                                    float *r_y)
{
  PropertyRNA *sockets = RNA_struct_find_property(node, "input_sockets");
  const int count = sockets ? RNA_property_collection_length(node, sockets) : 0;
  for (int index = 0; index < count; index++) {
    PointerRNA socket;
    RNA_property_collection_lookup_int(node, sockets, index, &socket);
    if (string_prop_equals(&socket, "socket_id", socket_id)) {
      return moodboard_graph_action_socket_position(node, index, r_x, r_y);
    }
  }
  return false;
}

static bool input_position(PointerRNA *scene_ptr,
                           const char *node_id,
                           const char *socket_id,
                           float *r_x,
                           float *r_y)
{
  rctf rect{};
  PointerRNA node;
  if (!rect_from_collection(
          scene_ptr, "mixie_moodboard_action_nodes", node_id, &rect, &node))
  {
    return false;
  }
  return socket_position_in_node(&node, socket_id, r_x, r_y);
}

static float link_handle_length(const float x1, const float x2)
{
  return std::max(fabsf(x2 - x1) * 0.45f, 90.0f);
}

void moodboard_graph_link_bounds(
    const float x1, const float y1, const float x2, const float y2, rctf *r_bounds)
{
  /* A Bezier is contained by the convex hull of its control points. The
   * x-handles reach outside the endpoint span whenever the link runs backwards
   * (x2 < x1), so a bound taken from the endpoints alone would clip a curve
   * that is still on screen. The y handles are flat (y1, y1, y2, y2). */
  const float handle = link_handle_length(x1, x2);
  r_bounds->xmin = std::min({x1, x2, x2 - handle});
  r_bounds->xmax = std::max({x1, x2, x1 + handle});
  r_bounds->ymin = std::min(y1, y2);
  r_bounds->ymax = std::max(y1, y2);
}

void moodboard_graph_link_curve_coords(
    const float x1,
    const float y1,
    const float x2,
    const float y2,
    float r_coords[MOODBOARD_GRAPH_LINK_RESOLUTION + 1][2])
{
  const float handle = link_handle_length(x1, x2);
  BKE_curve_forward_diff_bezier(x1,
                                x1 + handle,
                                x2 - handle,
                                x2,
                                &r_coords[0][0],
                                MOODBOARD_GRAPH_LINK_RESOLUTION,
                                sizeof(r_coords[0]));
  BKE_curve_forward_diff_bezier(y1,
                                y1,
                                y2,
                                y2,
                                &r_coords[0][1],
                                MOODBOARD_GRAPH_LINK_RESOLUTION,
                                sizeof(r_coords[0]));
}

void moodboard_graph_cache_build(PointerRNA *scene_ptr, MoodboardGraphCache *cache)
{
  /* One pass over the three collections, reused by every link. Resolving each
   * endpoint independently meant re-scanning the whole image collection per
   * link — and acquiring that image's ImBuf again just to read its aspect —
   * which made link drawing O(links * images) with a locked buffer acquire in
   * the inner loop, every redraw. */
  cache->outputs.clear();
  cache->action_nodes.clear();

  PropertyRNA *media = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  if (media) {
    CollectionPropertyIterator iter{};
    RNA_property_collection_begin(scene_ptr, media, &iter);
    while (iter.valid) {
      char node_id[MIXIE_GRAPH_ID_BUF];
      mixie_rna_string_get_clamped(&iter.ptr, "node_id", node_id, sizeof(node_id));
      rctf rect{};
      if (node_id[0] != '\0' && media_rect(&iter.ptr, &rect)) {
        cache->outputs.add_overwrite(node_id, rect);
      }
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }

  for (const char *collection_name : {"mixie_moodboard_action_nodes",
                                      "mixie_moodboard_asset_nodes"})
  {
    PropertyRNA *collection = RNA_struct_find_property(scene_ptr, collection_name);
    if (!collection) {
      continue;
    }
    const bool is_action = STREQ(collection_name, "mixie_moodboard_action_nodes");
    CollectionPropertyIterator iter{};
    RNA_property_collection_begin(scene_ptr, collection, &iter);
    while (iter.valid) {
      char node_id[MIXIE_GRAPH_ID_BUF];
      mixie_rna_string_get_clamped(&iter.ptr, "node_id", node_id, sizeof(node_id));
      if (node_id[0] != '\0') {
        rctf rect{};
        rect.xmin = RNA_float_get(&iter.ptr, "position_x");
        rect.ymin = RNA_float_get(&iter.ptr, "position_y");
        rect.xmax = rect.xmin + RNA_float_get(&iter.ptr, "width");
        rect.ymax = rect.ymin + RNA_float_get(&iter.ptr, "height");
        cache->outputs.add_overwrite(node_id, rect);
        if (is_action) {
          cache->action_nodes.add_overwrite(node_id, iter.ptr);
        }
      }
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }
}

bool moodboard_graph_link_endpoints(PointerRNA *scene_ptr,
                                    PointerRNA *link,
                                    float *r_x1,
                                    float *r_y1,
                                    float *r_x2,
                                    float *r_y2,
                                    const MoodboardGraphCache *cache)
{
  char from_id[MIXIE_GRAPH_ID_BUF], to_id[MIXIE_GRAPH_ID_BUF];
  char to_socket[MIXIE_GRAPH_ID_BUF];
  mixie_rna_string_get_clamped(link, "from_node_id", from_id, sizeof(from_id));
  mixie_rna_string_get_clamped(link, "to_node_id", to_id, sizeof(to_id));
  mixie_rna_string_get_clamped(link, "to_socket", to_socket, sizeof(to_socket));

  if (cache) {
    const rctf *from_rect = cache->outputs.lookup_ptr(from_id);
    const PointerRNA *to_node = cache->action_nodes.lookup_ptr(to_id);
    if (!from_rect || !to_node) {
      return false;
    }
    *r_x1 = from_rect->xmax + MOODBOARD_GRAPH_SOCKET_OFFSET;
    *r_y1 = BLI_rctf_cent_y(from_rect);
    PointerRNA node = *to_node;
    return socket_position_in_node(&node, to_socket, r_x2, r_y2);
  }
  return output_position(scene_ptr, from_id, r_x1, r_y1) &&
         input_position(scene_ptr, to_id, to_socket, r_x2, r_y2);
}

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
      UI_view2d_view_to_region_fl(v2d, coords[0][0], coords[0][1], &previous_x, &previous_y);
      for (int segment = 1; segment <= MOODBOARD_GRAPH_LINK_RESOLUTION; segment++) {
        float current_x, current_y;
        UI_view2d_view_to_region_fl(
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
                              const float socket_y)
{
  float region_x, region_y;
  UI_view2d_view_to_region_fl(v2d, socket_x, socket_y, &region_x, &region_y);
  const float dx = float(mouse_x) - region_x;
  const float dy = float(mouse_y) - region_y;
  const float radius = MOODBOARD_GRAPH_SOCKET_RADIUS + 5.0f;
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
    if (region_socket_hit(v2d, mouse_x, mouse_y, output_x, BLI_rctf_cent_y(&rect))) {
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
    rctf rect{};
    if (media_rect(&item, &rect) &&
        region_socket_hit(v2d,
                          mouse_x,
                          mouse_y,
                          rect.xmax + MOODBOARD_GRAPH_SOCKET_OFFSET,
                          BLI_rctf_cent_y(&rect)))
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
      PointerRNA socket;
      RNA_property_collection_lookup_int(&node, sockets, socket_index, &socket);
      mixie_rna_string_get_clamped(
          &node, "node_id", r_hit->node_id, sizeof(r_hit->node_id));
      mixie_rna_string_get_clamped(
          &socket, "socket_id", r_hit->socket_id, sizeof(r_hit->socket_id));
      r_hit->x = x;
      r_hit->y = y;
      return true;
    }
  }
  return false;
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

static bool link_drag_matches(const Scene *scene)
{
  const uint32_t uid = scene_drag_uid(scene);
  return g_link_drag.active && uid != 0 && g_link_drag.scene_uid == uid;
}

void moodboard_graph_link_drag_begin(Scene *scene, const float x, const float y)
{
  g_link_drag = {scene_drag_uid(scene), true, x, y, x, y};
}

void moodboard_graph_link_drag_update(Scene *scene, const float x, const float y)
{
  if (link_drag_matches(scene)) {
    g_link_drag.x2 = x;
    g_link_drag.y2 = y;
  }
}

void moodboard_graph_link_drag_end(Scene *scene)
{
  if (link_drag_matches(scene)) {
    g_link_drag = {};
  }
}

void moodboard_graph_link_drag_reset()
{
  g_link_drag = {};
}

bool moodboard_graph_link_drag_preview(
    Scene *scene, float *r_x1, float *r_y1, float *r_x2, float *r_y2)
{
  if (!link_drag_matches(scene)) {
    return false;
  }
  *r_x1 = g_link_drag.x1;
  *r_y1 = g_link_drag.y1;
  *r_x2 = g_link_drag.x2;
  *r_y2 = g_link_drag.y2;
  return true;
}

}  // namespace blender::ed::mixie
