/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup wm
 *
 * \name Custom Orientation/Navigation Gizmo for the 3D View
 *
 * \brief Simple gizmo to axis and translate.
 *
 * - scale_basis: used for the size.
 * - matrix_basis: used for the location.
 * - matrix_offset: used to store the orientation.
 */

#include <algorithm>

#include "BLI_math_constants.h" /* MIXAR: M_PI, for the globe's ring sampling. */
#include "BLI_math_matrix.h"
#include "BLI_math_vector.h"
#include "BLI_math_vector_types.hh"
#include "BLI_sort_utils.h"

#include "BKE_context.hh"

#include "GPU_immediate.hh"
#include "GPU_matrix.hh"
#include "GPU_state.hh"

#include "BLF_api.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_intern.hh"

/* Radius of the entire background. */
#define WIDGET_RADIUS ((U.gizmo_size_navigate_v3d / 2.0f) * UI_SCALE_FAC)

/* Sizes of axis spheres containing XYZ characters in relation to above. */
#define AXIS_HANDLE_SIZE 0.20f

#define AXIS_LINE_WIDTH ((U.gizmo_size_navigate_v3d / 40.0f) * U.pixelsize)
#define AXIS_RING_WIDTH ((U.gizmo_size_navigate_v3d / 60.0f) * U.pixelsize)
#define AXIS_TEXT_SIZE (WIDGET_RADIUS * AXIS_HANDLE_SIZE * 1.25f)

/* distance within this from center is considered positive. */
#define AXIS_DEPTH_BIAS 0.01f

/* -------------------------------------------------------------------- */
/** \name MIXAR: Globe navigation icon
 *
 * Mixar replaces Blender's RGB axis-ball artwork with a wireframe globe (see
 * the product design). Only the DRAWING changes — `gizmo_axis_test_select`,
 * the cursor and the screen bounds below are untouched, so hit-testing,
 * drag-to-orbit and click-to-snap-to-axis behave exactly as before.
 *
 * The globe is the three great circles of the XY / XZ / YZ planes drawn
 * through the gizmo's existing `matrix_offset` rotation, so the ellipses
 * reshape as the view orbits (a static ellipse pair would not track the
 * view). Each ring is tinted by the axis NORMAL to its plane — the same
 * convention as Blender's rotate gizmo, where the red ring turns about X —
 * and fades toward the far side of the sphere so the near half reads as
 * being in front.
 *
 * Design proportions: stroke 1.60714 at globe radius 21.6964, i.e. the
 * gizmo's full diameter / 27.
 * \{ */

#define GLOBE_LINE_WIDTH ((U.gizmo_size_navigate_v3d / 27.0f) * U.pixelsize)
#define GLOBE_RING_SEGMENTS 64

/* Silhouette ring, #494949 at 24% (design). Deliberately faint in both light
 * and dark themes — it only has to hint at the sphere's edge. */
#define GLOBE_SILHOUETTE_COLOR \
  { \
    0.286f, 0.286f, 0.286f, 0.24f \
  }

/**
 * Draw one great circle of the unit sphere as a line strip.
 *
 * \param normal_axis: the axis perpendicular to the circle's plane (0=X, 1=Y, 2=Z).
 * \param depth_axis: view-space Z of the gizmo's rotation (the third row of
 * `matrix_offset`), used to fade the far half. Pass nullptr for a ring that
 * is already screen-aligned (the silhouette), which keeps a constant alpha.
 */
static void gizmo_globe_ring_draw(const int normal_axis,
                                  const float color[4],
                                  const float depth_axis[3],
                                  const float viewport_size[4])
{
  GPUVertFormat *format = immVertexFormat();
  const uint pos_id = GPU_vertformat_attr_add(
      format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32_32);
  const uint color_id = GPU_vertformat_attr_add(
      format, "color", blender::gpu::VertAttrType::SFLOAT_32_32_32_32);

  immBindBuiltinProgram(GPU_SHADER_3D_POLYLINE_SMOOTH_COLOR);
  immUniform2fv("viewportSize", &viewport_size[2]);
  immUniform1f("lineWidth", GLOBE_LINE_WIDTH);

  immBegin(GPU_PRIM_LINE_STRIP, GLOBE_RING_SEGMENTS + 1);
  for (int i = 0; i <= GLOBE_RING_SEGMENTS; i++) {
    const float angle = (float(i) / float(GLOBE_RING_SEGMENTS)) * (2.0f * float(M_PI));
    float p[3] = {0.0f, 0.0f, 0.0f};
    p[(normal_axis + 1) % 3] = cosf(angle);
    p[(normal_axis + 2) % 3] = sinf(angle);

    float vert_color[4] = {color[0], color[1], color[2], color[3]};
    if (depth_axis != nullptr) {
      /* -1 at the back of the sphere, +1 at the front. Squaring the
       * front-ness keeps the far half faint without losing it entirely, so
       * the flat projection still reads as a sphere from every angle. */
      const float front = (dot_v3v3(p, depth_axis) + 1.0f) * 0.5f;
      /* Cubic falloff: the design's gradients reach full transparency on
       * the far side, so a squared ramp still left the back half too
       * present at ring scale. */
      vert_color[3] = color[3] * (0.06f + (0.94f * front * front * front));
    }
    immAttr4fv(color_id, vert_color);
    immVertex3fv(pos_id, p);
  }
  immEnd();
  immUnbindProgram();
}

