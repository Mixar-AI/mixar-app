/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Inference nodes, asset cards, and links for the moodboard graph.
 */

#include "mixie_draw_moodboard_intern.hh"

#include <cmath>

#include "BKE_curve.hh"

#include "BLI_string.h"
#include "BLI_time.h"

#include "GPU_immediate_util.hh"

#include "UI_interface_c.hh"

namespace blender::ed::mixie {

static constexpr int LINK_RESOLUTION = MOODBOARD_GRAPH_LINK_RESOLUTION;

static void draw_link_curve(const float x1,
                            const float y1,
                            const float x2,
                            const float y2,
                            const bool selected)
{
  float coords[LINK_RESOLUTION + 1][2];
  moodboard_graph_link_curve_coords(x1, y1, x2, y2, coords);

  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4f(0.65f, 0.67f, 0.72f, selected ? 1.0f : 0.72f);
  GPU_line_width(selected ? 4.0f : 2.0f);
  immBegin(GPU_PRIM_LINE_STRIP, LINK_RESOLUTION + 1);
  for (int i = 0; i <= LINK_RESOLUTION; i++) {
    immVertex2fv(pos, coords[i]);
  }
  immEnd();
  GPU_line_width(1.0f);
  immUnbindProgram();
}

void mixie_draw_moodboard_links(const bContext *C, View2D *v2d)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *links = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_links");
  if (!links) {
    return;
  }
  /* Built once, reused by every link. See MoodboardGraphCache. */
  MoodboardGraphCache cache;
  moodboard_graph_cache_build(&scene_ptr, &cache);
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(&scene_ptr, links, &iter);
  while (iter.valid) {
    PointerRNA link = iter.ptr;
    float x1, y1, x2, y2;
    if (moodboard_graph_link_endpoints(&scene_ptr, &link, &x1, &y1, &x2, &y2, &cache)) {
      /* Cull off-screen links before evaluating the curve. */
      rctf bounds{};
      moodboard_graph_link_bounds(x1, y1, x2, y2, &bounds);
      if (is_rect_in_view(v2d,
                          bounds.xmin,
                          bounds.ymin,
                          BLI_rctf_size_x(&bounds),
                          std::max(BLI_rctf_size_y(&bounds), 1.0f)))
      {
        draw_link_curve(x1, y1, x2, y2, RNA_boolean_get(&link, "selected"));
      }
    }
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
  float drag_x1, drag_y1, drag_x2, drag_y2;
  if (moodboard_graph_link_drag_preview(
          scene, &drag_x1, &drag_y1, &drag_x2, &drag_y2))
  {
    draw_link_curve(drag_x1, drag_y1, drag_x2, drag_y2, true);
  }
}

static void draw_card_background(const rctf &rect, const bool selected)
{
  const float background[4] = {0.105f, 0.105f, 0.11f, 0.99f};
  const float border[4] = {0.38f, 0.39f, 0.42f, selected ? 0.92f : 0.58f};
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  UI_draw_roundbox_4fv(&rect, true, 22.0f, background);
  UI_draw_roundbox_4fv(&rect, false, 22.0f, border);
}

static void draw_running_glow(const rctf &rect)
{
  /* Subtle "generating" pulse while a node is QUEUED/RUNNING: an accent border
   * that breathes in alpha plus a faint outset halo. Kept deliberately dim —
   * never a harsh bright ring. The Python pulse timer
   * (node_job_bridge.ensure_pulse_timer) supplies the continuous redraws; the
   * wall clock supplies the phase (~2.9s breathe). */
  const float pulse = 0.5f + 0.5f * float(std::sin(BLI_time_now_seconds() * 2.2));
  const float accent[3] = {0.32f, 0.72f, 0.55f}; /* muted Mixar green */
  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  rctf halo = rect;
  halo.xmin -= 3.0f;
  halo.ymin -= 3.0f;
  halo.xmax += 3.0f;
  halo.ymax += 3.0f;
  const float halo_color[4] = {accent[0], accent[1], accent[2], 0.05f + 0.10f * pulse};
  UI_draw_roundbox_4fv(&halo, false, 25.0f, halo_color);
  const float border[4] = {accent[0], accent[1], accent[2], 0.24f + 0.30f * pulse};
  UI_draw_roundbox_4fv(&rect, false, 22.0f, border);
}

static void draw_socket(const float x, const float y, const float color[3])
{
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4f(color[0], color[1], color[2], 1.0f);
  imm_draw_circle_fill_2d(pos, x, y, MOODBOARD_GRAPH_SOCKET_RADIUS, 24);
  immUnbindProgram();
}

static void draw_output_handle(const float x, const float y, const float color[3])
{
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4f(color[0], color[1], color[2], 1.0f);
  imm_draw_circle_fill_2d(pos, x, y, MOODBOARD_GRAPH_OUTPUT_RADIUS, 28);
  immUniformColor4f(0.04f, 0.05f, 0.06f, 1.0f);
  GPU_line_width(2.5f);
  immBegin(GPU_PRIM_LINES, 4);
  immVertex2f(pos, x - 7.0f, y);
  immVertex2f(pos, x + 7.0f, y);
  immVertex2f(pos, x, y - 7.0f);
  immVertex2f(pos, x, y + 7.0f);
  immEnd();
  GPU_line_width(1.0f);
  immUnbindProgram();
}

static void draw_text(const char *text, const float x, const float y, const float size, const float alpha)
{
  const int font_id = BLF_default();
  BLF_size(font_id, size);
  BLF_color4f(font_id, 0.94f, 0.95f, 0.98f, alpha);
  BLF_position(font_id, x, y, 0.0f);
  BLF_draw(font_id, text, strlen(text));
}

static const char *state_label(const int state)
{
  static const char *labels[] = {"Draft", "Queued", "Running", "Complete", "Failed", "Cancelled"};
  return labels[std::clamp(state, 0, 5)];
}

void mixie_draw_moodboard_graph_nodes(const bContext *C, View2D *v2d)
{
  Scene *scene = CTX_data_scene(C);
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  const float neutral[3] = {0.56f, 0.57f, 0.60f};

  PropertyRNA *actions = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_action_nodes");
  if (actions) {
    CollectionPropertyIterator iter{};
    RNA_property_collection_begin(&scene_ptr, actions, &iter);
    while (iter.valid) {
      PointerRNA node = iter.ptr;
      rctf rect{};
      rect.xmin = RNA_float_get(&node, "position_x");
      rect.ymin = RNA_float_get(&node, "position_y");
      rect.xmax = rect.xmin + RNA_float_get(&node, "width");
      rect.ymax = rect.ymin + RNA_float_get(&node, "height");
      if (is_rect_in_view(v2d, rect.xmin, rect.ymin, BLI_rctf_size_x(&rect), BLI_rctf_size_y(&rect))) {
        const bool selected = RNA_boolean_get(&node, "selected");
        const int state = RNA_enum_get(&node, "state");
        draw_card_background(rect, selected);
        if (ELEM(state, 1, 2)) { /* QUEUED or RUNNING */
          draw_running_glow(rect);
        }
        PropertyRNA *sockets = RNA_struct_find_property(&node, "input_sockets");
        const int socket_count = sockets ? RNA_property_collection_length(&node, sockets) : 0;
        for (int socket_index = 0; socket_index < socket_count; socket_index++) {
          float socket_x, socket_y;
          if (moodboard_graph_action_socket_position(
                  &node, socket_index, &socket_x, &socket_y))
          {
            draw_socket(socket_x, socket_y, neutral);
          }
        }
        draw_output_handle(
            rect.xmax + MOODBOARD_GRAPH_SOCKET_OFFSET, BLI_rctf_cent_y(&rect), neutral);

        PointerRNA preview_ptr = RNA_pointer_get(&node, "preview_image");
        Image *preview_image = static_cast<Image *>(preview_ptr.data);
        PointerRNA object_ptr = RNA_pointer_get(&node, "preview_object");
        if (preview_image || object_ptr.data) {
          rctf preview_bounds = {
              rect.xmin + 6.0f, rect.xmax - 6.0f, rect.ymin + 6.0f, rect.ymax - 6.0f};
          GPUVertFormat *format = immVertexFormat();
          const uint pos = GPU_vertformat_attr_add(
              format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
          immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
          immUniformColor4f(0.025f, 0.027f, 0.032f, 1.0f);
          immRectf(pos,
                   preview_bounds.xmin,
                   preview_bounds.ymin,
                   preview_bounds.xmax,
                   preview_bounds.ymax);
          immUnbindProgram();
          if (preview_image) {
            mixie_draw_moodboard_media_preview(preview_image, preview_bounds);
          }
        }
        if (ELEM(state, 1, 2, 4, 5)) {
          draw_text(state_label(state), rect.xmin + 18.0f, rect.ymin + 18.0f, 14.0f, 0.72f);
        }
      }
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }

  PropertyRNA *assets = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_asset_nodes");
  if (assets) {
    CollectionPropertyIterator iter{};
    RNA_property_collection_begin(&scene_ptr, assets, &iter);
    while (iter.valid) {
      PointerRNA node = iter.ptr;
      rctf rect{};
      rect.xmin = RNA_float_get(&node, "position_x");
      rect.ymin = RNA_float_get(&node, "position_y");
      rect.xmax = rect.xmin + RNA_float_get(&node, "width");
      rect.ymax = rect.ymin + RNA_float_get(&node, "height");
      if (is_rect_in_view(
              v2d, rect.xmin, rect.ymin, BLI_rctf_size_x(&rect), BLI_rctf_size_y(&rect)))
      {
        draw_card_background(rect, RNA_boolean_get(&node, "selected"));
        draw_output_handle(
            rect.xmax + MOODBOARD_GRAPH_SOCKET_OFFSET, BLI_rctf_cent_y(&rect), neutral);
        char title[MIXIE_GRAPH_LABEL_BUF], names[MIXIE_GRAPH_NAMES_BUF];
        mixie_rna_string_get_clamped(&node, "title", title, sizeof(title));
        mixie_rna_string_get_clamped(&node, "object_names", names, sizeof(names));
        draw_text("Legacy 3D Result", rect.xmin + 28.0f, rect.ymax - 44.0f, 16.0f, 0.58f);
        draw_text(title, rect.xmin + 28.0f, rect.ymax - 82.0f, 22.0f, 1.0f);
        draw_text(names, rect.xmin + 28.0f, rect.ymax - 120.0f, 15.0f, 0.65f);
      }
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }

  /* Uploaded stills and movies use the same output-handle language as
   * generated tiles. Embedded queue results are already represented by their
   * owning action node and remain hidden here. */
  PropertyRNA *media_items = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
  if (media_items) {
    CollectionPropertyIterator iter{};
    RNA_property_collection_begin(&scene_ptr, media_items, &iter);
    while (iter.valid) {
      PointerRNA media = iter.ptr;
      PropertyRNA *embedded = RNA_struct_find_property(&media, "embedded_node_id");
      if (!embedded || RNA_property_string_length(&media, embedded) == 0) {
        PointerRNA image_ptr = RNA_pointer_get(&media, "image");
        Image *image = static_cast<Image *>(image_ptr.data);
        if (image) {
          float aspect = 1.0f;
          void *lock = nullptr;
          ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
          if (ibuf && ibuf->x > 0) {
            aspect = float(ibuf->y) / float(ibuf->x);
          }
          BKE_image_release_ibuf(image, ibuf, lock);
          const float width = MOODBOARD_IMAGE_BASE_SIZE * RNA_float_get(&media, "scale");
          const float x = RNA_float_get(&media, "position_x") + width +
                          MOODBOARD_GRAPH_SOCKET_OFFSET;
          const float y = RNA_float_get(&media, "position_y") + width * aspect * 0.5f;
          draw_output_handle(x, y, neutral);
        }
      }
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }

  mixie_draw_moodboard_graph_controls(C, v2d);
}

}  // namespace blender::ed::mixie
