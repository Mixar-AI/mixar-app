/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: the aerial map card in the right column — the painter.
 *
 * Paints the card, blits the cached top-down render
 * (`view3d_director_minimap.cc`) into it, hides the render's square corners
 * under the card colour, and draws what changes every redraw OUTSIDE the
 * render pass: the shot camera as a white dot with a green view wedge, the
 * track target as a small dot, and the caption chips. It publishes the
 * pixel<->world transform for `MIXAR_OT_director_place_camera` and records
 * the same rect as the `director_minimap` QA target. No invisible button is
 * laid over the map: a uiBut would take the press before the keymap item
 * sees it.
 */

#include <algorithm>
#include <cmath>

#include "BLI_math_matrix_types.hh"
#include "BLI_math_rotation.h"
#include "BLI_math_vector.hh"
#include "BLI_rect.h"
#include "BLI_utildefines.h"

#include "BKE_camera.h"
#include "BKE_context.hh"

#include "DNA_ID.h"
#include "DNA_camera_types.h"
#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"

#include "GPU_immediate.hh"
#include "GPU_state.hh"
#include "GPU_viewport.hh"

#include "RNA_access.hh"

#include "UI_interface_c.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"
#include "view3d_director_minimap.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* Design px. */
constexpr float MINIMAP_INSET = 2.0f;    /* Card edge -> map edge. */
constexpr float MINIMAP_MARKER_D = 5.0f; /* Camera dot diameter. */
constexpr float MINIMAP_TARGET_D = 3.0f; /* Track-target dot diameter. */
constexpr float MINIMAP_WEDGE_LEN = 14.0f;
constexpr float MINIMAP_CHIP_H = 16.0f;
constexpr float MINIMAP_CHIP_PAD = 6.0f;
constexpr float MINIMAP_CHIP_MARGIN = 8.0f;

/** Cover the map's square corners with the card colour so it reads rounded. */
void corner_masks(const rctf &rect, const float radius, const float top[4], const float bottom[4])
{
  constexpr int segments = 8;
  uint pos = GPU_vertformat_attr_add(
      immVertexFormat(), "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  const struct {
    float cx, cy; /* The square corner. */
    float ax, ay; /* The arc centre. */
    float a0;     /* Arc start angle; it sweeps a quarter turn. */
    const float *col;
  } corners[4] = {
      {rect.xmin, rect.ymin, rect.xmin + radius, rect.ymin + radius, float(M_PI), bottom},
      {rect.xmax, rect.ymin, rect.xmax - radius, rect.ymin + radius, float(M_PI * 1.5), bottom},
      {rect.xmax, rect.ymax, rect.xmax - radius, rect.ymax - radius, 0.0f, top},
      {rect.xmin, rect.ymax, rect.xmin + radius, rect.ymax - radius, float(M_PI * 0.5), top},
  };
  for (const auto &corner : corners) {
    const float col[4] = {corner.col[0], corner.col[1], corner.col[2], 1.0f};
    immUniformColor4fv(col);
    immBegin(GPU_PRIM_TRI_FAN, segments + 2);
    immVertex2f(pos, corner.cx, corner.cy);
    for (int i = 0; i <= segments; i++) {
      const float angle = corner.a0 + float(M_PI * 0.5) * float(i) / float(segments);
      immVertex2f(pos, corner.ax + radius * cosf(angle), corner.ay + radius * sinf(angle));
    }
    immEnd();
  }
  immUnbindProgram();
}

/** Half of the camera's HORIZONTAL field of view, from lens, sensor and output aspect. */
float camera_half_angle(const Object *camera, const Scene *scene)
{
  const Camera *cam = id_cast<const Camera *>(camera->data);
  const float narrow = DEG2RADF(4.0f);
  if (cam == nullptr || cam->type == CAM_ORTHO) {
    return narrow; /* Parallel view: a sliver shows the heading only. */
  }
  const float xsize = scene ? float(scene->r.xsch) * scene->r.xasp : 1.0f;
  const float ysize = scene ? float(scene->r.ysch) * scene->r.yasp : 1.0f;
  const float sensor = BKE_camera_sensor_size(cam->sensor_fit, cam->sensor_x, cam->sensor_y);
  const float fov = focallength_to_fov(std::max(cam->lens, 1.0f), sensor);
  float fov_h = fov;
  if (BKE_camera_sensor_fit(cam->sensor_fit, xsize, ysize) == CAMERA_SENSOR_FIT_VERT) {
    fov_h = 2.0f * atanf(tanf(fov * 0.5f) * (xsize / std::max(ysize, 1e-6f)));
  }
  return std::clamp(fov_h * 0.5f, narrow, DEG2RADF(80.0f));
}

