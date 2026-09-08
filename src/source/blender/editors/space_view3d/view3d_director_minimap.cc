/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Cinema Mode: the aerial map's render, cache and pixel<->world transform.
 * The world extents it maps come from `view3d_director_minimap_extents.cc`;
 * the painter that draws the card around it is `view3d_director_minimap_draw.cc`.
 *
 * A live top-down orthographic render of the scene (world XY; +X right,
 * +Y up on the card). It is the agent strip's offscreen tile discipline
 * (`view3d_agent_strip_draw.cc`) applied to ONE cached buffer: `GPUOffScreen`
 * + `GPUViewport`, a hand-built view/projection, framebuffer/viewport/
 * scissor saved around the pass and restored after it, the
 * `ED_view3d_draw_offscreen_check_nested()` and `DEG_get_update_count() == 0`
 * guards, and a throttle.
 *
 * What re-renders (the rule, in this order):
 *   1. never while a draw-manager pass is in progress (nested);
 *   2. always when the card's pixel size (or the region drawing it)
 *      changed — the blit needs an exact match;
 *   3. otherwise never more often than #MINIMAP_MIN_RENDER_INTERVAL;
 *   4. when the map's WORLD extents changed (scene grew, or the camera left
 *      the mapped area and pulled the extents with it);
 *   5. when the depsgraph's update count changed — unless the shot camera
 *      moved since the last draw AND the last render is younger than
 *      #MINIMAP_CAMERA_MOVE_RENDER_INTERVAL. A camera-only drag bumps the
 *      update count on every mouse move, and the camera is not part of the
 *      render (excluded by object type; its marker is painted every redraw
 *      on top), so re-rendering for it would only burn a scene pass per
 *      mouse move; the 0.5 s ceiling still keeps an animated scene honest
 *      during playback.
 * A render wanted but throttled tags a redraw, so the map converges within
 * one interval, like a strip tile.
 */

#include <algorithm>
#include <cmath>
#include <utility>

#include "BLI_math_geom.h"
#include "BLI_math_matrix.h"
#include "BLI_math_matrix_types.hh"
#include "BLI_math_vector_types.hh"
#include "BLI_rect.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"
#include "BLI_vector.hh"

#include "BKE_context.hh"
#include "BKE_screen.hh"

#include "DEG_depsgraph.hh"

#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_view3d_enums.h"
#include "DNA_view3d_types.h"

#include "DRW_engine.hh"

#include "ED_screen.hh"
#include "ED_view3d_offscreen.hh"

#include "GPU_framebuffer.hh"
#include "GPU_state.hh"
#include "GPU_viewport.hh"

#include "UI_interface_c.hh"

#include "view3d_director.hh"
#include "view3d_director_cinema.hh"
#include "view3d_director_minimap.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/* -------------------------------------------------------------------- */
/** \name Tokens
 * \{ */

/** Floor between two renders, in seconds (~10 Hz), as the strip's tiles. */
constexpr double MINIMAP_MIN_RENDER_INTERVAL = 0.1;
/** Ceiling on how stale the map may get while only the camera moves. */
constexpr double MINIMAP_CAMERA_MOVE_RENDER_INTERVAL = 0.5;
/** Eye height above the scene's top, and depth kept below its bottom. */
constexpr float MINIMAP_Z_CLEARANCE = 10.0f;
/** Cards smaller than this on either axis are not rendered. */
constexpr int MINIMAP_MIN_SIZE = 8;

/** \} */

/* -------------------------------------------------------------------- */
/** \name Runtime
 * \{ */

struct DirectorMinimap {
  GPUOffScreen *offscreen = nullptr;
  GPUViewport *viewport = nullptr;
  /** Region that rendered the buffers; only it releases them. */
  const ARegion *region = nullptr;
  bool has_render = false;
  double last_render_time = 0.0;
  uint64_t last_update_count = 0;
  /** World rect of the last render, to tell a scene change from a camera move. */
  rctf rendered_world = {};
  /** Placement clamp (px) that goes with `rendered_world`. */
  int rendered_inset_px = 0;
  /** Shot camera XY at the last draw, to tell a camera move from a scene edit. */
  float2 last_camera_xy = float2(0.0f);
  bool have_camera_xy = false;
  /** Buffers released off the draw path; freed under a bound GPU context. */
  Vector<std::pair<GPUOffScreen *, GPUViewport *>> gpu_garbage;
};

