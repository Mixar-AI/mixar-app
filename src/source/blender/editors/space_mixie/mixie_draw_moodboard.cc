/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Moodboard mode drawing core for Mixie space
 *
 * This file contains:
 * - Property caching system
 * - View frustum culling helper
 * - View2D setup
 * - Grid drawing
 * - Selection overlay
 * - Main entry point
 *
 * Image, textbox, and edit tool drawing are in separate files:
 * - mixie_draw_moodboard_images.cc
 * - mixie_draw_moodboard_textboxes.cc
 * - mixie_draw_moodboard_tools.cc
 */

#include "mixie_draw_moodboard_intern.hh"
#include "mixie_moodboard_canvas.hh"

#include "UI_mixar.hh"
#include "UI_mixar_tokens.hh"
#include "mixie_moodboard_chrome.hh"
#include "mixie_moodboard_node_layout.hh"

#include "UI_interface_c.hh"

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name RNA Property Cache Global Instances
 * \{ */

MoodboardImageProps g_img_props = {};
MoodboardTextboxProps g_tb_props = {};

void init_image_property_cache(PointerRNA *itemptr)
{
  if (!g_img_props.initialized) {
    g_img_props.image = RNA_struct_find_property(itemptr, "image");
    g_img_props.display_image = RNA_struct_find_property(itemptr, "display_image");
    g_img_props.embedded_node_id = RNA_struct_find_property(itemptr, "embedded_node_id");
    g_img_props.position_x = RNA_struct_find_property(itemptr, "position_x");
    g_img_props.position_y = RNA_struct_find_property(itemptr, "position_y");
    g_img_props.scale = RNA_struct_find_property(itemptr, "scale");
    g_img_props.rotation = RNA_struct_find_property(itemptr, "rotation");
    g_img_props.flip_horizontal = RNA_struct_find_property(itemptr, "flip_horizontal");
    g_img_props.flip_vertical = RNA_struct_find_property(itemptr, "flip_vertical");
    g_img_props.selected = RNA_struct_find_property(itemptr, "selected");
    g_img_props.annotations = RNA_struct_find_property(itemptr, "annotations");
    g_img_props.show_annotations = RNA_struct_find_property(itemptr, "show_annotations");
    g_img_props.initialized = true;
  }
}

void init_textbox_property_cache(PointerRNA *itemptr)
{
  if (!g_tb_props.initialized) {
    g_tb_props.text = RNA_struct_find_property(itemptr, "text");
    g_tb_props.position_x = RNA_struct_find_property(itemptr, "position_x");
    g_tb_props.position_y = RNA_struct_find_property(itemptr, "position_y");
    g_tb_props.width = RNA_struct_find_property(itemptr, "width");
    g_tb_props.height = RNA_struct_find_property(itemptr, "height");
    g_tb_props.font_size = RNA_struct_find_property(itemptr, "font_size");
    g_tb_props.rotation = RNA_struct_find_property(itemptr, "rotation");
    g_tb_props.text_color = RNA_struct_find_property(itemptr, "text_color");
    g_tb_props.background_color = RNA_struct_find_property(itemptr, "background_color");
    g_tb_props.align = RNA_struct_find_property(itemptr, "align");
    g_tb_props.bold = RNA_struct_find_property(itemptr, "bold");
    g_tb_props.italic = RNA_struct_find_property(itemptr, "italic");
    g_tb_props.selected = RNA_struct_find_property(itemptr, "selected");
    g_tb_props.initialized = true;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name View Frustum Culling Helper
 * \{ */

bool is_rect_in_view(View2D *v2d, float x, float y, float w, float h)
{
  /* Add margin to account for selection handles and rotation */
  const float margin = 50.0f;
  return !(x + w < v2d->cur.xmin - margin || x > v2d->cur.xmax + margin ||
           y + h < v2d->cur.ymin - margin || y > v2d->cur.ymax + margin);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name View2D Setup for Moodboard
 * \{ */

/* File-local: the drawer's cross-module entry point is
 * `mixie_moodboard_canvas_draw()`, which rebuilds the view itself. */
static void mixie_moodboard_region_set_view2d(ARegion *region)
{
  View2D *v2d = &region->v2d;

  /* Calculate window dimensions from winrct - matches IMAGE_EDITOR pattern */
  int winx = BLI_rcti_size_x(&region->winrct) + 1;
  int winy = BLI_rcti_size_y(&region->winrct) + 1;

  /* Update View2D window size */
  v2d->winx = winx;
  v2d->winy = winy;

  /* Update mask to match actual window dimensions - CRITICAL for trackpad zoom coordinate
   * transform */
  v2d->mask.xmin = 0;
  v2d->mask.ymin = 0;
  v2d->mask.xmax = winx;
  v2d->mask.ymax = winy;

  /* Calculate view size maintaining current center and zoom level */
  float cur_width = BLI_rctf_size_x(&v2d->cur);

  /* If we have a valid previous size, keep the zoom ratio (view units per pixel) */
  float zoom_ratio = (winx > 0 && cur_width > 0) ? cur_width / float(winx) : 1.0f;

  float view_width = float(winx) * zoom_ratio;
  float view_height = float(winy) * zoom_ratio;

  float center_x = (v2d->cur.xmin + v2d->cur.xmax) / 2.0f;
  float center_y = (v2d->cur.ymin + v2d->cur.ymax) / 2.0f;

  /* Update current view bounds based on window size, maintaining center */
  v2d->cur.xmin = center_x - view_width / 2.0f;
  v2d->cur.xmax = center_x + view_width / 2.0f;
  v2d->cur.ymin = center_y - view_height / 2.0f;
  v2d->cur.ymax = center_y + view_height / 2.0f;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Moodboard Grid Drawing
 * \{ */

static void mixie_draw_moodboard_grid(View2D *v2d)
{
  /* Keep both spacing and dot radius fixed in canvas space. Consequently,
   * zooming in reveals fewer, larger dots instead of maintaining a constant
   * screen-space density. */
  const float grid_step = MOODBOARD_GRID_SPACING;
  const float dot_radius = MOODBOARD_GRID_DOT_RADIUS;
  const float view_scale = std::min(ui::view2d_scale_get_x(v2d),
                                    ui::view2d_scale_get_y(v2d));
  const float dot_diameter_px = dot_radius * 2.0f * view_scale;

  /* A regular grid below pixel resolution produces circular Moire bands as
   * rows are inconsistently sampled. Fade it before reaching that range. */
  if (dot_diameter_px <= MOODBOARD_GRID_DOT_FADE_START_PX) {
    return;
  }
  const float grid_alpha = std::clamp(
      (dot_diameter_px - MOODBOARD_GRID_DOT_FADE_START_PX) /
          (MOODBOARD_GRID_DOT_FADE_END_PX - MOODBOARD_GRID_DOT_FADE_START_PX),
      0.0f,
      1.0f);
  const float *border = ui::mixar_tokens::mixar_zen().border;
  const float grid_color[4] = {border[0], border[1], border[2], grid_alpha * 0.65f};

  /* Calculate the visible grid bounds. */
  float view_min_x = v2d->cur.xmin;
  float view_max_x = v2d->cur.xmax;
  float view_min_y = v2d->cur.ymin;
  float view_max_y = v2d->cur.ymax;

  const int first_column = int(floorf(view_min_x / grid_step));
  const int last_column = int(floorf(view_max_x / grid_step));
  const int first_row = int(floorf(view_min_y / grid_step));
  const int last_row = int(floorf(view_max_y / grid_step));
  const int column_count = std::max(last_column - first_column + 1, 0);
  const int row_count = std::max(last_row - first_row + 1, 0);
  const int dot_count = column_count * row_count;

  if (dot_count == 0) {
    return;
  }

  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);

  GPU_blend(GPU_BLEND_ALPHA);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(grid_color);

  /* Every dot is the same disc at a different centre, so the rim offsets are
   * loop-invariant: resolve the unit circle once instead of four trig calls
   * per segment per dot. A default-width drawer shows ~700 dots, which cost
   * ~34k `cosf`/`sinf` per frame before this and 24 after. */
  float rim_x[MOODBOARD_GRID_DOT_SEGMENTS + 1];
  float rim_y[MOODBOARD_GRID_DOT_SEGMENTS + 1];
  for (int segment = 0; segment <= MOODBOARD_GRID_DOT_SEGMENTS; segment++) {
    const float angle = (2.0f * float(M_PI) * float(segment)) /
                        float(MOODBOARD_GRID_DOT_SEGMENTS);
    rim_x[segment] = cosf(angle) * dot_radius;
    rim_y[segment] = sinf(angle) * dot_radius;
  }

  /* Filled discs avoid the varying subpixel coverage of GPU point primitives,
   * which otherwise creates visible Moire groupings. */
  immBegin(GPU_PRIM_TRIS, dot_count * MOODBOARD_GRID_DOT_SEGMENTS * 3);
  for (int row = first_row; row <= last_row; row++) {
    const float center_y = float(row) * grid_step;
    for (int column = first_column; column <= last_column; column++) {
      const float center_x = float(column) * grid_step;

      for (int segment = 0; segment < MOODBOARD_GRID_DOT_SEGMENTS; segment++) {
        immVertex2f(pos, center_x, center_y);
        immVertex2f(pos, center_x + rim_x[segment], center_y + rim_y[segment]);
        immVertex2f(pos, center_x + rim_x[segment + 1], center_y + rim_y[segment + 1]);
      }
    }
  }
  immEnd();
  immUnbindProgram();
  GPU_blend(GPU_BLEND_NONE);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Selection Overlay Drawing
 * \{ */

void moodboard_draw_surface(const rctf &rect, const float radius)
{
  ui::mixar_fill_round(rect, radius, ui::mixar_tokens::mixar_zen().panel);
  ui::draw_roundbox_corner_set(ui::CNR_ALL);
  ui::draw_roundbox_4fv(&rect, false, radius, ui::mixar_tokens::mixar_zen().border);
}

void mixie_draw_moodboard_media_frame(
    const float x, const float y, const float w, const float h, const bool selected)
{
  const float padding = MOODBOARD_MEDIA_FRAME_PADDING;
  const rctf frame = {x - padding, x + w + padding, y - padding, y + h + padding};
  moodboard_draw_surface(frame, MOODBOARD_MEDIA_FRAME_RADIUS);
  /* Only the SELECTED frame brightens its rim; the RESTING one is the token
   * row's, so both the media frame and the node card share one resting look. */
  if (selected) {
    const float *border = ui::mixar_tokens::mixar_zen().focus;
    ui::draw_roundbox_corner_set(ui::CNR_ALL);
    ui::draw_roundbox_4fv(&frame, false, MOODBOARD_MEDIA_FRAME_RADIUS, border);
  }
}

void mixie_draw_moodboard_selection_overlay(View2D *v2d, float x, float y, float w, float h)
{
  /* Draw selection outline */
  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);

  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);

  /* Draw selection fill (semi-transparent) */
  GPU_blend(GPU_BLEND_ALPHA);
  immUniformColor4f(0.70f, 0.71f, 0.74f, 0.06f);

  immRectf(pos, x, y, x + w, y + h);

  /* Draw selection border */
  immUniformColor4f(0.72f, 0.73f, 0.76f, 0.82f);
  GPU_line_width(2.0f);

  immBegin(GPU_PRIM_LINE_LOOP, 4);
  immVertex2f(pos, x, y);
  immVertex2f(pos, x + w, y);
  immVertex2f(pos, x + w, y + h);
  immVertex2f(pos, x, y + h);
  immEnd();

  mixie_draw_moodboard_resize_handles(v2d, pos, x, y, w, h);

  GPU_line_width(1.0f);
  GPU_blend(GPU_BLEND_NONE);

  immUnbindProgram();
}

void mixie_draw_moodboard_resize_handles(
    View2D *v2d, const uint pos, const float x, const float y, const float w, const float h)
{
  /* FOUR corner squares, from the ONE definition the hit-test reads
   * (`moodboard_resize_handle_positions`), so the squares the user aims at and
   * the region that responds cannot drift apart. The four edge midpoints this
   * replaces meant "stretch one axis" -- a distortion nobody asks of a picture
   * or a generated result -- and they crowded the corners that do the work.
   *
   * A fixed SCREEN size converted through the view scale: a handle is an
   * affordance, not part of the picture, so it stays the same size to aim at
   * at every zoom. */
  const float handle_size = MOODBOARD_RESIZE_HANDLE_PX / ui::view2d_scale_get_x(v2d);
  const rctf rect = {x, x + w, y, y + h};
  float handles[MOODBOARD_RESIZE_HANDLE_COUNT][2];
  moodboard_resize_handle_positions(rect, handles);

  immUniformColor4f(1.0f, 1.0f, 1.0f, 1.0f);
  for (int i = 0; i < MOODBOARD_RESIZE_HANDLE_COUNT; i++) {
    immRectf(pos,
             handles[i][0] - handle_size / 2,
             handles[i][1] - handle_size / 2,
             handles[i][0] + handle_size / 2,
             handles[i][1] + handle_size / 2);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Moodboard Mode Entry Point
 * \{ */

void mixie_draw_moodboard_mode(const bContext *C, ARegion *region)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return;
  }

  /* Update View2D before drawing to prevent automatic validation from distorting canvas */
  mixie_moodboard_region_set_view2d(region);

  /* Setup View2D for infinite canvas */
  View2D *v2d = &region->v2d;

  ui::view2d_view_ortho(v2d);

  /* Draw grid background */
  mixie_draw_moodboard_grid(v2d);

  /* Paint the complete board beneath floating chrome and overlapping panels.
   * Framing margins must never cut a vertical strip out of a panned card. */
  int previous_scissor[4];
  GPU_scissor_get(previous_scissor);
  rcti content = moodboard_canvas_draw_rect(C);
  const rcti host_scissor = {previous_scissor[0], previous_scissor[0] + previous_scissor[2],
                            previous_scissor[1], previous_scissor[1] + previous_scissor[3]};
  if (BLI_rcti_isect(&content, &host_scissor, &content)) {
    GPU_scissor(content.xmin, content.ymin,
                BLI_rcti_size_x(&content), BLI_rcti_size_y(&content));
  }
  else {
    GPU_scissor(0, 0, 0, 0);
  }

  /* Canvas frames come next, UNDERNEATH every other pass. A frame is a
   * translucent wash over a region of the board, so drawing it after the
   * media and the cards (which is where the old group pass sat) would tint
   * the very results the user is looking at. Its NAME is painted much later,
   * in the screen-space pass, so a member can never cover it. */
  mixie_draw_moodboard_frames(C, v2d);

  /* One rect/link cache for every graph pass of this frame. Aspect comes
   * from the draw-stamp size cache, so a warm tile does not lock an ImBuf. */
  MoodboardGraphCache graph_cache;
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  moodboard_graph_cache_build(&scene_ptr, &graph_cache);

  /* Draw graph connections behind every canvas block. */
  mixie_draw_moodboard_links(C, v2d, &graph_cache);

  /* Draw moodboard images */
  mixie_draw_moodboard_images(C, v2d);

  /* Draw inference and 3D-result nodes above their links. */
  mixie_draw_moodboard_graph_nodes(C, v2d, &graph_cache);

  /* Draw moodboard text boxes */
  mixie_draw_moodboard_textboxes(C, v2d);

  /* Board marks sit over its content and share its pan/zoom and host scissor. */
  mixie_draw_moodboard_canvas_annotations(&scene_ptr, v2d);

  /* Draw edit tool overlay */
  mixie_draw_edit_tool_overlay(C, v2d);

  BLF_batch_draw_flush();
  GPU_scissor(previous_scissor[0], previous_scissor[1],
              previous_scissor[2], previous_scissor[3]);

  /* Reset view */
  ui::view2d_view_restore(C);

  /* Draw View2D scrollers */
  ui::view2d_scrollers_draw(v2d, nullptr);
  mixie_moodboard_chrome_draw(C, region);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Public host bridge
 * \{ */

void mixie_moodboard_canvas_draw(const bContext *C, ARegion *region)
{
  mixie_draw_moodboard_mode(C, region);
}

/** \} */

}  // namespace blender::ed::mixie
