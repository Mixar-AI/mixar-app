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

void mixie_draw_moodboard_links(const bContext *C,
                                View2D *v2d,
                                const MoodboardGraphCache *cache)
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
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(&scene_ptr, links, &iter);
  while (iter.valid) {
    PointerRNA link = iter.ptr;
    float x1, y1, x2, y2;
    if (moodboard_graph_link_endpoints(&scene_ptr, &link, &x1, &y1, &x2, &y2, cache)) {
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
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&rect, true, 22.0f, background);
  ui::draw_roundbox_4fv(&rect, false, 22.0f, border);
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
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  rctf halo = rect;
  halo.xmin -= 3.0f;
  halo.ymin -= 3.0f;
  halo.xmax += 3.0f;
  halo.ymax += 3.0f;
  const float halo_color[4] = {accent[0], accent[1], accent[2], 0.05f + 0.10f * pulse};
  ui::draw_roundbox_4fv(&halo, false, 25.0f, halo_color);
  const float border[4] = {accent[0], accent[1], accent[2], 0.24f + 0.30f * pulse};
  ui::draw_roundbox_4fv(&rect, false, 22.0f, border);
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

static void draw_text_centered(
    const char *text, const float center_x, const float y, const float size, const float alpha)
{
  const int font_id = BLF_default();
  BLF_size(font_id, size);
  const float width = BLF_width(font_id, text, strlen(text));
  BLF_color4f(font_id, 0.94f, 0.95f, 0.98f, alpha);
  BLF_position(font_id, center_x - width * 0.5f, y, 0.0f);
  BLF_draw(font_id, text, strlen(text));
}

static void draw_text_centered_clipped_col(const char *text,
                                           const float center_x,
                                           const float y,
                                           const float max_width,
                                           const float size,
                                           const float color[3],
                                           const float alpha)
{
  const int font_id = BLF_default();
  BLF_size(font_id, size);
  const char *ellipsis = "...";
  size_t draw_len = strlen(text);
  float draw_width = BLF_width(font_id, text, draw_len);
  bool clipped = false;
  if (draw_width > max_width) {
    const float ellipsis_width = BLF_width(font_id, ellipsis, 3);
    draw_len = BLF_width_to_strlen(
        font_id, text, draw_len, std::max(0.0f, max_width - ellipsis_width), &draw_width);
    clipped = true;
  }
  const float x = center_x - (draw_width + (clipped ? BLF_width(font_id, ellipsis, 3) : 0.0f)) * 0.5f;
  BLF_color4f(font_id, color[0], color[1], color[2], alpha);
  BLF_position(font_id, x, y, 0.0f);
  BLF_draw(font_id, text, draw_len);
  if (clipped) {
    BLF_position(font_id, x + draw_width, y, 0.0f);
    BLF_draw(font_id, ellipsis, 3);
  }
}

static void draw_text_centered_clipped(const char *text,
                                       const float center_x,
                                       const float y,
                                       const float max_width,
                                       const float size,
                                       const float alpha)
{
  const float light[3] = {0.94f, 0.95f, 0.98f};
  draw_text_centered_clipped_col(text, center_x, y, max_width, size, light, alpha);
}

/** One clipped line of the node's failure message (empty error draws nothing).
 * The state used to be announced with no reason at all — the error string was
 * recorded on the node and then shown nowhere. */
static void draw_error_line(PointerRNA *node,
                            const float center_x,
                            const float y,
                            const float max_width)
{
  char error[MIXIE_GRAPH_ERROR_BUF];
  mixie_rna_string_get_clamped(node, "error", error, sizeof(error));
  if (!error[0]) {
    return;
  }
  const float red[3] = {0.94f, 0.55f, 0.52f};
  draw_text_centered_clipped_col(error, center_x, y, max_width, 13.0f, red, 0.85f);
}

/* A deselected (or too-zoomed-out) draft card would otherwise render as an
 * unexplained empty box: its prompt field and Generate button only exist in
 * the screen-space toolbar, which needs the node selected and large enough on
 * screen. Echo the drafted prompt, or say how to get the controls back. */
static void draw_draft_hint(PointerRNA *node, const rctf &rect)
{
  char prompt[MIXIE_GRAPH_PROMPT_PREVIEW_BUF];
  mixie_rna_string_get_clamped(node, "prompt", prompt, sizeof(prompt));
  const float center_x = BLI_rctf_cent_x(&rect);
  const float center_y = BLI_rctf_cent_y(&rect);
  const float max_width = std::max(60.0f, BLI_rctf_size_x(&rect) - 56.0f);
  if (prompt[0]) {
    draw_text_centered_clipped(prompt, center_x, center_y + 8.0f, max_width, 17.0f, 0.85f);
    draw_text_centered_clipped(
        "Click to edit and generate", center_x, center_y - 24.0f, max_width, 13.0f, 0.5f);
  }
  else {
    draw_text_centered_clipped(
        "Describe what you want to create", center_x, center_y + 8.0f, max_width, 17.0f, 0.75f);
    draw_text_centered_clipped(
        "Click this block to type a prompt", center_x, center_y - 24.0f, max_width, 13.0f, 0.5f);
  }
}

/* Queued/Running/Failed/Cancelled tiles without a preview get the same
 * centered layout: the state as the headline, the prompt (or a retry hint)
 * beneath it. The tiny corner label alone read as a broken empty card. */
static void draw_state_hint(PointerRNA *node, const rctf &rect, const int state)
{
  char prompt[MIXIE_GRAPH_PROMPT_PREVIEW_BUF];
  mixie_rna_string_get_clamped(node, "prompt", prompt, sizeof(prompt));
  const float center_x = BLI_rctf_cent_x(&rect);
  const float center_y = BLI_rctf_cent_y(&rect);
  const float max_width = std::max(60.0f, BLI_rctf_size_x(&rect) - 56.0f);
  const char *title = ELEM(state, 1, 2) ?
                          (state == 1 ? "Queued..." : "Generating...") :
                          (state == 4 ? "Generation failed" : "Cancelled");
  draw_text_centered_clipped(title, center_x, center_y + 8.0f, max_width, 17.0f, 0.85f);
  if (ELEM(state, 4, 5)) {
    draw_text_centered_clipped(
        "Click to edit the prompt and try again", center_x, center_y - 24.0f, max_width, 13.0f, 0.5f);
    if (state == 4) {
      draw_error_line(node, center_x, center_y - 52.0f, max_width);
    }
  }
  else if (prompt[0]) {
    draw_text_centered_clipped(prompt, center_x, center_y - 24.0f, max_width, 13.0f, 0.5f);
  }
}

void mixie_draw_moodboard_graph_nodes(const bContext *C,
                                      View2D *v2d,
                                      const MoodboardGraphCache *cache)
{
  Scene *scene = CTX_data_scene(C);
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  float zoom_x, zoom_y;
  ui::view2d_scale_get(v2d, &zoom_x, &zoom_y);
  /* Canvas-unit labels stop being legible below this; skip the draw cost. */
  const bool socket_labels_readable = 13.0f * zoom_x >= 7.0f;

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
        /* One definition of "the floating controls are on screen", shared by
         * every hint below — the toolbar pass uses the same gate, so exactly
         * one of the two draws in any given spot. */
        const bool controls_visible =
            selected &&
            BLI_rctf_size_x(&rect) * zoom_x >= MOODBOARD_GRAPH_CONTROLS_MIN_PX_X &&
            BLI_rctf_size_y(&rect) * zoom_y >= MOODBOARD_GRAPH_CONTROLS_MIN_PX_Y;
        draw_card_background(rect, selected);
        if (ELEM(state, 1, 2)) { /* QUEUED or RUNNING */
          draw_running_glow(rect);
        }
        char node_id[MIXIE_GRAPH_ID_BUF];
        mixie_rna_string_get_clamped(&node, "node_id", node_id, sizeof(node_id));
        PropertyRNA *sockets = RNA_struct_find_property(&node, "input_sockets");
        const int socket_count = sockets ? RNA_property_collection_length(&node, sockets) : 0;
        for (int socket_index = 0; socket_index < socket_count; socket_index++) {
          float socket_x, socket_y;
          if (!moodboard_graph_action_socket_position(
                  &node, socket_index, &socket_x, &socket_y))
          {
            continue;
          }
          PointerRNA socket;
          RNA_property_collection_lookup_int(&node, sockets, socket_index, &socket);
          char accepted[MIXIE_GRAPH_ID_BUF];
          mixie_rna_string_get_clamped(
              &socket, "accepted_types", accepted, sizeof(accepted));
          char socket_id[MIXIE_GRAPH_ID_BUF];
          mixie_rna_string_get_clamped(&socket, "socket_id", socket_id, sizeof(socket_id));
          const bool connected =
              cache && cache->occupied_inputs.contains(
                           moodboard_graph_socket_key(node_id, socket_id));
          moodboard_draw_socket(socket_x,
                                socket_y,
                                moodboard_socket_type_color(accepted),
                                connected,
                                RNA_boolean_get(&socket, "required"));
          if (selected && socket_labels_readable) {
            moodboard_draw_socket_label(&socket, socket_x, socket_y);
          }
        }
        const int action_type = RNA_enum_get(&node, "action_type");
        moodboard_draw_output_handle(rect.xmax + MOODBOARD_GRAPH_SOCKET_OFFSET,
                                     BLI_rctf_cent_y(&rect),
                                     moodboard_action_output_color(action_type));

        PointerRNA preview_ptr = RNA_pointer_get(&node, "preview_image");
        Image *preview_image = static_cast<Image *>(preview_ptr.data);
        PointerRNA object_ptr = RNA_pointer_get(&node, "preview_object");
        /* A MASK_DETAIL node has no embedded result (its outputs become
         * separate nodes), so it falls back to its pre-generation mask cutout
         * — the card always shows what it represents, drawn by the SAME preview
         * path as every other node. The focused control panel floats over this
         * tile with its own background, so no cross-pass stitching is needed. */
        Image *tile_image = preview_image;
        if (!tile_image) {
          PointerRNA mask_ptr = RNA_pointer_get(&node, "mask_preview");
          tile_image = static_cast<Image *>(mask_ptr.data);
        }
        if (tile_image || object_ptr.data) {
          rctf preview_bounds{};
          moodboard_graph_node_preview_bounds(rect, &preview_bounds);
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
          if (tile_image) {
            mixie_draw_moodboard_media_preview(tile_image, preview_bounds);
            if (tile_image->source == IMA_SRC_MOVIE) {
              /* A generated movie is owned by its node, so it never draws as a
               * standalone tile and would otherwise sit frozen on frame 1 with
               * no way to start it. Same affordance as an uploaded movie. */
              bool is_playing = false;
              moodboard_video_playback_frame(tile_image, &is_playing);
              mixie_draw_moodboard_video_overlay(v2d,
                                                 BLI_rctf_cent_x(&preview_bounds),
                                                 BLI_rctf_cent_y(&preview_bounds),
                                                 is_playing);
            }
          }
        }
        const bool has_visual = preview_image || object_ptr.data;
        if (ELEM(state, 1, 2, 4, 5)) {
          if (has_visual) {
            /* Keep the unobtrusive corner label over an existing preview
             * (Edit & Run Again keeps the previous result visible). */
            draw_text(state_label(state), rect.xmin + 18.0f, rect.ymin + 18.0f, 14.0f, 0.72f);
          }
          else if (ELEM(state, 4, 5) && controls_visible) {
            /* The floating prompt + Generate are on screen for the retry, so
             * the centered hint would draw straight underneath them. Keep the
             * compact corner label, and float the failure reason above the
             * card where nothing overlaps it. */
            draw_text(state_label(state), rect.xmin + 18.0f, rect.ymin + 18.0f, 14.0f, 0.72f);
            if (state == 4) {
              draw_error_line(&node,
                              BLI_rctf_cent_x(&rect),
                              rect.ymax + 14.0f,
                              std::max(60.0f, BLI_rctf_size_x(&rect) - 24.0f));
            }
          }
          else {
            draw_state_hint(&node, rect, state);
          }
        }
        else if (state == 0 && !has_visual) {
          if (!controls_visible) {
            draw_draft_hint(&node, rect);
          }
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
        moodboard_draw_output_handle(rect.xmax + MOODBOARD_GRAPH_SOCKET_OFFSET,
                                     BLI_rctf_cent_y(&rect),
                                     moodboard_mesh_output_color());
        char title[MIXIE_GRAPH_LABEL_BUF];
        mixie_rna_string_get_clamped(&node, "title", title, sizeof(title));
        /* 3D mesh node: the object preview icon is drawn in the node-UI pass
         * (like action nodes' 3D results). Here we lay down its dark backdrop
         * and a title strip; nodes without a preview object still show text. */
        PointerRNA object_ptr = RNA_pointer_get(&node, "preview_object");
        if (object_ptr.data) {
          rctf preview_bounds = {
              rect.xmin + 8.0f, rect.xmax - 8.0f, rect.ymin + 8.0f, rect.ymax - 44.0f};
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
          draw_text(title, rect.xmin + 18.0f, rect.ymax - 30.0f, 15.0f, 0.9f);
        }
        else {
          char names[MIXIE_GRAPH_NAMES_BUF];
          mixie_rna_string_get_clamped(&node, "object_names", names, sizeof(names));
          draw_text("3D Result", rect.xmin + 28.0f, rect.ymax - 44.0f, 16.0f, 0.58f);
          draw_text(title, rect.xmin + 28.0f, rect.ymax - 82.0f, 22.0f, 1.0f);
          draw_text(names, rect.xmin + 28.0f, rect.ymax - 120.0f, 15.0f, 0.65f);
        }
      }
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }

  /* Uploaded stills and movies use the same output-handle language as
   * generated tiles. Embedded queue results are already represented by their
   * owning action node and remain hidden here. Rects come from the shared
   * per-frame cache — re-deriving them here re-acquired every image's ImBuf a
   * second time per redraw just to read its aspect. */
  PropertyRNA *media_items = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
  if (media_items && cache) {
    CollectionPropertyIterator iter{};
    RNA_property_collection_begin(&scene_ptr, media_items, &iter);
    while (iter.valid) {
      PointerRNA media = iter.ptr;
      PropertyRNA *embedded = RNA_struct_find_property(&media, "embedded_node_id");
      if (!embedded || RNA_property_string_length(&media, embedded) == 0) {
        char media_id[MIXIE_GRAPH_ID_BUF];
        mixie_rna_string_get_clamped(&media, "node_id", media_id, sizeof(media_id));
        const rctf *media_rect = media_id[0] ? cache->outputs.lookup_ptr(media_id) : nullptr;
        if (media_rect &&
            is_rect_in_view(v2d,
                            media_rect->xmin,
                            media_rect->ymin,
                            BLI_rctf_size_x(media_rect),
                            BLI_rctf_size_y(media_rect)))
        {
          PointerRNA image_ptr = RNA_pointer_get(&media, "image");
          Image *image = static_cast<Image *>(image_ptr.data);
          moodboard_draw_output_handle(media_rect->xmax + MOODBOARD_GRAPH_SOCKET_OFFSET,
                                       BLI_rctf_cent_y(media_rect),
                                       moodboard_media_output_color(image));
        }
      }
      RNA_property_collection_next(&iter);
    }
    RNA_property_collection_end(&iter);
  }

  mixie_draw_moodboard_graph_controls(C, v2d, cache);
}

}  // namespace blender::ed::mixie
