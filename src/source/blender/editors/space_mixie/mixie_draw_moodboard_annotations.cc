/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Persistent vector annotation drawing for moodboard images
 */

#include "mixie_draw_moodboard_intern.hh"

namespace blender::ed::mixie {

void mixie_draw_moodboard_annotations(PointerRNA *itemptr,
                                      View2D *v2d,
                                      const float pos_x,
                                      const float pos_y,
                                      const float display_width,
                                      const float display_height,
                                      const float image_scale)
{
  if (!g_img_props.annotations || !g_img_props.show_annotations ||
      !RNA_property_boolean_get(itemptr, g_img_props.show_annotations))
  {
    return;
  }

  const int stroke_count = RNA_property_collection_length(itemptr, g_img_props.annotations);
  if (stroke_count == 0) {
    return;
  }

  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  GPU_blend(GPU_BLEND_ALPHA);

  const float view_scale = std::max(ui::view2d_scale_get_x(v2d), 0.001f);
  CollectionPropertyIterator stroke_iter{};
  RNA_property_collection_begin(itemptr, g_img_props.annotations, &stroke_iter);
  while (stroke_iter.valid) {
    PointerRNA stroke_ptr = stroke_iter.ptr;
    PropertyRNA *points_prop = RNA_struct_find_property(&stroke_ptr, "points");
    PropertyRNA *color_prop = RNA_struct_find_property(&stroke_ptr, "color");
    PropertyRNA *width_prop = RNA_struct_find_property(&stroke_ptr, "width");
    if (!points_prop || !color_prop || !width_prop) {
      RNA_property_collection_next(&stroke_iter);
      continue;
    }

    const int point_count = RNA_property_collection_length(&stroke_ptr, points_prop);
    if (point_count == 0) {
      RNA_property_collection_next(&stroke_iter);
      continue;
    }

    float color[4];
    RNA_property_float_get_array(&stroke_ptr, color_prop, color);
    immUniformColor4fv(color);

    const float width = RNA_property_float_get(&stroke_ptr, width_prop);
    const float screen_width = std::clamp(width * image_scale * view_scale, 1.0f, 64.0f);
    GPU_line_width(screen_width);

    if (point_count == 1) {
      PointerRNA point_ptr;
      RNA_property_collection_lookup_int(&stroke_ptr, points_prop, 0, &point_ptr);
      PropertyRNA *x_prop = RNA_struct_find_property(&point_ptr, "x");
      PropertyRNA *y_prop = RNA_struct_find_property(&point_ptr, "y");
      if (x_prop && y_prop) {
        const float x = pos_x + RNA_property_float_get(&point_ptr, x_prop) * display_width;
        const float y = pos_y + RNA_property_float_get(&point_ptr, y_prop) * display_height;
        const float radius = std::max(width * image_scale * 0.25f, 0.5f / view_scale);
        immBegin(GPU_PRIM_LINES, 2);
        immVertex2f(pos, x - radius, y);
        immVertex2f(pos, x + radius, y);
        immEnd();
      }
    }
    else {
      immBegin(GPU_PRIM_LINE_STRIP, point_count);
      CollectionPropertyIterator point_iter{};
      RNA_property_collection_begin(&stroke_ptr, points_prop, &point_iter);
      while (point_iter.valid) {
        PointerRNA point_ptr = point_iter.ptr;
        PropertyRNA *x_prop = RNA_struct_find_property(&point_ptr, "x");
        PropertyRNA *y_prop = RNA_struct_find_property(&point_ptr, "y");
        if (x_prop && y_prop) {
          const float x = pos_x + RNA_property_float_get(&point_ptr, x_prop) * display_width;
          const float y = pos_y + RNA_property_float_get(&point_ptr, y_prop) * display_height;
          immVertex2f(pos, x, y);
        }
        RNA_property_collection_next(&point_iter);
      }
      RNA_property_collection_end(&point_iter);
      immEnd();
    }

    RNA_property_collection_next(&stroke_iter);
  }
  RNA_property_collection_end(&stroke_iter);

  GPU_line_width(1.0f);
  GPU_blend(GPU_BLEND_NONE);
  immUnbindProgram();
}

}  // namespace blender::ed::mixie