DirectorMinimap g_minimap;

struct DirectorMinimapTransform {
  /** Inclusive region-px rect the map is blitted into (rcti convention). */
  rcti rect_region_px = {};
  float world_xmin = 0.0f, world_xmax = 0.0f, world_ymin = 0.0f, world_ymax = 0.0f;
  /** Placements stay this many px inside the rect so the marker never sits on the edge. */
  int inset_px = 0;
  const ARegion *region = nullptr;
  bool valid = false;
};

DirectorMinimapTransform g_transform;

void minimap_gpu_queue_release()
{
  if (g_minimap.offscreen || g_minimap.viewport) {
    g_minimap.gpu_garbage.append({g_minimap.offscreen, g_minimap.viewport});
  }
  g_minimap.offscreen = nullptr;
  g_minimap.viewport = nullptr;
  g_minimap.region = nullptr;
  g_minimap.has_render = false;
  g_minimap.have_camera_xy = false;
}

bool minimap_gpu_ensure(const int w, const int h)
{
  if (g_minimap.offscreen && GPU_offscreen_width(g_minimap.offscreen) == w &&
      GPU_offscreen_height(g_minimap.offscreen) == h)
  {
    return true;
  }
  /* Drawing: a GPU context is bound, free directly. */
  minimap_gpu_queue_release();
  view3d_director_minimap_garbage_flush();

  char err_out[256] = "unknown";
  g_minimap.offscreen = GPU_offscreen_create(w,
                                             h,
                                             true,
                                             blender::gpu::TextureFormat::UNORM_8_8_8_8,
                                             GPU_TEXTURE_USAGE_SHADER_READ,
                                             false,
                                             err_out);
  if (!g_minimap.offscreen) {
    return false;
  }
  g_minimap.viewport = GPU_viewport_create();
  if (!g_minimap.viewport) {
    GPU_offscreen_free(g_minimap.offscreen);
    g_minimap.offscreen = nullptr;
    return false;
  }
  return true;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Render
 * \{ */

void minimap_render(const bContext *C,
                    Depsgraph *depsgraph,
                    const WorldExtents &extents,
                    const rctf &world,
                    const int w,
                    const int h)
{
  /* Eye above the scene looking down world -Z; identity rotation already has
   * +X right and +Y up on the image, which is the card's convention. */
  const float top_z = (extents.any ? extents.zmax : 0.0f) + MINIMAP_Z_CLEARANCE;
  const float bottom_z = (extents.any ? extents.zmin : 0.0f) - MINIMAP_Z_CLEARANCE;
  const float clip_start = 0.01f;
  const float clip_end = top_z - bottom_z;

  float viewmat[4][4], winmat[4][4];
  unit_m4(viewmat);
  translate_m4(viewmat, -BLI_rctf_cent_x(&world), -BLI_rctf_cent_y(&world), -top_z);
  const float hw = BLI_rctf_size_x(&world) * 0.5f;
  const float hh = BLI_rctf_size_y(&world) * 0.5f;
  orthographic_m4(winmat, -hw, hw, -hh, hh, clip_start, clip_end);

  /* Always solid: cheap and legible as a map, whatever the host shows. */
  View3DShading shading;
  BKE_screen_view3d_shading_init(&shading);
  shading.type = OB_SOLID;

  GPU_offscreen_bind(g_minimap.offscreen, true);
  ED_view3d_draw_offscreen_simple(depsgraph,
                                  CTX_data_scene(const_cast<bContext *>(C)),
                                  &shading,
                                  /*context*/ nullptr,
                                  OB_SOLID,
                                  /*object_type_exclude_viewport_override*/ MINIMAP_HIDDEN_TYPES,
                                  /*object_type_exclude_select_override*/ 0,
                                  w,
                                  h,
                                  V3D_OFSDRAW_SHOW_GRIDFLOOR,
                                  viewmat,
                                  winmat,
                                  clip_start,
                                  clip_end,
                                  /*vignette_aperture*/ 0.0f,
                                  /*is_xr_surface*/ false,
                                  /*is_image_render*/ true,
                                  /*draw_background*/ true,
                                  /*viewname*/ nullptr,
                                  /*do_color_management*/ false,
                                  /*camera_override*/ nullptr,
                                  g_minimap.offscreen,
                                  g_minimap.viewport);
  GPU_offscreen_unbind(g_minimap.offscreen, true);
}

/** \} */

}  // namespace

/* -------------------------------------------------------------------- */
/** \name Internal API (view3d_director_minimap.hh)
 * \{ */

void view3d_director_minimap_garbage_flush()
{
  for (auto &[offscreen, viewport] : g_minimap.gpu_garbage) {
    if (viewport) {
      GPU_viewport_free(viewport);
    }
    if (offscreen) {
      GPU_offscreen_free(offscreen);
    }
  }
  g_minimap.gpu_garbage.clear();
}

GPUViewport *view3d_director_minimap_viewport()
{
  return g_minimap.has_render ? g_minimap.viewport : nullptr;
}

bool view3d_director_minimap_update(const bContext *C,
                                    const ARegion *region,
                                    const rcti &map,
                                    const float *camera_xy,
                                    const float margin_px,
                                    rctf *r_world,
                                    int *r_inset_px)
{
  *r_world = g_minimap.rendered_world;
  *r_inset_px = g_minimap.rendered_inset_px;
  const int w = BLI_rcti_size_x(&map) + 1;
  const int h = BLI_rcti_size_y(&map) + 1;
  if (w < MINIMAP_MIN_SIZE || h < MINIMAP_MIN_SIZE) {
    return false;
  }
  Depsgraph *depsgraph = CTX_data_expect_evaluated_depsgraph(const_cast<bContext *>(C));
  if (!depsgraph || DEG_get_update_count(depsgraph) == 0) {
    /* Never evaluated: no evaluated scene to draw or measure yet. */
    return false;
  }

  const WorldExtents extents = view3d_director_minimap_scene_extents(depsgraph);
  int inset_px = 0;
  const rctf world = view3d_director_minimap_fit_world(
      extents, camera_xy, margin_px, w, h, &inset_px);
  const uint64_t update_count = DEG_get_update_count(depsgraph);
  const double now = BLI_time_now_seconds();

  const bool camera_moved = camera_xy && g_minimap.have_camera_xy &&
                            (g_minimap.last_camera_xy.x != camera_xy[0] ||
                             g_minimap.last_camera_xy.y != camera_xy[1]);
  g_minimap.have_camera_xy = camera_xy != nullptr;
  if (camera_xy) {
    g_minimap.last_camera_xy = float2(camera_xy[0], camera_xy[1]);
  }

  const bool size_mismatch = !g_minimap.offscreen || !g_minimap.has_render ||
                             GPU_offscreen_width(g_minimap.offscreen) != w ||
                             GPU_offscreen_height(g_minimap.offscreen) != h ||
                             g_minimap.region != region;
  const double age = now - g_minimap.last_render_time;
  bool wanted = size_mismatch;
  if (!wanted && view3d_director_minimap_world_changed(world, g_minimap.rendered_world)) {
    wanted = true;
  }
  if (!wanted && update_count != g_minimap.last_update_count) {
    /* A camera-only move is not in the render; see the file comment. */
    wanted = !(camera_moved && age < MINIMAP_CAMERA_MOVE_RENDER_INTERVAL);
  }
  if (!wanted) {
    return g_minimap.has_render;
  }
  if (ED_view3d_draw_offscreen_check_nested() ||
      (!size_mismatch && age < MINIMAP_MIN_RENDER_INTERVAL))
  {
    /* Due but not now: converge on a later draw, as a strip tile does. */
    ED_region_tag_redraw(const_cast<ARegion *>(region));
    return g_minimap.has_render && !size_mismatch;
  }
  if (!minimap_gpu_ensure(w, h)) {
    return false;
  }

  /* The draw-manager pass re-binds framebuffers internally, and binding
   * resets the per-framebuffer viewport/scissor — the rest of the surface
   * (and the region under it) would draw black. Capture, render, restore. */
  blender::gpu::FrameBuffer *fb_prev = GPU_framebuffer_active_get();
  int viewport_prev[4], scissor_prev[4];
  GPU_viewport_size_get_i(viewport_prev);
  GPU_scissor_get(scissor_prev);

  minimap_render(C, depsgraph, extents, world, w, h);

  if (fb_prev) {
    GPU_framebuffer_bind(fb_prev);
  }
  GPU_viewport(viewport_prev[0], viewport_prev[1], viewport_prev[2], viewport_prev[3]);
  GPU_scissor(scissor_prev[0], scissor_prev[1], scissor_prev[2], scissor_prev[3]);
  ED_region_pixelspace(const_cast<ARegion *>(region));
  GPU_blend(GPU_BLEND_ALPHA);

  g_minimap.region = region;
  g_minimap.has_render = true;
  g_minimap.last_render_time = now;
  g_minimap.last_update_count = update_count;
  g_minimap.rendered_world = world;
  g_minimap.rendered_inset_px = inset_px;
  *r_world = world;
  *r_inset_px = inset_px;
  return true;
}

void view3d_director_minimap_publish(const ARegion *region,
                                     const rcti &map,
                                     const rctf &world,
                                     const int inset_px,
                                     const bool valid)
{
  g_transform.rect_region_px = map;
  g_transform.world_xmin = world.xmin;
  g_transform.world_xmax = world.xmax;
  g_transform.world_ymin = world.ymin;
  g_transform.world_ymax = world.ymax;
  g_transform.inset_px = inset_px;
  g_transform.region = region;
  g_transform.valid = valid;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Public API (view3d_director_cinema.hh / view3d_director.hh)
 * \{ */

bool view3d_director_minimap_contains(const ARegion *region, const int x, const int y)
{
  return g_transform.valid && g_transform.region == region &&
         BLI_rcti_isect_pt(&g_transform.rect_region_px, x, y);
}

bool view3d_director_minimap_world_from_region_px(const ARegion *region,
                                                  const int x,
                                                  const int y,
                                                  float r_xy[2])
{
  const DirectorMinimapTransform &t = g_transform;
  if (!t.valid || t.region != region) {
    return false;
  }
  /* Pixel -> unit square -> world, clamped inside the placeable area:
   * world = world_min + ((px - rect_min + 0.5) / rect_size) * world_size. */
  const float w = float(BLI_rcti_size_x(&t.rect_region_px) + 1);
  const float h = float(BLI_rcti_size_y(&t.rect_region_px) + 1);
  const float inset = float(t.inset_px);
  const float px = std::clamp(float(x - t.rect_region_px.xmin) + 0.5f, inset, w - inset);
  const float py = std::clamp(float(y - t.rect_region_px.ymin) + 0.5f, inset, h - inset);
  r_xy[0] = t.world_xmin + (px / w) * (t.world_xmax - t.world_xmin);
  r_xy[1] = t.world_ymin + (py / h) * (t.world_ymax - t.world_ymin);
  return true;
}

void view3d_director_minimap_free()
{
  minimap_gpu_queue_release();
  g_transform = DirectorMinimapTransform{};
}

void view3d_director_minimap_release(const ARegion *region, const bool free_gpu)
{
  if (g_transform.region == region) {
    g_transform = DirectorMinimapTransform{};
  }
  if (free_gpu && g_minimap.region == region) {
    /* Drawing: a GPU context is bound. */
    minimap_gpu_queue_release();
    view3d_director_minimap_garbage_flush();
  }
}

void view3d_director_minimap_region_free(ARegion *region)
{
  if (g_minimap.region == region) {
    view3d_director_minimap_free();
  }
  if (!g_minimap.gpu_garbage.is_empty()) {
    /* Outside drawing, no GPU context is guaranteed: borrow the draw
     * manager's, as the agent strip's region free does. */
    DRW_gpu_context_enable();
    view3d_director_minimap_garbage_flush();
    DRW_gpu_context_disable();
  }
}

/** \} */

}  // namespace blender