void draw_wedge(
    const float2 &apex, const float2 &dir, const float len, const float half, const float col[4])
{
  constexpr int segments = 6;
  const float heading = atan2f(dir.y, dir.x);
  uint pos = GPU_vertformat_attr_add(
      immVertexFormat(), "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4fv(col);
  immBegin(GPU_PRIM_TRI_FAN, segments + 2);
  immVertex2f(pos, apex.x, apex.y);
  for (int i = 0; i <= segments; i++) {
    const float angle = heading - half + 2.0f * half * float(i) / float(segments);
    immVertex2f(pos, apex.x + len * cosf(angle), apex.y + len * sinf(angle));
  }
  immEnd();
  immUnbindProgram();
}

void draw_dot(const float2 &center, const float diameter, const float col[4])
{
  rctf dot;
  BLI_rctf_init(&dot,
                center.x - diameter * 0.5f,
                center.x + diameter * 0.5f,
                center.y - diameter * 0.5f,
                center.y + diameter * 0.5f);
  cinema_fill(dot, diameter * 0.5f, col);
}

/** Small caption on a dark pill so it reads over the render. */
void caption_chip(const char *text, const float x, const float top, const float u)
{
  const float size = CINEMA_FONT_LABEL * u;
  const float pad = MINIMAP_CHIP_PAD * u;
  rctf chip;
  chip.xmin = x;
  chip.xmax = x + cinema_text_width(text, size) + pad * 2.0f;
  chip.ymax = top;
  chip.ymin = top - MINIMAP_CHIP_H * u;
  const float fill[4] = {0.0f, 0.0f, 0.0f, 0.55f};
  const float label[4] = CINEMA_COL_LABEL;
  cinema_fill(chip, BLI_rctf_size_y(&chip) * 0.5f, fill);
  cinema_text_left(text, chip.xmin + pad, BLI_rctf_cent_y(&chip), size, label);
}

/** The painter's side of the transform: world -> region px on the map. */
float2 world_to_px(const rctf &world, const rctf &px, const float x, const float y)
{
  const float fx = (x - world.xmin) / std::max(BLI_rctf_size_x(&world), 1e-6f);
  const float fy = (y - world.ymin) / std::max(BLI_rctf_size_y(&world), 1e-6f);
  return float2(px.xmin + fx * BLI_rctf_size_x(&px), px.ymin + fy * BLI_rctf_size_y(&px));
}

/** The shot's tracked object, if the take aims at one. */
const Object *shot_track_target(Scene *scene)
{
  PointerRNA shot_ptr;
  if (!view3d_director_active_shot_pointer(scene, &shot_ptr)) {
    return nullptr;
  }
  PropertyRNA *prop = RNA_struct_find_property(&shot_ptr, "track_target");
  if (prop == nullptr) {
    return nullptr;
  }
  return static_cast<const Object *>(RNA_property_pointer_get(&shot_ptr, prop).data);
}

}  // namespace