/** \} */

static void gizmo_axis_draw(const bContext * /*C*/, wmGizmo *gz)
{
  /* When the cursor is over any of the gizmos (show circle backdrop). */
  const bool is_active = ((gz->state & WM_GIZMO_STATE_HIGHLIGHT) != 0);

  float matrix_screen[4][4];
  float matrix_unit[4][4];
  unit_m4(matrix_unit);

  WM_GizmoMatrixParams params{};
  params.matrix_offset = matrix_unit;
  WM_gizmo_calc_matrix_final_params(gz, &params, matrix_screen);
  GPU_matrix_push();
  GPU_matrix_mul(matrix_screen);

  float viewport_size[4];
  GPU_viewport_size_get_f(viewport_size);

  /* Third row of the gizmo's rotation: the view-space depth of a local point
   * is its dot product with this (matching how the axis handles derive their
   * depth from `matrix_offset[axis][2]`). */
  const float depth_axis[3] = {
      gz->matrix_offset[0][2],
      gz->matrix_offset[1][2],
      gz->matrix_offset[2][2],
  };

  bool use_project_matrix = (gz->scale_final >= -GPU_MATRIX_ORTHO_CLIP_NEAR_DEFAULT);
  if (use_project_matrix) {
    GPU_matrix_push_projection();
    GPU_matrix_ortho_set_z(-gz->scale_final, gz->scale_final);
  }

  UI_draw_roundbox_corner_set(UI_CNR_ALL);
  GPU_polygon_smooth(false);
  GPU_blend(GPU_BLEND_ALPHA);

  /* Circle defining active area. */
  if (is_active) {
    const float rad = WIDGET_RADIUS;
    GPU_matrix_push();
    GPU_matrix_scale_1f(1.0f / rad);

    rctf rect{};
    rect.xmin = -rad;
    rect.xmax = rad;
    rect.ymin = -rad;
    rect.ymax = rad;
    UI_draw_roundbox_4fv(&rect, true, rad, gz->color_hi);
    GPU_matrix_pop();
  }

  /* Silhouette: a screen-aligned ring on the sphere's outline, so it never
   * changes shape as the view orbits. */
  {
    const float silhouette_color[4] = GLOBE_SILHOUETTE_COLOR;
    gizmo_globe_ring_draw(2, silhouette_color, nullptr, viewport_size);
  }

  /* The three great circles, rotated with the view.
   *
   * MIXAR: tints come from the DESIGN export, not from the theme's axis
   * colours. The theme's are fully saturated primaries meant for axis
   * lines; at ring scale they read as a bright RGB toy, where the design
   * is a muted globe that recedes into the viewport. Order matches
   * `gizmo_globe_ring_draw`'s plane->axis mapping (ring normal to X, Y, Z). */
  const float ring_colors[3][4] = {
      {0.329f, 0.173f, 0.173f, 0.85f}, /* #542C2C — equator (normal X). */
      {0.094f, 0.612f, 0.310f, 0.80f}, /* #189C4F — meridian (normal Y). */
      {0.000f, 0.369f, 1.000f, 0.80f}, /* #005EFF — meridian (normal Z). */
  };
  GPU_matrix_push();
  GPU_matrix_mul(gz->matrix_offset);
  for (int axis = 0; axis < 3; axis++) {
    gizmo_globe_ring_draw(axis, ring_colors[axis], depth_axis, viewport_size);
  }
  GPU_matrix_pop();

  /* Hovered axis marker.
   *
   * MIXAR: the design has no axis balls, so nothing marks the six axis click
   * targets at rest — but those targets still exist (see
   * `gizmo_axis_test_select`, unchanged), and without any feedback
   * click-to-snap becomes undiscoverable. A single dot under the cursor
   * keeps the interaction legible while leaving the resting artwork exactly
   * as designed. Delete this block to get the pure design at all times. */
  if (gz->highlight_part >= 1 && gz->highlight_part <= 6) {
    const int part = gz->highlight_part - 1;
    const int axis = part / 2;
    const bool is_pos = (part % 2) != 0;

    float v_local[3] = {0.0f, 0.0f, 0.0f};
    v_local[axis] = (1.0f - AXIS_HANDLE_SIZE) * (is_pos ? 1.0f : -1.0f);

    float m3_offset[3][3];
    copy_m3_m4(m3_offset, gz->matrix_offset);
    float v_rot[3];
    mul_v3_m3v3(v_rot, m3_offset, v_local);

    float dot_color[4];
    UI_GetThemeColor3fv(TH_AXIS_X + axis, dot_color);
    /* Depth of this axis handle, exactly as the upstream artwork derived it,
     * so a marker on the far side of the sphere reads as being behind it. */
    const float depth = gz->matrix_offset[axis][2] * (is_pos ? 1.0f : -1.0f);
    dot_color[3] = 0.35f + (0.65f * ((depth + 1.0f) * 0.5f));

    const float rad = WIDGET_RADIUS * AXIS_HANDLE_SIZE * 0.55f;
    GPU_matrix_push();
    GPU_matrix_translate_3fv(v_rot);
    GPU_matrix_scale_1f(1.0f / WIDGET_RADIUS);

    rctf rect{};
    rect.xmin = -rad;
    rect.xmax = rad;
    rect.ymin = -rad;
    rect.ymax = rad;
    UI_draw_roundbox_4fv(&rect, true, rad, dot_color);
    GPU_matrix_pop();
  }

  if (use_project_matrix) {
    GPU_matrix_pop_projection();
  }

  GPU_blend(GPU_BLEND_NONE);
  GPU_matrix_pop();
}

