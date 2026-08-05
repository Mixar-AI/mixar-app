/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Moodboard edit tool overlay drawing (crop/mask/lasso) for Mixie space
 */

#include "mixie_draw_moodboard_intern.hh"

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Edit Tool Overlay Drawing (Crop/Box Mask/Lasso)
 * \{ */

/**
 * Draw edit tool overlay (crop box, mask region, etc.) on top of the target image.
 * Reads state from Python's mixie_edit_tool_state property group.
 */
void mixie_draw_edit_tool_overlay(const bContext *C, View2D *v2d)
{
  Scene *scene = CTX_data_scene(C);
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);

  /* Get edit tool state from Python property group */
  PropertyRNA *state_prop = RNA_struct_find_property(&scene_ptr, "mixie_edit_tool_state");
  if (!state_prop) {
    return;
  }

  PointerRNA state_ptr = RNA_property_pointer_get(&scene_ptr, state_prop);
  if (!state_ptr.data) {
    return;
  }

  /* Check if any edit tool is active */
  PropertyRNA *tool_prop = RNA_struct_find_property(&state_ptr, "active_tool");
  if (!tool_prop) {
    return;
  }

  int active_tool = RNA_property_enum_get(&state_ptr, tool_prop);
  /* active_tool: 0=NONE, 1=CROP, 2=BOX_MASK, 3=LASSO, 4=MAGIC_SELECT, 5=ANNOTATE */
  if (active_tool == 0) {
    return;
  }

  /* Get target image index */
  PropertyRNA *idx_prop = RNA_struct_find_property(&state_ptr, "target_image_index");
  if (!idx_prop) {
    return;
  }
  int target_idx = RNA_property_int_get(&state_ptr, idx_prop);
  if (target_idx < 0) {
    return;
  }

  /* Get box coordinates (0-1 range in image space) */
  PropertyRNA *box_x1_prop = RNA_struct_find_property(&state_ptr, "box_start_x");
  PropertyRNA *box_y1_prop = RNA_struct_find_property(&state_ptr, "box_start_y");
  PropertyRNA *box_x2_prop = RNA_struct_find_property(&state_ptr, "box_end_x");
  PropertyRNA *box_y2_prop = RNA_struct_find_property(&state_ptr, "box_end_y");

  if (!box_x1_prop || !box_y1_prop || !box_x2_prop || !box_y2_prop) {
    return;
  }

  float box_x1 = RNA_property_float_get(&state_ptr, box_x1_prop);
  float box_y1 = RNA_property_float_get(&state_ptr, box_y1_prop);
  float box_x2 = RNA_property_float_get(&state_ptr, box_x2_prop);
  float box_y2 = RNA_property_float_get(&state_ptr, box_y2_prop);

  /* Get target image position and size */
  PropertyRNA *images_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");
  if (!images_prop) {
    return;
  }

  int image_count = RNA_property_collection_length(&scene_ptr, images_prop);
  if (target_idx >= image_count) {
    return;
  }

  PointerRNA img_item_ptr;
  RNA_property_collection_lookup_int(&scene_ptr, images_prop, target_idx, &img_item_ptr);

  PropertyRNA *image_prop = RNA_struct_find_property(&img_item_ptr, "image");
  PropertyRNA *pos_x_prop = RNA_struct_find_property(&img_item_ptr, "position_x");
  PropertyRNA *pos_y_prop = RNA_struct_find_property(&img_item_ptr, "position_y");
  PropertyRNA *scale_prop = RNA_struct_find_property(&img_item_ptr, "scale");
  PropertyRNA *rotation_prop = RNA_struct_find_property(&img_item_ptr, "rotation");
  PropertyRNA *flip_horizontal_prop = RNA_struct_find_property(&img_item_ptr, "flip_horizontal");
  PropertyRNA *flip_vertical_prop = RNA_struct_find_property(&img_item_ptr, "flip_vertical");

  if (!image_prop || !pos_x_prop || !pos_y_prop || !scale_prop) {
    return;
  }

  PointerRNA image_ptr = RNA_property_pointer_get(&img_item_ptr, image_prop);
  Image *image = (Image *)image_ptr.data;
  if (!image) {
    return;
  }

  float pos_x = RNA_property_float_get(&img_item_ptr, pos_x_prop);
  float pos_y = RNA_property_float_get(&img_item_ptr, pos_y_prop);
  float scale = RNA_property_float_get(&img_item_ptr, scale_prop);
  float rotation = rotation_prop ? RNA_property_float_get(&img_item_ptr, rotation_prop) : 0.0f;
  bool flip_horizontal = flip_horizontal_prop ?
                             RNA_property_boolean_get(&img_item_ptr, flip_horizontal_prop) :
                             false;
  bool flip_vertical = flip_vertical_prop ?
                           RNA_property_boolean_get(&img_item_ptr, flip_vertical_prop) :
                           false;

  /* Calculate display size */
  void *lock;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
  float display_width = MOODBOARD_IMAGE_BASE_SIZE * scale;
  float display_height = (ibuf && ibuf->x > 0 && ibuf->y > 0) ?
                             (MOODBOARD_IMAGE_BASE_SIZE * float(ibuf->y) / float(ibuf->x)) * scale :
                             MOODBOARD_IMAGE_BASE_SIZE * scale;
  BKE_image_release_ibuf(image, ibuf, lock);

  /* Normalize box coordinates (handle drag in any direction) */
  float norm_x1 = std::min(box_x1, box_x2);
  float norm_x2 = std::max(box_x1, box_x2);
  float norm_y1 = std::min(box_y1, box_y2);
  float norm_y2 = std::max(box_y1, box_y2);

  /* Convert box coords from image-relative (0-1) to canvas coords */
  float crop_x1 = pos_x + norm_x1 * display_width;
  float crop_y1 = pos_y + norm_y1 * display_height;
  float crop_x2 = pos_x + norm_x2 * display_width;
  float crop_y2 = pos_y + norm_y2 * display_height;

  /* Image bounds in canvas coords */
  float img_left = pos_x;
  float img_right = pos_x + display_width;
  float img_bottom = pos_y;
  float img_top = pos_y + display_height;

  const float center_x = pos_x + display_width / 2.0f;
  const float center_y = pos_y + display_height / 2.0f;
  GPU_matrix_push();
  GPU_matrix_translate_2f(center_x, center_y);
  if (rotation != 0.0f) {
    GPU_matrix_rotate_2d(rotation);
  }
  GPU_matrix_scale_2f(flip_horizontal ? -1.0f : 1.0f, flip_vertical ? -1.0f : 1.0f);
  GPU_matrix_translate_2f(-center_x, -center_y);

  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);

  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  GPU_blend(GPU_BLEND_ALPHA);

  /* Draw tool-specific overlay */
  if (active_tool == 1 || active_tool == 2) {
    /* CROP or BOX_MASK - draw box with dimming overlay */

    /* Draw semi-transparent overlay outside the crop region (dimming effect) */
    immUniformColor4f(0.0f, 0.0f, 0.0f, 0.5f);

    /* Left region */
    if (crop_x1 > img_left) {
      immRectf(pos, img_left, img_bottom, crop_x1, img_top);
    }
    /* Right region */
    if (crop_x2 < img_right) {
      immRectf(pos, crop_x2, img_bottom, img_right, img_top);
    }
    /* Bottom region (between left and right crop bounds) */
    if (crop_y1 > img_bottom) {
      immRectf(pos, crop_x1, img_bottom, crop_x2, crop_y1);
    }
    /* Top region (between left and right crop bounds) */
    if (crop_y2 < img_top) {
      immRectf(pos, crop_x1, crop_y2, crop_x2, img_top);
    }

    /* Draw crop box outline */
    GPU_line_width(2.0f);

    if (active_tool == 1) {
      /* CROP - cyan */
      immUniformColor4f(0.0f, 1.0f, 1.0f, 1.0f);
    }
    else {
      /* BOX_MASK - yellow */
      immUniformColor4f(1.0f, 1.0f, 0.0f, 1.0f);
    }

    immBegin(GPU_PRIM_LINE_LOOP, 4);
    immVertex2f(pos, crop_x1, crop_y1);
    immVertex2f(pos, crop_x2, crop_y1);
    immVertex2f(pos, crop_x2, crop_y2);
    immVertex2f(pos, crop_x1, crop_y2);
    immEnd();

    /* Draw crop handles: L-shaped corners + edge midpoint lines */
    float inv_zoom = 1.0f / UI_view2d_scale_get_x(v2d);
    float corner_len = 20.0f * inv_zoom;   /* Length of each L arm */
    float edge_len = 14.0f * inv_zoom;     /* Length of edge midpoint lines */
    float mid_x = (crop_x1 + crop_x2) / 2;
    float mid_y = (crop_y1 + crop_y2) / 2;

    /* Clamp corner arm length to half the crop box size */
    float half_w = (crop_x2 - crop_x1) * 0.4f;
    float half_h = (crop_y2 - crop_y1) * 0.4f;
    corner_len = std::min(corner_len, std::min(half_w, half_h));

    GPU_line_width(3.0f);
    immUniformColor4f(1.0f, 1.0f, 1.0f, 1.0f);

    /* 4 L-shaped corner handles (2 lines each = 16 vertices) */
    immBegin(GPU_PRIM_LINES, 16);
    /* Bottom-left L */
    immVertex2f(pos, crop_x1, crop_y1);
    immVertex2f(pos, crop_x1 + corner_len, crop_y1);
    immVertex2f(pos, crop_x1, crop_y1);
    immVertex2f(pos, crop_x1, crop_y1 + corner_len);
    /* Bottom-right L */
    immVertex2f(pos, crop_x2, crop_y1);
    immVertex2f(pos, crop_x2 - corner_len, crop_y1);
    immVertex2f(pos, crop_x2, crop_y1);
    immVertex2f(pos, crop_x2, crop_y1 + corner_len);
    /* Top-right L */
    immVertex2f(pos, crop_x2, crop_y2);
    immVertex2f(pos, crop_x2 - corner_len, crop_y2);
    immVertex2f(pos, crop_x2, crop_y2);
    immVertex2f(pos, crop_x2, crop_y2 - corner_len);
    /* Top-left L */
    immVertex2f(pos, crop_x1, crop_y2);
    immVertex2f(pos, crop_x1 + corner_len, crop_y2);
    immVertex2f(pos, crop_x1, crop_y2);
    immVertex2f(pos, crop_x1, crop_y2 - corner_len);
    immEnd();

    /* 4 edge midpoint lines (1 line each = 8 vertices) */
    immBegin(GPU_PRIM_LINES, 8);
    /* Bottom edge - horizontal line */
    immVertex2f(pos, mid_x - edge_len / 2, crop_y1);
    immVertex2f(pos, mid_x + edge_len / 2, crop_y1);
    /* Right edge - vertical line */
    immVertex2f(pos, crop_x2, mid_y - edge_len / 2);
    immVertex2f(pos, crop_x2, mid_y + edge_len / 2);
    /* Top edge - horizontal line */
    immVertex2f(pos, mid_x - edge_len / 2, crop_y2);
    immVertex2f(pos, mid_x + edge_len / 2, crop_y2);
    /* Left edge - vertical line */
    immVertex2f(pos, crop_x1, mid_y - edge_len / 2);
    immVertex2f(pos, crop_x1, mid_y + edge_len / 2);
    immEnd();

    GPU_line_width(1.0f);
  }
  else if (active_tool == 3) {
    /* LASSO - draw completed polygons and the polygon currently being drawn. */
    auto draw_lasso_polygon = [&](PointerRNA &owner_ptr, PropertyRNA *points_prop) {
      int point_count = RNA_property_collection_length(&owner_ptr, points_prop);
      if (point_count < 2) {
        return;
      }

      /* Magenta outline for lasso */
      GPU_line_width(2.0f);
      immUniformColor4f(1.0f, 0.0f, 1.0f, 1.0f);
      immBegin(GPU_PRIM_LINE_STRIP, point_count);

      CollectionPropertyIterator points_iter{};
      RNA_property_collection_begin(&owner_ptr, points_prop, &points_iter);
      while (points_iter.valid) {
        PointerRNA point_ptr = points_iter.ptr;
        PropertyRNA *x_prop = RNA_struct_find_property(&point_ptr, "x");
        PropertyRNA *y_prop = RNA_struct_find_property(&point_ptr, "y");
        if (x_prop && y_prop) {
          float rel_x = RNA_property_float_get(&point_ptr, x_prop);
          float rel_y = RNA_property_float_get(&point_ptr, y_prop);
          immVertex2f(pos, pos_x + rel_x * display_width, pos_y + rel_y * display_height);
        }
        RNA_property_collection_next(&points_iter);
      }
      RNA_property_collection_end(&points_iter);
      immEnd();

      if (point_count >= 3) {
        PointerRNA first_point_ptr;
        PointerRNA last_point_ptr;
        RNA_property_collection_lookup_int(&owner_ptr, points_prop, 0, &first_point_ptr);
        RNA_property_collection_lookup_int(
            &owner_ptr, points_prop, point_count - 1, &last_point_ptr);
        PropertyRNA *first_x_prop = RNA_struct_find_property(&first_point_ptr, "x");
        PropertyRNA *first_y_prop = RNA_struct_find_property(&first_point_ptr, "y");
        PropertyRNA *last_x_prop = RNA_struct_find_property(&last_point_ptr, "x");
        PropertyRNA *last_y_prop = RNA_struct_find_property(&last_point_ptr, "y");
        if (first_x_prop && first_y_prop && last_x_prop && last_y_prop) {
          immUniformColor4f(1.0f, 0.0f, 1.0f, 0.5f);
          immBegin(GPU_PRIM_LINES, 2);
          immVertex2f(pos,
                      pos_x + RNA_property_float_get(&first_point_ptr, first_x_prop) * display_width,
                      pos_y + RNA_property_float_get(&first_point_ptr, first_y_prop) * display_height);
          immVertex2f(pos,
                      pos_x + RNA_property_float_get(&last_point_ptr, last_x_prop) * display_width,
                      pos_y + RNA_property_float_get(&last_point_ptr, last_y_prop) * display_height);
          immEnd();
        }
      }
    };

    PropertyRNA *loops_prop = RNA_struct_find_property(&state_ptr, "lasso_loops");
    if (loops_prop) {
      CollectionPropertyIterator loops_iter{};
      RNA_property_collection_begin(&state_ptr, loops_prop, &loops_iter);
      while (loops_iter.valid) {
        PointerRNA loop_ptr = loops_iter.ptr;
        PropertyRNA *points_prop = RNA_struct_find_property(&loop_ptr, "points");
        if (points_prop) {
          draw_lasso_polygon(loop_ptr, points_prop);
        }
        RNA_property_collection_next(&loops_iter);
      }
      RNA_property_collection_end(&loops_iter);
    }

    PropertyRNA *lasso_prop = RNA_struct_find_property(&state_ptr, "lasso_points");
    PropertyRNA *drawing_prop = RNA_struct_find_property(&state_ptr, "is_drawing");
    if (lasso_prop && drawing_prop && RNA_property_boolean_get(&state_ptr, drawing_prop)) {
      int point_count = RNA_property_collection_length(&state_ptr, lasso_prop);
      if (point_count >= 2) {
        GPU_line_width(2.0f);
        immUniformColor4f(1.0f, 0.0f, 1.0f, 1.0f);
        immBegin(GPU_PRIM_LINE_STRIP, point_count);

        CollectionPropertyIterator lasso_iter{};
        RNA_property_collection_begin(&state_ptr, lasso_prop, &lasso_iter);

        while (lasso_iter.valid) {
          PointerRNA point_ptr = lasso_iter.ptr;

          PropertyRNA *x_prop = RNA_struct_find_property(&point_ptr, "x");
          PropertyRNA *y_prop = RNA_struct_find_property(&point_ptr, "y");

          if (x_prop && y_prop) {
            float rel_x = RNA_property_float_get(&point_ptr, x_prop);
            float rel_y = RNA_property_float_get(&point_ptr, y_prop);

            /* Convert from image-relative (0-1) to canvas coords */
            float canvas_x = pos_x + rel_x * display_width;
            float canvas_y = pos_y + rel_y * display_height;

            immVertex2f(pos, canvas_x, canvas_y);
          }

          RNA_property_collection_next(&lasso_iter);
        }

        RNA_property_collection_end(&lasso_iter);
        immEnd();

        if (point_count >= 3) {
          PointerRNA first_point_ptr;
          RNA_property_collection_lookup_int(&state_ptr, lasso_prop, 0, &first_point_ptr);
          PointerRNA last_point_ptr;
          RNA_property_collection_lookup_int(
              &state_ptr, lasso_prop, point_count - 1, &last_point_ptr);

          PropertyRNA *x_prop_f = RNA_struct_find_property(&first_point_ptr, "x");
          PropertyRNA *y_prop_f = RNA_struct_find_property(&first_point_ptr, "y");
          PropertyRNA *x_prop_l = RNA_struct_find_property(&last_point_ptr, "x");
          PropertyRNA *y_prop_l = RNA_struct_find_property(&last_point_ptr, "y");

          if (x_prop_f && y_prop_f && x_prop_l && y_prop_l) {
            float first_x =
                pos_x + RNA_property_float_get(&first_point_ptr, x_prop_f) * display_width;
            float first_y =
                pos_y + RNA_property_float_get(&first_point_ptr, y_prop_f) * display_height;
            float last_x =
                pos_x + RNA_property_float_get(&last_point_ptr, x_prop_l) * display_width;
            float last_y =
                pos_y + RNA_property_float_get(&last_point_ptr, y_prop_l) * display_height;

            immUniformColor4f(1.0f, 0.0f, 1.0f, 0.5f);
            immBegin(GPU_PRIM_LINES, 2);
            immVertex2f(pos, last_x, last_y);
            immVertex2f(pos, first_x, first_y);
            immEnd();
          }
        }

        GPU_line_width(1.0f);
      }
    }
  }

  immUnbindProgram();
  GPU_blend(GPU_BLEND_NONE);
  GPU_matrix_pop();
}

/** \} */

}  // namespace blender::ed::mixie