void cinema_draw_minimap(ui::Block *block,
                         const bContext *C,
                         const ARegion *region,
                         const DirectorViewState &state,
                         const rctf &card)
{
  const float u = cinema_unit();
  /* Corner fans cover the rectangular blit. RGB matches CARD tint; A=1 so
   * they fully hide the square corners the glass pane already rounded. */
  const float card_top[4] = {0.090f, 0.120f, 0.100f, 1.0f};
  const float card_bottom[4] = {0.040f, 0.055f, 0.048f, 1.0f};
  Scene *scene = CTX_data_scene(const_cast<bContext *>(C));

  view3d_director_minimap_garbage_flush();
  cinema_glass_panel(card, CINEMA_PANEL_RADIUS * u);

  /* The map fills the card under its rounded corners. */
  rctf inner = card;
  BLI_rctf_pad(&inner, -MINIMAP_INSET * u, -MINIMAP_INSET * u);
  rcti map;
  map.xmin = int(inner.xmin);
  map.ymin = int(inner.ymin);
  map.xmax = map.xmin + int(BLI_rctf_size_x(&inner)) - 1;
  map.ymax = map.ymin + int(BLI_rctf_size_y(&inner)) - 1;
  rctf map_px;
  BLI_rctf_init(
      &map_px, float(map.xmin), float(map.xmax + 1), float(map.ymin), float(map.ymax + 1));

  bool locked = false;
  const Object *camera = state.has_shot ? view3d_director_shot_camera(scene, &locked) : nullptr;
  float camera_xy[2] = {0.0f, 0.0f};
  float2 camera_dir(0.0f);
  if (camera) {
    const float4x4 &mat = camera->object_to_world();
    camera_xy[0] = mat.location().x;
    camera_xy[1] = mat.location().y;
    camera_dir = -float2(mat.z_axis().x, mat.z_axis().y);
  }

  /* Render pass (guarded, throttled, state restored inside). The marker's
   * full extent — dot radius plus wedge length — is kept inside the map. */
  const float margin_px = (MINIMAP_MARKER_D * 0.5f + MINIMAP_WEDGE_LEN) * u;
  rctf world = {};
  int inset_px = 0;
  const bool blit = view3d_director_minimap_update(
      C, region, map, camera ? camera_xy : nullptr, margin_px, &world, &inset_px);
  if (blit) {
    GPU_viewport_draw_to_screen_ex(view3d_director_minimap_viewport(),
                                   0,
                                   &map,
                                   /*display_colorspace*/ true,
                                   /*do_overlay_merge*/ true);
    GPU_blend(GPU_BLEND_ALPHA);
    corner_masks(map_px, (CINEMA_PANEL_RADIUS - MINIMAP_INSET) * u, card_top, card_bottom);
  }

  /* The transform the placement modal reads, and the SAME rect as the QA
   * target. The transform is dropped when no map was drawn. */
  view3d_director_minimap_publish(region, map, world, inset_px, blit);
  cinema_qa_record(region, inner, "director_minimap", "place", -1);

  /* Markers: every redraw, on top of the render, never part of it. */
  if (blit && camera) {
    const float2 at = world_to_px(world, map_px, camera_xy[0], camera_xy[1]);
    const float alpha = locked ? 0.45f : 1.0f;
    if (math::length_squared(camera_dir) > 1e-8f) {
      const float wedge[4] = {0.165f, 0.475f, 0.286f, 0.8f * alpha}; /* CINEMA_COL_SPEED_ON */
      draw_wedge(at,
                 math::normalize(camera_dir),
                 MINIMAP_WEDGE_LEN * u,
                 camera_half_angle(camera, scene),
                 wedge);
    }
    const float dot[4] = {1.0f, 1.0f, 1.0f, alpha};
    draw_dot(at, MINIMAP_MARKER_D * u, dot);
    if (const Object *target = shot_track_target(scene)) {
      const float3 &loc = target->object_to_world().location();
      const float2 target_px = world_to_px(world, map_px, loc.x, loc.y);
      if (BLI_rctf_isect_pt_v(&map_px, target_px)) {
        const float target_col[4] = {1.0f, 1.0f, 1.0f, 0.7f * alpha};
        draw_dot(target_px, MINIMAP_TARGET_D * u, target_col);
      }
    }
  }

  const float margin = MINIMAP_CHIP_MARGIN * u;
  caption_chip("Aerial view", inner.xmin + margin, inner.ymax - margin, u);
  if (!camera) {
    const char *hint = "Add a camera to place it";
    const float width = cinema_text_width(hint, CINEMA_FONT_LABEL * u) +
                        MINIMAP_CHIP_PAD * u * 2.0f;
    caption_chip(hint,
                 BLI_rctf_cent_x(&inner) - width * 0.5f,
                 inner.ymin + margin + MINIMAP_CHIP_H * u,
                 u);
  }
  UNUSED_VARS(block);
}

}  // namespace blender