static int gizmo_axis_test_select(bContext * /*C*/, wmGizmo *gz, const int mval[2])
{
  float point_local[2] = {float(mval[0]), float(mval[1])};
  sub_v2_v2(point_local, gz->matrix_basis[3]);
  mul_v2_fl(point_local, 1.0f / gz->scale_final);

  const float len_sq = len_squared_v2(point_local);
  if (len_sq > 1.0) {
    return -1;
  }

  int part_best = -1;
  int part_index = 1;
  /* Use 'SQUARE(HANDLE_SIZE)' if we want to be able to _not_ focus on one of the axis. */
  float i_best_len_sq = FLT_MAX;
  for (int i = 0; i < 3; i++) {
    for (int is_pos = 0; is_pos < 2; is_pos++) {
      const float co[2] = {
          gz->matrix_offset[i][0] * (is_pos ? 1 : -1),
          gz->matrix_offset[i][1] * (is_pos ? 1 : -1),
      };

      bool ok = true;

      /* Check if we're viewing on an axis,
       * there is no point to clicking on the current axis so show the reverse. */
      if (len_squared_v2(co) < 1e-6f && (gz->matrix_offset[i][2] > 0.0f) == is_pos) {
        ok = false;
      }

      if (ok) {
        const float len_axis_sq = len_squared_v2v2(co, point_local);
        if (len_axis_sq < i_best_len_sq) {
          part_best = part_index;
          i_best_len_sq = len_axis_sq;
        }
      }
      part_index += 1;
    }
  }

  if (part_best != -1) {
    return part_best;
  }

  /* The 'gz->scale_final' is already applied when projecting. */
  if (len_sq < 1.0f) {
    return 0;
  }

  return -1;
}

static int gizmo_axis_cursor_get(wmGizmo * /*gz*/)
{
  return WM_CURSOR_DEFAULT;
}

static bool gizmo_axis_screen_bounds_get(bContext *C, wmGizmo *gz, rcti *r_bounding_box)
{
  ScrArea *area = CTX_wm_area(C);
  const float rad = WIDGET_RADIUS;
  r_bounding_box->xmin = gz->matrix_basis[3][0] + area->totrct.xmin - rad;
  r_bounding_box->ymin = gz->matrix_basis[3][1] + area->totrct.ymin - rad;
  r_bounding_box->xmax = r_bounding_box->xmin + rad;
  r_bounding_box->ymax = r_bounding_box->ymin + rad;
  return true;
}

void VIEW3D_GT_navigate_rotate(wmGizmoType *gzt)
{
  /* identifiers */
  gzt->idname = "VIEW3D_GT_navigate_rotate";

  /* API callbacks. */
  gzt->draw = gizmo_axis_draw;
  gzt->test_select = gizmo_axis_test_select;
  gzt->cursor_get = gizmo_axis_cursor_get;
  gzt->screen_bounds_get = gizmo_axis_screen_bounds_get;

  gzt->struct_size = sizeof(wmGizmo);
}
