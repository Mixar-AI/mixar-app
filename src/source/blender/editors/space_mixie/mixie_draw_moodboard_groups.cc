/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Moodboard group drawing for Mixie space
 */

#include "mixie_draw_moodboard_intern.hh"
#include "GPU_vertex_format.hh" /* For VertAttrType */

namespace blender::ed::mixie {

/* -------------------------------------------------------------------- */
/** \name Moodboard Groups Drawing
 * \{
 */

void mixie_draw_moodboard_groups(const bContext *C, View2D *v2d)
{
  Scene *scene = CTX_data_scene(C);
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  
  PropertyRNA *groups_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_groups");
  PropertyRNA *images_prop = RNA_struct_find_property(&scene_ptr, "mixie_moodboard_images");

  if (!groups_prop || !images_prop) {
    return;
  }

  int group_count = RNA_property_collection_length(&scene_ptr, groups_prop);
  int image_count = RNA_property_collection_length(&scene_ptr, images_prop);

  if (group_count == 0 || image_count == 0) {
    return;
  }

  /* Setup drawing state */
  /* Use the correct 3-argument version of GPU_vertformat_attr_add */
  /* SFLOAT_32_32 corresponds to 2 floats (vec2) for position */
  uint pos = GPU_vertformat_attr_add(immVertexFormat(), "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  GPU_line_width(3.0f);

  for (int i = 0; i < group_count; i++) {
    PointerRNA group_ptr;
    RNA_property_collection_lookup_int(&scene_ptr, groups_prop, i, &group_ptr);

    PropertyRNA *visible_prop = RNA_struct_find_property(&group_ptr, "visible");
    bool visible = visible_prop ? RNA_property_boolean_get(&group_ptr, visible_prop) : true;

    if (!visible) {
      continue;
    }

    /* Check if the group itself is selected */
    PropertyRNA *group_sel_prop = RNA_struct_find_property(&group_ptr, "selected");
    bool is_group_selected = group_sel_prop ? RNA_property_boolean_get(&group_ptr, group_sel_prop)
                                            : false;

    /* Also check if any individual image in this group is selected */
    bool any_image_selected = false;

    /* Calculate bounds */
    float min_x = FLT_MAX, min_y = FLT_MAX;
    float max_x = -FLT_MAX, max_y = -FLT_MAX;
    bool has_valid_bounds = false;

    /* Iterate all images */
    for (int j = 0; j < image_count; j++) {
      PointerRNA img_ptr;
      RNA_property_collection_lookup_int(&scene_ptr, images_prop, j, &img_ptr);

      PropertyRNA *grp_idx_prop = RNA_struct_find_property(&img_ptr, "group_index");
      int group_index = grp_idx_prop ? RNA_property_int_get(&img_ptr, grp_idx_prop) : -1;

      if (group_index != i) {
        continue;
      }

      PropertyRNA *sel_prop = RNA_struct_find_property(&img_ptr, "selected");
      if (sel_prop && RNA_property_boolean_get(&img_ptr, sel_prop)) {
        any_image_selected = true;
      }

      /* Calculate corners */
      PropertyRNA *image_prop = RNA_struct_find_property(&img_ptr, "image");
      if (!image_prop) continue;
      
      PointerRNA image_ptr = RNA_property_pointer_get(&img_ptr, image_prop);
      Image *image = (Image *)image_ptr.data;
      if (!image) continue;
      
      /* Get dimensions using ImBuf to correspond with legacy Image struct access */
      /* Note: BKE_image_acquire_ibuf returns an ImBuf with dimensions */
      int img_width = 0;
      int img_height = 0;
      
      /* Try to get cached texture dimensions first if available, similar to draw_images */
      blender::gpu::Texture *gpu_tex = BKE_image_get_gpu_texture(image, nullptr);
      if (gpu_tex) {
         img_width = GPU_texture_width(gpu_tex);
         img_height = GPU_texture_height(gpu_tex);
      }
      else {
         /* Fallback to ImBuf */
         void *lock;
         ImBuf *ibuf = BKE_image_acquire_ibuf(image, nullptr, &lock);
         if (ibuf) {
            img_width = ibuf->x;
            img_height = ibuf->y;
            BKE_image_release_ibuf(image, ibuf, lock);
         }
      }
      
      if (img_width <= 0 || img_height <= 0) {
         continue; 
      }

      PropertyRNA *px_prop = RNA_struct_find_property(&img_ptr, "position_x");
      PropertyRNA *py_prop = RNA_struct_find_property(&img_ptr, "position_y");
      PropertyRNA *s_prop = RNA_struct_find_property(&img_ptr, "scale");
      PropertyRNA *r_prop = RNA_struct_find_property(&img_ptr, "rotation");

      float pos_x = px_prop ? RNA_property_float_get(&img_ptr, px_prop) : 0.0f;
      float pos_y = py_prop ? RNA_property_float_get(&img_ptr, py_prop) : 0.0f;
      float scale = s_prop ? RNA_property_float_get(&img_ptr, s_prop) : 1.0f;
      float rotation = r_prop ? RNA_property_float_get(&img_ptr, r_prop) : 0.0f; // Radians

      float aspect = (float)img_height / (float)img_width;
      
      float w = MOODBOARD_IMAGE_BASE_SIZE * scale;
      float h = MOODBOARD_IMAGE_BASE_SIZE * aspect * scale;
      
      /* mixie_draw_moodboard_images draws quad at (pos_x, pos_y) with size (w, h)
         and then rotates around center.
         Center is: */
      float cx = pos_x + w / 2.0f;
      float cy = pos_y + h / 2.0f;
      
      /* Corners relative to center */
      float corners[4][2] = {
        {-w/2.0f, -h/2.0f},
        { w/2.0f, -h/2.0f},
        { w/2.0f,  h/2.0f},
        {-w/2.0f,  h/2.0f}
      };
      
      float cos_a = cosf(rotation);
      float sin_a = sinf(rotation);
      
      for (int k = 0; k < 4; k++) {
        float rx = corners[k][0] * cos_a - corners[k][1] * sin_a;
        float ry = corners[k][0] * sin_a + corners[k][1] * cos_a;
        
        float world_x = cx + rx;
        float world_y = cy + ry;
        
        min_x = std::min(min_x, world_x);
        min_y = std::min(min_y, world_y);
        max_x = std::max(max_x, world_x);
        max_y = std::max(max_y, world_y);
        has_valid_bounds = true;
      }
    }

    /* Draw bounding box if group is selected OR any individual image in group is selected */
    if ((is_group_selected || any_image_selected) && has_valid_bounds) {
      float color[4] = {0.2f, 0.6f, 1.0f, 1.0f}; // Default
      PropertyRNA *color_prop = RNA_struct_find_property(&group_ptr, "color");
      if (color_prop) {
        RNA_property_float_get_array(&group_ptr, color_prop, color);
      }
      
      immUniformColor4fv(color);
      
      /* Padding */
      float padding = 10.0f;
      min_x -= padding;
      min_y -= padding;
      max_x += padding;
      max_y += padding;

      immBegin(GPU_PRIM_LINE_STRIP, 5);
      immVertex2f(pos, min_x, min_y);
      immVertex2f(pos, max_x, min_y);
      immVertex2f(pos, max_x, max_y);
      immVertex2f(pos, min_x, max_y);
      immVertex2f(pos, min_x, min_y);
      immEnd();

      /* Draw resize handles on group bounding box (only when group itself is selected) */
      if (is_group_selected) {
        float handle_size_px = 12.0f;
        float handle_size = handle_size_px / UI_view2d_scale_get_x(v2d);

        float width = max_x - min_x;
        float height = max_y - min_y;

        /* 8 handle positions: 4 corners + 4 edge midpoints */
        float handle_positions[8][2] = {
            {min_x, min_y},                    /* 0: Bottom-left */
            {min_x + width / 2, min_y},        /* 1: Bottom-center */
            {max_x, min_y},                    /* 2: Bottom-right */
            {max_x, min_y + height / 2},       /* 3: Right-center */
            {max_x, max_y},                    /* 4: Top-right */
            {min_x + width / 2, max_y},        /* 5: Top-center */
            {min_x, max_y},                    /* 6: Top-left */
            {min_x, min_y + height / 2}        /* 7: Left-center */
        };

        /* Draw white handles */
        immUniformColor4f(1.0f, 1.0f, 1.0f, 1.0f);
        for (int h = 0; h < 8; h++) {
          immRectf(pos,
                   handle_positions[h][0] - handle_size / 2,
                   handle_positions[h][1] - handle_size / 2,
                   handle_positions[h][0] + handle_size / 2,
                   handle_positions[h][1] + handle_size / 2);
        }
      }
    }
  }

  immUnbindProgram();
  GPU_line_width(1.0f);
}

/** \} */

}  // namespace blender::ed::mixie