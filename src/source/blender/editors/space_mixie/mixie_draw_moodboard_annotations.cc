/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Persistent vector annotation drawing for moodboard images and canvas
 */

#include "mixie_draw_moodboard_intern.hh"

#include "BLI_math_vector_types.hh"
#include "BLI_vector.hh"

namespace blender::ed::mixie {

/* Semicircle samples, built once. Each cap rotates this table by its start
 * angle instead of calling cos/sin sixteen times per end per redraw. */
struct CapUnitCircle {
  float cos_v[17];
  float sin_v[17];
  CapUnitCircle()
  {
    for (int i = 0; i <= 16; i++) {
      const float angle = float(M_PI) * float(i) / 16.0f;
      cos_v[i] = std::cos(angle);
      sin_v[i] = std::sin(angle);
    }
  }
};

static const CapUnitCircle &cap_unit_circle()
{
  static const CapUnitCircle circle;
  return circle;
}

/* A connected ribbon keeps joins closed on every GPU backend. Separate outer
 * strips fade over one physical pixel; caps use the same coverage, without
 * overlapping translucent discs at every sampled point. */
static void draw_stroke_ribbon(const Vector<float2> &points,
                               const float color[4],
                               const float screen_width,
                               const float view_scale)
{
  const auto normalized = [](const float2 v) {
    const float length = std::sqrt(v.x * v.x + v.y * v.y);
    return length > 1.0e-8f ? v / length : float2(1.0f, 0.0f);
  };
  const float inner = std::max(0.0f, (screen_width - 1.0f) * 0.5f) / view_scale;
  const float outer = (screen_width + 1.0f) * 0.5f / view_scale;
  Vector<float2> offsets;
  for (int i = 0; i < points.size(); i++) {
    const float2 before = i > 0 ? normalized(points[i] - points[i - 1]) :
                                 (points.size() > 1 ? normalized(points[1] - points[0]) :
                                                      float2(1.0f, 0.0f));
    const float2 after = i + 1 < points.size() ? normalized(points[i + 1] - points[i]) :
                                               before;
    const float2 n_before(-before.y, before.x), n_after(-after.y, after.x);
    const float2 sum = n_before + n_after;
    const float2 miter = sum.x * sum.x + sum.y * sum.y > 1.0e-8f ? normalized(sum) : n_after;
    const float dot = miter.x * n_after.x + miter.y * n_after.y;
    offsets.append(miter / std::max(dot, 0.5f));
  }

  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  const uint col = GPU_vertformat_attr_add(format, "color", gpu::VertAttrType::SFLOAT_32_32_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_SMOOTH_COLOR);
  const auto vertex = [&](const float2 point, const float alpha) {
    immAttr4f(col, color[0], color[1], color[2], color[3] * alpha);
    immVertex2f(pos, point.x, point.y);
  };
  const auto strip = [&](const float a, const float b, const float alpha_a, const float alpha_b) {
    immBegin(GPU_PRIM_TRI_STRIP, points.size() * 2);
    for (int i = 0; i < points.size(); i++) {
      vertex(points[i] + offsets[i] * a, alpha_a);
      vertex(points[i] + offsets[i] * b, alpha_b);
    }
    immEnd();
  };
  if (points.size() > 1) {
    strip(-inner, inner, 1.0f, 1.0f);
    strip(-outer, -inner, 0.0f, 1.0f);
    strip(inner, outer, 1.0f, 0.0f);
  }
  const auto cap = [&](const float2 center, const float start) {
    constexpr int segments = 16;
    const float start_cos = std::cos(start);
    const float start_sin = std::sin(start);
    const CapUnitCircle &circle = cap_unit_circle();
    const auto direction = [&](const int i) {
      return float2(start_cos * circle.cos_v[i] - start_sin * circle.sin_v[i],
                    start_sin * circle.cos_v[i] + start_cos * circle.sin_v[i]);
    };
    immBegin(GPU_PRIM_TRIS, segments * 3);
    for (int i = 0; i < segments; i++) {
      vertex(center, 1.0f);
      vertex(center + direction(i) * inner, 1.0f);
      vertex(center + direction(i + 1) * inner, 1.0f);
    }
    immEnd();
    immBegin(GPU_PRIM_TRI_STRIP, (segments + 1) * 2);
    for (int i = 0; i <= segments; i++) {
      vertex(center + direction(i) * inner, 1.0f);
      vertex(center + direction(i) * outer, 0.0f);
    }
    immEnd();
  };
  cap(points.first(), std::atan2(offsets.first().y, offsets.first().x));
  cap(points.last(), std::atan2(offsets.last().y, offsets.last().x) - float(M_PI));
  immUnbindProgram();
}

static void draw_annotation_strokes(PointerRNA *itemptr,
                                    PropertyRNA *annotations,
                                    View2D *v2d,
                                    const float pos_x,
                                    const float pos_y,
                                    const float display_width,
                                    const float display_height,
                                    const float image_scale)
{
  const float view_scale = std::max(ui::view2d_scale_get_x(v2d), 0.001f);
  GPU_blend(GPU_BLEND_ALPHA);
  CollectionPropertyIterator stroke_iter{};
  RNA_property_collection_begin(itemptr, annotations, &stroke_iter);
  while (stroke_iter.valid) {
    PointerRNA stroke_ptr = stroke_iter.ptr;
    PropertyRNA *points_prop = RNA_struct_find_property(&stroke_ptr, "points");
    PropertyRNA *color_prop = RNA_struct_find_property(&stroke_ptr, "color");
    PropertyRNA *width_prop = RNA_struct_find_property(&stroke_ptr, "width");
    if (!points_prop || !color_prop || !width_prop) {
      RNA_property_collection_next(&stroke_iter);
      continue;
    }
    Vector<float2> points;
    CollectionPropertyIterator point_iter{};
    RNA_property_collection_begin(&stroke_ptr, points_prop, &point_iter);
    while (point_iter.valid) {
      PointerRNA point_ptr = point_iter.ptr;
      const float2 point(pos_x + RNA_float_get(&point_ptr, "x") * display_width,
                         pos_y + RNA_float_get(&point_ptr, "y") * display_height);
      if (points.is_empty() || point != points.last()) {
        points.append(point);
      }
      RNA_property_collection_next(&point_iter);
    }
    RNA_property_collection_end(&point_iter);
    if (!points.is_empty()) {
      float color[4];
      RNA_property_float_get_array(&stroke_ptr, color_prop, color);
      const float width = RNA_property_float_get(&stroke_ptr, width_prop);
      const float screen_width = std::clamp(width * image_scale * view_scale, 1.0f, 64.0f);
      draw_stroke_ribbon(points, color, screen_width, view_scale);
    }
    RNA_property_collection_next(&stroke_iter);
  }
  RNA_property_collection_end(&stroke_iter);
  GPU_blend(GPU_BLEND_NONE);
}

void mixie_draw_moodboard_annotations(PointerRNA *itemptr,
                                      View2D *v2d,
                                      const float pos_x,
                                      const float pos_y,
                                      const float display_width,
                                      const float display_height,
                                      const float image_scale)
{
  if (g_img_props.annotations && g_img_props.show_annotations &&
      RNA_property_boolean_get(itemptr, g_img_props.show_annotations))
  {
    draw_annotation_strokes(itemptr, g_img_props.annotations, v2d, pos_x, pos_y,
                            display_width, display_height, image_scale);
  }
}

void mixie_draw_moodboard_canvas_annotations(PointerRNA *scene, View2D *v2d)
{
  PropertyRNA *strokes = RNA_struct_find_property(scene, "mixie_moodboard_annotations");
  PropertyRNA *visible = RNA_struct_find_property(scene, "mixie_moodboard_show_annotations");
  if (strokes && visible && RNA_property_boolean_get(scene, visible)) {
    /* Points and widths are already in canvas units; never inherit an image transform. */
    draw_annotation_strokes(scene, strokes, v2d, 0.0f, 0.0f, 1.0f, 1.0f, 1.0f);
  }
}

}  // namespace blender::ed::mixie
