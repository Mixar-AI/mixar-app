/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: the world extents the aerial map shows.
 *
 * Every draw measures the evaluated scene's world XY bounds (visible,
 * geometry-carrying objects only), pads them, grows them to include the shot
 * camera and fits them to the card's pixel aspect. The render half
 * (`view3d_director_minimap.cc`) compares the result against the last
 * render's rect to decide whether the scene moved.
 */

#include <algorithm>
#include <cfloat>
#include <cmath>
#include <optional>

#include "BLI_bounds_types.hh"
#include "BLI_math_matrix.hh"
#include "BLI_math_matrix_types.hh"
#include "BLI_math_vector_types.hh"
#include "BLI_rect.h"

#include "BKE_object.hh"

#include "DEG_depsgraph_query.hh"

#include "DNA_object_types.h"

#include "view3d_director_minimap.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/** Scene bounds are padded by this fraction of their size, at least #MINIMAP_PAD_MIN metres. */
constexpr float MINIMAP_PAD_FRACTION = 0.1f;
constexpr float MINIMAP_PAD_MIN = 2.0f;
/** Half-size of the square shown for an empty scene (20 x 20 m). */
constexpr float MINIMAP_EMPTY_HALF = 10.0f;
/** Extents that moved less than this fraction of their size count as unchanged. */
constexpr float MINIMAP_EXTENT_TOLERANCE = 1e-3f;

}  // namespace

WorldExtents view3d_director_minimap_scene_extents(Depsgraph *depsgraph)
{
  WorldExtents extents;
  BLI_rctf_init_minmax(&extents.xy);
  extents.zmin = FLT_MAX;
  extents.zmax = -FLT_MAX;

  /* No DUPLI: instancing every collection/particle instance per redraw is
   * the one part of this walk that could get heavy; instances are covered
   * by their instancer's own box. */
  DEGObjectIterSettings settings{};
  settings.depsgraph = depsgraph;
  settings.flags = DEG_ITER_OBJECT_FLAG_LINKED_DIRECTLY | DEG_ITER_OBJECT_FLAG_LINKED_VIA_SET |
                   DEG_ITER_OBJECT_FLAG_VISIBLE;
  DEG_OBJECT_ITER_BEGIN (&settings, ob) {
    if (MINIMAP_HIDDEN_TYPES & (1 << ob->type)) {
      continue;
    }
    const std::optional<Bounds<float3>> bounds = BKE_object_boundbox_get(ob);
    if (!bounds) {
      continue;
    }
    const float4x4 &mat = ob->object_to_world();
    for (int corner = 0; corner < 8; corner++) {
      const float3 local((corner & 1) ? bounds->max.x : bounds->min.x,
                         (corner & 2) ? bounds->max.y : bounds->min.y,
                         (corner & 4) ? bounds->max.z : bounds->min.z);
      const float3 world = math::transform_point(mat, local);
      extents.xy.xmin = std::min(extents.xy.xmin, world.x);
      extents.xy.xmax = std::max(extents.xy.xmax, world.x);
      extents.xy.ymin = std::min(extents.xy.ymin, world.y);
      extents.xy.ymax = std::max(extents.xy.ymax, world.y);
      extents.zmin = std::min(extents.zmin, world.z);
      extents.zmax = std::max(extents.zmax, world.z);
    }
    extents.any = true;
  }
  DEG_OBJECT_ITER_END;
  return extents;
}

/**
 * The world rect the map shows: scene bounds padded by 10 % (at least 2 m),
 * grown to include the shot camera so its marker is never off the map, then
 * fitted to the card's pixel aspect by growing the shorter world axis.
 * Growth is symmetric so the scene stays centred.
 */
rctf view3d_director_minimap_fit_world(const WorldExtents &extents,
                                       const float *camera_xy,
                                       const float margin_px,
                                       const int w,
                                       const int h,
                                       int *r_inset_px)
{
  rctf world;
  if (extents.any) {
    world = extents.xy;
    const float pad_x = std::max(BLI_rctf_size_x(&world) * MINIMAP_PAD_FRACTION, MINIMAP_PAD_MIN);
    const float pad_y = std::max(BLI_rctf_size_y(&world) * MINIMAP_PAD_FRACTION, MINIMAP_PAD_MIN);
    BLI_rctf_pad(&world, pad_x, pad_y);
  }
  else {
    BLI_rctf_init(
        &world, -MINIMAP_EMPTY_HALF, MINIMAP_EMPTY_HALF, -MINIMAP_EMPTY_HALF, MINIMAP_EMPTY_HALF);
  }

  /* World units per pixel of the rect BEFORE the marker margin — after the
   * aspect fit the scale is the larger of the two axes' ratios. */
  const float min_px = float(std::max(std::min(w, h), 1));
  float margin_world = 0.0f;
  if (camera_xy) {
    rctf pre = world;
    BLI_rctf_do_minmax_v(&pre, camera_xy);
    const float scale_pre = std::max(BLI_rctf_size_x(&pre) / float(w),
                                     BLI_rctf_size_y(&pre) / float(h));
    /* The camera extending the limiting axis by `m` enlarges the final
     * scale to (S + m) / W; solving m / scale_final >= margin_px gives the
     * correction below, so the marker keeps its full extent on the card. */
    const float clamped_margin = std::min(margin_px, min_px * 0.25f);
    margin_world = clamped_margin * scale_pre / (1.0f - clamped_margin / min_px);
    /* Union with the camera and its marker, never padded after: a placement
     * is clamped `r_inset_px` (this margin in final pixels) inside the map,
     * so it can never move the camera past its current position on an axis
     * it is the outermost thing on — the rect grows once, on arrival. */
    const float lo[2] = {camera_xy[0] - margin_world, camera_xy[1] - margin_world};
    const float hi[2] = {camera_xy[0] + margin_world, camera_xy[1] + margin_world};
    BLI_rctf_do_minmax_v(&world, lo);
    BLI_rctf_do_minmax_v(&world, hi);
  }

  const float aspect = float(w) / float(h);
  const float size_x = BLI_rctf_size_x(&world);
  const float size_y = BLI_rctf_size_y(&world);
  if (size_x < size_y * aspect) {
    const float grow = (size_y * aspect - size_x) * 0.5f;
    world.xmin -= grow;
    world.xmax += grow;
  }
  else {
    const float grow = (size_x / aspect - size_y) * 0.5f;
    world.ymin -= grow;
    world.ymax += grow;
  }
  if (r_inset_px) {
    const float scale_final = std::max(BLI_rctf_size_x(&world) / float(w), 1e-6f);
    *r_inset_px = int(std::ceil(margin_world / scale_final));
  }
  return world;
}

bool view3d_director_minimap_world_changed(const rctf &a, const rctf &b)
{
  const float tol = MINIMAP_EXTENT_TOLERANCE *
                    std::max(BLI_rctf_size_x(&a), BLI_rctf_size_y(&a));
  return std::fabs(a.xmin - b.xmin) > tol || std::fabs(a.xmax - b.xmax) > tol ||
         std::fabs(a.ymin - b.ymin) > tol || std::fabs(a.ymax - b.ymax) > tol;
}

}  // namespace blender
