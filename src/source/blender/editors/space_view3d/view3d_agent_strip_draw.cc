/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Agent Scene Strip drawing: offscreen-render each dirty tile's scene, then
 * blit all tiles into the strip region and draw overlays on top. Also the
 * single-row tile layout and mouse hit-testing.
 *
 * Rendering happens in the draw callback the same way Python's
 * `GPUOffScreen.draw_view3d()` runs from draw handlers: guarded by
 * `ED_view3d_draw_offscreen_check_nested()`, with the caller's framebuffer
 * saved/restored by `GPU_offscreen_bind/unbind(..., true)`. Depsgraph
 * evaluation does NOT happen here — `view3d_agent_strip_refresh()` keeps
 * the non-active scenes evaluated on the main-loop refresh phase.
 */

#include <algorithm>
#include <cmath>
#include <cstring>

#include "BLF_api.hh"

#include "BLI_math_geom.h"
#include "BLI_math_matrix.h"
#include "BLI_math_rotation.h"
#include "BLI_rect.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"

#include "BKE_context.hh"
#include "BKE_main.hh"
#include "BKE_scene.hh"
#include "BKE_screen.hh"

#include "DEG_depsgraph.hh"

#include "DNA_object_types.h"
#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"
#include "DNA_view3d_enums.h"
#include "DNA_view3d_types.h"

#include "ED_screen.hh"
#include "ED_view3d_offscreen.hh"

#include "GPU_framebuffer.hh"
#include "GPU_immediate.hh"
#include "GPU_immediate_util.hh"
#include "GPU_state.hh"
#include "GPU_viewport.hh"

#include "UI_interface.hh"
#include "UI_resources.hh"

#include "WM_api.hh"

