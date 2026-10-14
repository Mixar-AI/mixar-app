/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Shared geometry and hit-testing for moodboard graph sockets and links.
 */

#include "mixie_draw_moodboard_intern.hh"
#include "mixie_moodboard_graph_geometry.hh"

#include "BKE_curve.hh"

#include "BLI_string.h"
#include "DNA_theme_types.h"
#include "DNA_userdef_types.h"

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
    MEM_delete_void(static_cast<void *>(value));
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

float moodboard_video_play_radius(View2D *v2d, const rctf &media_rect)
{
  /* Fixed pixel size, converted into canvas units so it stays the same size on
   * screen at every zoom -- until that would leave it covering the frame it
   * sits on. Zoomed far out a 28px button is most of a small tile, which is
   * exactly how it came to read as "the play button grows as you zoom out", so
   * it is capped against the tile's shorter side and shrinks with it from
   * there. Both hit-tests call this too, so the target never leaves the glyph. */
  const float view_scale = std::max(ui::view2d_scale_get_x(v2d), 0.001f);
  const float screen_radius = MOODBOARD_VIDEO_PLAY_RADIUS_PX / view_scale;
  const float shorter_side = std::min(BLI_rctf_size_x(&media_rect),
                                      BLI_rctf_size_y(&media_rect));
  if (shorter_side <= 0.0f) {
    return screen_radius;
  }
  return std::min(screen_radius, shorter_side * MOODBOARD_VIDEO_PLAY_MAX_FRACTION);
}


std::string moodboard_graph_socket_key(const char *node_id, const char *socket_id)
{
  /* '|' cannot appear in a uuid-hex node id, so the pair cannot collide. */
  return std::string(node_id) + "|" + socket_id;
}

bool moodboard_graph_string_prop_equals(PointerRNA *ptr, const char *name, const char *value)
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
    if (moodboard_graph_string_prop_equals(&iter.ptr, "node_id", node_id)) {
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

bool moodboard_graph_media_rect(PointerRNA *item, rctf *r_rect)
{
  PointerRNA image_ptr = RNA_pointer_get(item, "image");
  Image *image = static_cast<Image *>(image_ptr.data);
  if (!image) {
    return false;
  }
  const float aspect = mixie_moodboard_image_aspect(image);
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
    if (moodboard_graph_string_prop_equals(&iter.ptr, "node_id", node_id) &&
        moodboard_graph_media_rect(&iter.ptr, r_rect))
    {
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

float moodboard_graph_input_radius_px(PointerRNA *node,
                                       const int socket_index,
                                       const View2D *v2d)
{
  const float base = moodboard_socket_radius_px(v2d);
  float x, y;
  if (!moodboard_graph_action_socket_position(node, socket_index, &x, &y)) {
    return base;
  }
  /* Read the real visible socket centres; labels, links and hit tests keep
   * those positions even when adjacent rings need to shrink at overview. */
  float nearest_spacing = 2.0f * (base + UI_SCALE_FAC);
  const float scale_y = std::abs(ui::view2d_scale_get_y(v2d));
  PropertyRNA *sockets = RNA_struct_find_property(node, "input_sockets");
  const int count = sockets ? RNA_property_collection_length(node, sockets) : 0;
  /* Only visible neighbours can be closest. Avoid resolving every position:
   * each lookup scans visibility, making an all-pairs radius pass cubic. */
  for (const int direction : {-1, 1}) {
    for (int index = socket_index + direction; index >= 0 && index < count; index += direction) {
      PointerRNA socket;
      RNA_property_collection_lookup_int(node, sockets, index, &socket);
      if (!RNA_boolean_get(&socket, "visible")) {
        continue;
      }
      float other_x, other_y;
      if (moodboard_graph_action_socket_position(node, index, &other_x, &other_y)) {
        nearest_spacing = std::min(nearest_spacing, std::abs(other_y - y) * scale_y);
      }
      break;
    }
  }
  return std::min(base, std::max(1.0f, nearest_spacing * 0.5f - UI_SCALE_FAC));
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
    if (moodboard_graph_string_prop_equals(&socket, "socket_id", socket_id)) {
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
   * link — and locking that image's buffer again just to read its aspect —
   * which made link drawing O(links * images) every redraw. Aspect now comes
   * from mixie_moodboard_image_aspect, so a warm tile does not take the lock. */
  cache->outputs.clear();
  cache->action_nodes.clear();
  cache->occupied_inputs.clear();

  PropertyRNA *links = RNA_struct_find_property(scene_ptr, "mixie_moodboard_links");
  if (links) {
    CollectionPropertyIterator link_iter{};
    RNA_property_collection_begin(scene_ptr, links, &link_iter);
    while (link_iter.valid) {
      char to_id[MIXIE_GRAPH_ID_BUF], to_socket[MIXIE_GRAPH_ID_BUF];
      mixie_rna_string_get_clamped(&link_iter.ptr, "to_node_id", to_id, sizeof(to_id));
      mixie_rna_string_get_clamped(&link_iter.ptr, "to_socket", to_socket, sizeof(to_socket));
      if (to_id[0] != '\0') {
        cache->occupied_inputs.add(moodboard_graph_socket_key(to_id, to_socket));
      }
      RNA_property_collection_next(&link_iter);
    }
    RNA_property_collection_end(&link_iter);
  }

  PropertyRNA *media = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  if (media) {
    CollectionPropertyIterator iter{};
    RNA_property_collection_begin(scene_ptr, media, &iter);
    while (iter.valid) {
      char node_id[MIXIE_GRAPH_ID_BUF];
      mixie_rna_string_get_clamped(&iter.ptr, "node_id", node_id, sizeof(node_id));
      rctf rect{};
      if (node_id[0] != '\0' && moodboard_graph_media_rect(&iter.ptr, &rect)) {
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
    if (!from_rect) {
      return false;
    }
    *r_x1 = from_rect->xmax + MOODBOARD_GRAPH_SOCKET_OFFSET;
    *r_y1 = BLI_rctf_cent_y(from_rect);
    const PointerRNA *to_node = cache->action_nodes.lookup_ptr(to_id);
    if (to_node) {
      PointerRNA node = *to_node;
      return socket_position_in_node(&node, to_socket, r_x2, r_y2);
    }
    /* Non-action target: a generated output image (or asset) node connected
     * from its producing action node. Images have no input sockets, so aim at
     * the left-centre of the target tile. */
    const rctf *to_rect = cache->outputs.lookup_ptr(to_id);
    if (!to_rect) {
      return false;
    }
    *r_x2 = to_rect->xmin - MOODBOARD_GRAPH_SOCKET_OFFSET;
    *r_y2 = BLI_rctf_cent_y(to_rect);
    return true;
  }
  return output_position(scene_ptr, from_id, r_x1, r_y1) &&
         input_position(scene_ptr, to_id, to_socket, r_x2, r_y2);
}

}  // namespace blender::ed::mixie
