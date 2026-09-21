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
#include <cmath>

#include "BLI_math_constants.h" /* MIXAR: M_PI, for the globe ring sampling. */
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
#include "UI_mixar.hh"
#include "UI_resources.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_intern.hh"

namespace blender {

/* Size of main icon (50% smaller for Mixar viewport layout). */
#define GIZMO_SIZE (U.gizmo_size_navigate_v3d * 0.5f)

/* Radius of the entire background. */
#define WIDGET_RADIUS ((GIZMO_SIZE / 2.0f) * UI_SCALE_FAC)

/* Sizes of axis spheres containing XYZ characters in relation to above. */
#define AXIS_HANDLE_SIZE 0.20f

/* MIXAR: hovered-axis readout. Text scales with the widget so the capsule is
 * the same shape at every UI scale; the floor keeps it legible if the user
 * shrinks `gizmo_size_navigate_v3d`. The far side of the sphere only dims to
 * `MARKER_ALPHA_BACK` — the marker is a cursor readout, so it stays readable
 * behind the globe where the rings themselves fade out. */
#define MARKER_TEXT_SIZE_MIN (9.0f * UI_SCALE_FAC)
#define MARKER_TEXT_SIZE_FAC 0.46f
#define MARKER_ALPHA_BACK 0.72f

#define AXIS_LINE_WIDTH ((GIZMO_SIZE / 40.0f) * U.pixelsize)
#define AXIS_RING_WIDTH ((GIZMO_SIZE / 60.0f) * U.pixelsize)
#define AXIS_TEXT_SIZE (WIDGET_RADIUS * AXIS_HANDLE_SIZE * 1.25f)

/* distance within this from center is considered positive. */
#define AXIS_DEPTH_BIAS 0.01f

/**
 * ONE colour per axis, shared by the globe's rings and the hover marker so
 * the two can never drift apart.
 *
 * Blender's THEME axis colours are not used: `axis_y` is a yellow-green and
 * `axis_x` a pink-red, neither of which belongs to this globe. These are the
 * design's own hues at marker strength; the rings scale them down (see
 * `GLOBE_AXIS_TINT_SCALE`) to stay recessive.
 */
static const float axis_colors[3][4] = {
    {0.878f, 0.263f, 0.286f, 1.0f}, /* #E04349 — X. */
    {0.094f, 0.612f, 0.310f, 1.0f}, /* #189C4F — Y. */
    {0.000f, 0.369f, 1.000f, 1.0f}, /* #005EFF — Z. */
};

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
 * view). They fade toward the far side of the sphere so the near half reads
 * as being in front.
 *
 * Tinting is per VERTEX, by the direction that vertex points (see
 * `gizmo_globe_axis_tint`), never one flat colour per ring. No ring can
 * carry an axis's colour as a whole: each passes through four of the six
 * axis handles and misses only its own two poles. Tinting by the normal —
 * Blender's rotate-gizmo convention — therefore paints the ground circle
 * blue while it runs through the red +X and green +Y handles and past the
 * viewport's own red X / green Y grid lines.
 *
 * Design proportions: stroke 1.60714 at globe radius 21.6964, i.e. the
 * gizmo's full diameter / 27.
 * \{ */

#define GLOBE_LINE_WIDTH ((GIZMO_SIZE / 27.0f) * U.pixelsize)
#define GLOBE_RING_SEGMENTS 64

/* One alpha for all three rings: with a per-vertex tint they no longer have
 * separate identities to weight against each other. */
#define GLOBE_RING_ALPHA 0.82f

/* The rings run the axis hues muted, so the globe still recedes into the
 * viewport instead of reading as a bright RGB toy at ring scale. */
#define GLOBE_AXIS_TINT_SCALE 0.70f

/* Blend exponent (weights are |p_i| to this power, normalised): high keeps
 * each hue pure almost all the way round and turns over only near a
 * 45-degree crossing, where a squared weighting spends a long arc as olive. */
#define GLOBE_AXIS_TINT_POWER 6.0f

/* Silhouette ring, #494949 at 24% (design). Deliberately faint in both light
 * and dark themes — it only has to hint at the sphere's edge. */
#define GLOBE_SILHOUETTE_COLOR \
  { \
    0.286f, 0.286f, 0.286f, 0.24f \
  }

/**
 * The colour of a point on the sphere: the axis it is pointing at.
 *
 * \param p: a unit vector in the gizmo's local space.
 *
 * A point sitting on an axis gets that axis's colour exactly. `p` is a unit
 * vector, so one component is always >= 1/sqrt(3) and the total cannot be
 * zero; the guard is for a caller that hands over something else.
 */
static void gizmo_globe_axis_tint(const float p[3], float r_color[3])
{
  float weight[3];
  float total = 0.0f;
  for (int i = 0; i < 3; i++) {
    weight[i] = powf(fabsf(p[i]), GLOBE_AXIS_TINT_POWER);
    total += weight[i];
  }
  if (!(total > 0.0f)) {
    copy_v3_v3(r_color, axis_colors[0]);
    return;
  }
  for (int c = 0; c < 3; c++) {
    float channel = 0.0f;
    for (int i = 0; i < 3; i++) {
      channel += (weight[i] / total) * axis_colors[i][c];
    }
    r_color[c] = std::min(1.0f, channel * GLOBE_AXIS_TINT_SCALE);
  }
}

/**
 * Draw one great circle of the unit sphere as a line strip.
 *
 * \param normal_axis: the axis perpendicular to the circle's plane (0=X, 1=Y, 2=Z).
 * \param color: a flat colour for the whole ring, or nullptr to tint every
 * vertex by the axis it points at (what the three globe rings do).
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
      format, "pos", gpu::VertAttrType::SFLOAT_32_32_32);
  const uint color_id = GPU_vertformat_attr_add(
      format, "color", gpu::VertAttrType::SFLOAT_32_32_32_32);

  immBindBuiltinProgram(GPU_SHADER_3D_POLYLINE_SMOOTH_COLOR);
  immUniform2fv("viewportSize", &viewport_size[2]);
  immUniform1f("lineWidth", GLOBE_LINE_WIDTH);

  immBegin(GPU_PRIM_LINE_STRIP, GLOBE_RING_SEGMENTS + 1);
  for (int i = 0; i <= GLOBE_RING_SEGMENTS; i++) {
    const float angle = (float(i) / float(GLOBE_RING_SEGMENTS)) * (2.0f * float(M_PI));
    float p[3] = {0.0f, 0.0f, 0.0f};
    p[(normal_axis + 1) % 3] = cosf(angle);
    p[(normal_axis + 2) % 3] = sinf(angle);

    float vert_color[4] = {1.0f, 1.0f, 1.0f, GLOBE_RING_ALPHA};
    if (color != nullptr) {
      copy_v4_v4(vert_color, color);
    }
    else {
      gizmo_globe_axis_tint(p, vert_color);
    }
    const float base_alpha = vert_color[3];
    if (depth_axis != nullptr) {
      /* -1 at the back of the sphere, +1 at the front. Squaring the
       * front-ness keeps the far half faint without losing it entirely, so
       * the flat projection still reads as a sphere from every angle. */
      const float front = (dot_v3v3(p, depth_axis) + 1.0f) * 0.5f;
      /* Cubic falloff: the design's gradients reach full transparency on
       * the far side, so a squared ramp still left the back half too
       * present at ring scale. */
      vert_color[3] = base_alpha * (0.06f + (0.94f * front * front * front));
    }
    immAttr4fv(color_id, vert_color);
    immVertex3fv(pos_id, p);
  }
  immEnd();
  immUnbindProgram();
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name MIXAR: Hovered axis readout
 *
 * The design has no axis balls, so nothing marks the six axis click targets
 * at rest — but those targets still exist (`gizmo_axis_test_select`,
 * unchanged, highlights the nearest one as soon as the cursor enters the
 * circle), and a bare dot only says "something is here". It does not say
 * WHICH axis, nor which END of it, and click-to-snap sends the view
 * somewhere the user did not choose.
 *
 * So the marker is a labelled capsule: filled with that axis's colour and
 * carrying its letter and sign, so `+X` and `-X` can never be confused.
 * Nothing about hit-testing changes.
 * \{ */

/**
 * Draw the readout for the axis handle under the cursor.
 *
 * \param axis: 0=X, 1=Y, 2=Z.
 * \param is_pos: the handle on the positive end of that axis.
 */
static void gizmo_axis_marker_draw(const wmGizmo *gz, const int axis, const bool is_pos)
{
  float v_local[3] = {0.0f, 0.0f, 0.0f};
  v_local[axis] = 1.0f * (is_pos ? 1.0f : -1.0f);

  float m3_offset[3][3];
  copy_m3_m4(m3_offset, gz->matrix_offset);
  float v_rot[3];
  mul_v3_m3v3(v_rot, m3_offset, v_local);

  /* Sign first: the direction is what a bare dot could never show. */
  const char label[3] = {is_pos ? '+' : '-', char('X' + axis), '\0'};

  /* Capsule metrics in pixels. The height floor is the resting handle size,
   * so the marker is never smaller than the dot it replaces. */
  const float text_size = std::max(MARKER_TEXT_SIZE_MIN, WIDGET_RADIUS * MARKER_TEXT_SIZE_FAC);
  const float text_width = ui::mixar_text_width(label, text_size);
  const float half_h = std::max(WIDGET_RADIUS * AXIS_HANDLE_SIZE * 1.25f, text_size * 0.78f);
  const float half_w = std::max(half_h, (text_width * 0.5f) + (text_size * 0.45f));

  /* Keep the capsule inside the widget circle by pulling it in along its own
   * direction — `gizmo_axis_screen_bounds_get` is the gizmo's redraw rect and
   * stays untouched, so the marker must not spill past `WIDGET_RADIUS`. The
   * extent is the capsule box's support function along that direction, so a
   * marker at the rim ends exactly on it instead of being pulled to the
   * bounding circle of its own diagonal. */
  float dir[2] = {v_rot[0], v_rot[1]};
  const float dir_len = len_v2(dir);
  if (dir_len > 1e-5f) {
    mul_v2_fl(dir, 1.0f / dir_len);
    const float extent = ((fabsf(dir[0]) * half_w) + (fabsf(dir[1]) * half_h)) / WIDGET_RADIUS;
    const float radius = std::min(dir_len, std::max(0.0f, 1.0f - extent));
    v_rot[0] = dir[0] * radius;
    v_rot[1] = dir[1] * radius;
  }

  /* Depth of this axis handle, exactly as the upstream artwork derived it,
   * so a marker on the far side of the sphere reads as being behind it. */
  const float depth = gz->matrix_offset[axis][2] * (is_pos ? 1.0f : -1.0f);
  const float front = (depth + 1.0f) * 0.5f;

  float fill[4];
  copy_v4_v4(fill, axis_colors[axis]);
  fill[3] = MARKER_ALPHA_BACK + ((1.0f - MARKER_ALPHA_BACK) * front);

  /* Contrast follows the fill so a re-tinted axis stays readable. */
  const float luminance = (0.2126f * fill[0]) + (0.7152f * fill[1]) + (0.0722f * fill[2]);
  const bool text_is_dark = (luminance > 0.6f);
  const float text_color[4] = {
      text_is_dark ? 0.07f : 1.0f,
      text_is_dark ? 0.07f : 1.0f,
      text_is_dark ? 0.08f : 1.0f,
      1.0f,
  };

  GPU_matrix_push();
  GPU_matrix_translate_3fv(v_rot);
  GPU_matrix_scale_1f(1.0f / WIDGET_RADIUS);

  rctf rect{};
  rect.xmin = -half_w;
  rect.xmax = half_w;
  rect.ymin = -half_h;
  rect.ymax = half_h;
  /* Full capsule: the corner radius is the half height. */
  ui::mixar_fill_round(rect, half_h, fill);
  ui::mixar_label_left(label, -text_width * 0.5f, 0.0f, text_size, text_color);

  GPU_matrix_pop();
}

/** \} */

static void gizmo_axis_draw(const bContext * /*C*/, wmGizmo *gz)
{
  /* When the cursor is over any of the gizmos (show circle backdrop). */
  const bool is_active = ((gz->state & WM_GIZMO_STATE_HIGHLIGHT) != 0);

  float matrix_screen[4][4];
  float matrix_unit[4][4];
  unit_m4(matrix_unit);

  wmGizmoMatrixParams params{};
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

  ui::draw_roundbox_corner_set(ui::CNR_ALL);
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
    ui::draw_roundbox_4fv(&rect, true, rad, gz->color_hi);
    GPU_matrix_pop();
  }

  /* Silhouette: a screen-aligned ring on the sphere's outline, so it never
   * changes shape as the view orbits. */
  {
    const float silhouette_color[4] = GLOBE_SILHOUETTE_COLOR;
    gizmo_globe_ring_draw(2, silhouette_color, nullptr, viewport_size);
  }

  /* The three great circles, rotated with the view. No per-ring colour: each
   * vertex is tinted by the axis it points at, so the globe agrees with the
   * axis handles and with the viewport's own grid lines (see the section
   * comment above). */
  GPU_matrix_push();
  GPU_matrix_mul(gz->matrix_offset);
  for (int axis = 0; axis < 3; axis++) {
    gizmo_globe_ring_draw(axis, nullptr, depth_axis, viewport_size);
  }
  GPU_matrix_pop();

  /* Hovered axis readout (see the MIXAR section above).
   *
   * Part numbering is `gizmo_axis_test_select`'s: it walks axis-major,
   * negative end first, from 1 — so part 1/2 are -X/+X, 3/4 -Y/+Y, 5/6 -Z/+Z.
   * Gated on the highlight STATE, not on `highlight_part` alone, which keeps
   * its last value after the cursor leaves the gizmo. */
  if (is_active && gz->highlight_part >= 1 && gz->highlight_part <= 6) {
    const int part = gz->highlight_part - 1;
    gizmo_axis_marker_draw(gz, part / 2, (part % 2) != 0);
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

static bool gizmo_axis_screen_bounds_get(const bContext *C, wmGizmo *gz, rcti *r_bounding_box)
{
  ScrArea *area = CTX_wm_area(C);
  const float rad = WIDGET_RADIUS;
  r_bounding_box->xmin = gz->matrix_basis[3][0] + area->totrct.xmin - rad;
  r_bounding_box->ymin = gz->matrix_basis[3][1] + area->totrct.ymin - rad;
  r_bounding_box->xmax = gz->matrix_basis[3][0] + area->totrct.xmin + rad;
  r_bounding_box->ymax = gz->matrix_basis[3][1] + area->totrct.ymin + rad;
  return true;
}

static void gizmo_axis_setup(wmGizmo *gz)
{
  WM_gizmo_set_flag(gz, WM_GIZMO_NO_GROUPING, true);
}

void VIEW3D_GT_navigate_rotate(wmGizmoType *gzt)
{
  /* identifiers */
  gzt->idname = "VIEW3D_GT_navigate_rotate";

  /* API callbacks. */
  gzt->setup = gizmo_axis_setup;
  gzt->draw = gizmo_axis_draw;
  gzt->test_select = gizmo_axis_test_select;
  gzt->cursor_get = gizmo_axis_cursor_get;
  gzt->screen_bounds_get = gizmo_axis_screen_bounds_get;

  gzt->struct_size = sizeof(wmGizmo);
}

}  // namespace blender