#include "view3d_agent_strip.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Region Init / Exit
 * \{ */

void view3d_agent_strip_region_init(wmWindowManager *wm, ARegion *region)
{
  wmKeyMap *keymap = WM_keymap_ensure(
      wm->runtime->defaultconf, "Agent Scene Strip", SPACE_VIEW3D, RGN_TYPE_EXECUTE);
  WM_event_add_keymap_handler(&region->runtime->handlers, keymap);
}

void view3d_agent_strip_region_exit(wmWindowManager *wm, ARegion *region)
{
  /* Stop the poll-tick timer while the strip is hidden (no agent scenes) or
   * closing; the runtime itself stays alive so cameras and renders survive
   * a temporary hide. */
  AgentStripRuntime *runtime = static_cast<AgentStripRuntime *>(region->regiondata);
  view3d_agent_strip_tick_timer_remove(wm, runtime);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Layout & Hit Testing
 * \{ */

void view3d_agent_strip_layout_tiles(const ARegion *region, AgentStripRuntime *runtime)
{
  const int n = int(runtime->tiles.size());
  if (n == 0) {
    return;
  }

  const int gap = AGENT_STRIP_TILE_GAP;
  const int tile_h = std::max(region->winy - 2 * gap, 0);

  /* One row: tiles at the preferred aspect, shrunk evenly when the row
   * would overflow the region width. */
  const int ideal_w = int(roundf(float(tile_h) * AGENT_STRIP_TILE_ASPECT));
  const int fit_w = (region->winx - gap * (n + 1)) / n;
  const int tile_w = std::max(std::min(ideal_w, fit_w), 0);

  for (int i = 0; i < n; i++) {
    rcti *rect = &runtime->tiles[i].rect;
    rect->xmin = gap + i * (tile_w + gap);
    rect->xmax = rect->xmin + tile_w - 1;
    rect->ymin = gap;
    rect->ymax = gap + tile_h - 1;
  }
}

AgentStripTile *view3d_agent_strip_tile_at(AgentStripRuntime *runtime, const int mval[2])
{
  for (AgentStripTile &tile : runtime->tiles) {
    if (BLI_rcti_isect_pt(&tile.rect, mval[0], mval[1])) {
      return &tile;
    }
  }
  return nullptr;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Tile Rendering
 * \{ */

static bool tile_gpu_ensure(AgentStripTile &tile, const int w, const int h)
{
  if (tile.offscreen && GPU_offscreen_width(tile.offscreen) == w &&
      GPU_offscreen_height(tile.offscreen) == h)
  {
    return true;
  }

  /* A GPU context is bound during drawing, free directly. */
  if (tile.viewport) {
    GPU_viewport_free(tile.viewport);
    tile.viewport = nullptr;
  }
  if (tile.offscreen) {
    GPU_offscreen_free(tile.offscreen);
    tile.offscreen = nullptr;
  }
  tile.has_render = false;

  char err_out[256] = "unknown";
  tile.offscreen = GPU_offscreen_create(w,
                                        h,
                                        true,
                                        blender::gpu::TextureFormat::UNORM_8_8_8_8,
                                        GPU_TEXTURE_USAGE_SHADER_READ,
                                        false,
                                        err_out);
  if (!tile.offscreen) {
    return false;
  }
  tile.viewport = GPU_viewport_create();
  if (!tile.viewport) {
    GPU_offscreen_free(tile.offscreen);
    tile.offscreen = nullptr;
    return false;
  }
  return true;
}

static void tile_camera_matrices(const AgentStripCamera &cam,
                                 const int w,
                                 const int h,
                                 float r_viewmat[4][4],
                                 float r_winmat[4][4])
{
  /* Same composition as view3d_viewmatrix_set() for a user (non-camera) view. */
  quat_to_mat4(r_viewmat, cam.viewquat);
  r_viewmat[3][2] -= cam.dist;
  translate_m4(r_viewmat, cam.ofs[0], cam.ofs[1], cam.ofs[2]);

  const float aspect = float(w) / float(h);
  const float half_h = AGENT_STRIP_CLIP_START * tanf(AGENT_STRIP_FOV_Y * 0.5f);
  const float half_w = half_h * aspect;
  perspective_m4(r_winmat,
                 -half_w,
                 half_w,
                 -half_h,
                 half_h,
                 AGENT_STRIP_CLIP_START,
                 AGENT_STRIP_CLIP_END);
}

/** Tiles follow the host viewport's shading, clamped to the modes the
 * offscreen tile render supports: solid, or material/rendered as material. */
static eDrawType tile_drawtype(const View3D *v3d)
{
  return (v3d && v3d->shading.type >= OB_MATERIAL) ? OB_MATERIAL : OB_SOLID;
}

static void tile_render(const View3D *v3d,
                        AgentStripTile &tile,
                        Depsgraph *depsgraph,
                        const int w,
                        const int h)
{
  float viewmat[4][4], winmat[4][4];
  tile_camera_matrices(tile.cam, w, h, viewmat, winmat);

  const eDrawType drawtype = tile_drawtype(v3d);

  View3DShading shading;
  BKE_screen_view3d_shading_init(&shading);
  shading.type = drawtype;

  GPU_offscreen_bind(tile.offscreen, true);
  ED_view3d_draw_offscreen_simple(depsgraph,
                                  tile.scene,
                                  &shading,
                                  drawtype,
                                  /*object_type_exclude_viewport_override*/ 0,
                                  /*object_type_exclude_select_override*/ 0,
                                  w,
                                  h,
                                  V3D_OFSDRAW_SHOW_GRIDFLOOR,
                                  viewmat,
                                  winmat,
                                  AGENT_STRIP_CLIP_START,
                                  AGENT_STRIP_CLIP_END,
                                  /*vignette_aperture*/ 0.0f,
                                  /*is_xr_surface*/ false,
                                  /*is_image_render*/ true,
                                  /*draw_background*/ true,
                                  /*viewname*/ nullptr,
                                  /*do_color_management*/ false,
                                  tile.offscreen,
                                  tile.viewport);
  GPU_offscreen_unbind(tile.offscreen, true);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Overlays
 * \{ */

static void draw_rect(uint pos, const float color[4], float x1, float y1, float x2, float y2)
{
  immUniformColor4fv(color);
  immRectf(pos, x1, y1, x2, y2);
}

/** Per-tile 2D overlays: scene name pill and agent busy badge. The active
 * scene is never in the strip, so there is no active highlight. */
static void agent_strip_draw_overlays(AgentStripRuntime *runtime)
{
  const float scale = UI_SCALE_FAC;
  const float pad_x = 9.0f * scale;
  const float pad_y = 6.0f * scale;
  const float dot_radius = 5.0f * scale;

  const int fontid = BLF_default();
  BLF_size(fontid, 14.0f * scale);

  const float pill_color[4] = {0.0f, 0.0f, 0.0f, 0.55f};
  const float busy_color[4] = {1.0f, 0.65f, 0.1f, 1.0f};
  const float idle_color[4] = {0.45f, 0.45f, 0.45f, 1.0f};

  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);

  GPU_blend(GPU_BLEND_ALPHA);

  for (AgentStripTile &tile : runtime->tiles) {
    const rcti *rect = &tile.rect;
    if (BLI_rcti_size_x(rect) < AGENT_STRIP_MIN_TILE_SIZE ||
        BLI_rcti_size_y(rect) < AGENT_STRIP_MIN_TILE_SIZE)
    {
      continue;
    }

    const char *name = tile.scene_name.c_str();
    const float text_w = BLF_width(fontid, name, strlen(name));
    const float text_h = BLF_height_max(fontid);
    const bool busy = view3d_agent_strip_scene_busy(tile.scene);

    /* Pill rect at the tile's top-left: [dot] [scene name]. */
    const float dot_w = dot_radius * 2.0f;
    const float pill_x = float(rect->xmin) + 6.0f * scale;
    const float pill_h = text_h + pad_y * 2.0f;
    const float pill_y = float(rect->ymax + 1) - 6.0f * scale - pill_h;
    const float pill_w = pad_x * 2.0f + dot_w + 5.0f * scale + text_w;

    immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
    draw_rect(pos, pill_color, pill_x, pill_y, pill_x + pill_w, pill_y + pill_h);

    /* Status dot: orange while the agent works on this scene, gray when idle. */
    const float dot_x = pill_x + pad_x;
    const float dot_y = pill_y + (pill_h - dot_w) * 0.5f;
    draw_rect(pos, busy ? busy_color : idle_color, dot_x, dot_y, dot_x + dot_w, dot_y + dot_w);
    immUnbindProgram();

    BLF_color4f(fontid, 1.0f, 1.0f, 1.0f, 1.0f);
    BLF_position(fontid, dot_x + dot_w + 5.0f * scale, pill_y + pad_y, 0.0f);
    BLF_draw(fontid, name, strlen(name));
  }

  GPU_blend(GPU_BLEND_NONE);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Region Draw
 * \{ */

static void tile_draw_placeholder(const rcti *rect)
{
  GPUVertFormat *format = immVertexFormat();
  uint pos = GPU_vertformat_attr_add(format, "pos", blender::gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_UNIFORM_COLOR);
  immUniformColor4f(0.13f, 0.13f, 0.13f, 1.0f);
  immRectf(pos, float(rect->xmin), float(rect->ymin), float(rect->xmax + 1), float(rect->ymax + 1));
  immUnbindProgram();
}

void view3d_agent_strip_region_draw(const bContext *C, ARegion *region)
{
  ScrArea *area = CTX_wm_area(C);
  const View3D *v3d = static_cast<const View3D *>(area->spacedata.first);
  Main *bmain = CTX_data_main(C);

  if (region->overlap) {
    /* Transparent background: the tiles float over the main viewport,
     * which extends behind this region. */
    GPU_clear_color(0.0f, 0.0f, 0.0f, 0.0f);
  }
  else {
    /* Region overlap disabled in the preferences — the region is docked
     * opaque, fall back to the editor background. */
    ui::theme::frame_buffer_clear(TH_BACK);
  }

  AgentStripRuntime *runtime = view3d_agent_strip_runtime_ensure(region);
  view3d_agent_strip_tick_timer_ensure(C, runtime);
  view3d_agent_strip_tiles_sync(bmain, CTX_data_scene(C), runtime);
  view3d_agent_strip_gpu_garbage_flush(runtime);
  view3d_agent_strip_layout_tiles(region, runtime);

  /* Pass 1: offscreen-render tiles that need it.
   *
   * The draw-manager pass re-binds window framebuffers internally
   * (GPU_framebuffer_restore), and binding resets the per-framebuffer
   * viewport/scissor — which silently destroys this region's drawing setup
   * for the rest of the frame. Capture everything and restore it after. */
  blender::gpu::FrameBuffer *fb_prev = GPU_framebuffer_active_get();
  int viewport_prev[4], scissor_prev[4];
  GPU_viewport_size_get_i(viewport_prev);
  GPU_scissor_get(scissor_prev);

  const bool can_render = !ED_view3d_draw_offscreen_check_nested();
  const double now = BLI_time_now_seconds();
  bool need_refresh = false;
  bool rendered_any = false;

  for (AgentStripTile &tile : runtime->tiles) {
    const int w = BLI_rcti_size_x(&tile.rect) + 1;
    const int h = BLI_rcti_size_y(&tile.rect) + 1;
    if (w < AGENT_STRIP_MIN_TILE_SIZE || h < AGENT_STRIP_MIN_TILE_SIZE) {
      continue;
    }

    const bool size_mismatch = !tile.offscreen || GPU_offscreen_width(tile.offscreen) != w ||
                               GPU_offscreen_height(tile.offscreen) != h;
    const bool throttled = (now - tile.last_render_time) < AGENT_STRIP_MIN_RENDER_INTERVAL;
    /* A size mismatch forces a render — blitting requires the offscreen to
     * match the tile rect exactly. */
    if (!can_render || (!size_mismatch && (!tile.dirty || throttled))) {
      continue;
    }
    if (!tile_gpu_ensure(tile, w, h)) {
      continue;
    }

    ViewLayer *view_layer = static_cast<ViewLayer *>(tile.scene->view_layers.first);
    Depsgraph *depsgraph = view_layer ? BKE_scene_get_depsgraph(tile.scene, view_layer) : nullptr;
    if (!depsgraph || DEG_get_update_count(depsgraph) == 0) {
      /* Missing, or allocated but never evaluated (update count 0 until the
       * first evaluation): an unevaluated graph has no evaluated scene or
       * view layer yet and the draw context would crash dereferencing them.
       * view3d_agent_strip_refresh() will ensure + evaluate it. */
      need_refresh = true;
      continue;
    }

    tile_render(v3d, tile, depsgraph, w, h);
    tile.dirty = false;
    tile.has_render = true;
    tile.last_render_time = now;
    rendered_any = true;
  }

  /* Restore the region's drawing state before any 2D output. */
  if (rendered_any) {
    if (fb_prev) {
      GPU_framebuffer_bind(fb_prev);
    }
    GPU_viewport(viewport_prev[0], viewport_prev[1], viewport_prev[2], viewport_prev[3]);
    GPU_scissor(scissor_prev[0], scissor_prev[1], scissor_prev[2], scissor_prev[3]);
  }
  ED_region_pixelspace(region);

  /* Pass 2: blit every tile (non-dirty tiles keep their last render). */
  for (AgentStripTile &tile : runtime->tiles) {
    const int w = BLI_rcti_size_x(&tile.rect) + 1;
    const int h = BLI_rcti_size_y(&tile.rect) + 1;

    const bool blittable = tile.has_render && tile.viewport && tile.offscreen &&
                           GPU_offscreen_width(tile.offscreen) == w &&
                           GPU_offscreen_height(tile.offscreen) == h;
    if (blittable) {
      GPU_viewport_draw_to_screen_ex(tile.viewport,
                                     0,
                                     &tile.rect,
                                     /*display_colorspace*/ true,
                                     /*do_overlay_merge*/ true);
    }
    else if (w >= AGENT_STRIP_MIN_TILE_SIZE && h >= AGENT_STRIP_MIN_TILE_SIZE) {
      tile_draw_placeholder(&tile.rect);
    }
  }

  /* Pass 3: scene names and agent badges. */
  agent_strip_draw_overlays(runtime);

  if (need_refresh) {
    ED_area_tag_refresh(area);
  }

  /* A tile that stayed dirty (rate limit, nested-draw guard, missing
   * depsgraph) renders on a later draw — keep redraws coming until every
   * tile is clean. Redraws stop as soon as the strip converges. */
  for (const AgentStripTile &tile : runtime->tiles) {
    if (tile.dirty) {
      ED_region_tag_redraw(region);
      break;
    }
  }
}

/** \} */
}  // namespace blender
