/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Scene-card thumbnails for the Scenes drawer: a SNAPSHOT of the host
 * viewport, never a render of the card's scene.
 *
 * The card shows the tab as the user last saw it. The picture is taken from
 * the View3D WINDOW region's own `GPUViewport` — the frame the event loop
 * already drew — colour-managed and overlay-merged exactly as it reached the
 * screen, copied to the CPU and box-resampled to thumb size. Nothing here
 * evaluates a depsgraph, runs a draw engine, compiles a
 * shader or touches a scene no window shows: the crash class this replaces
 * (an EEVEE material render of every tab from a timer, next to a Cycles
 * viewport, on a driver whose worker thread faulted) has no code path left.
 *
 * When the picture is taken:
 *  - `view3d.scenes_drawer_snapshot`, called by the Python tab switch BEFORE
 *    the windows move to another scene (the leaving tab's last frame);
 *  - `view3d.scenes_drawer_thumbs`, the drawer tick, refreshes only the SHOWN
 *    tab's card, throttled and only when its depsgraph changed.
 * A tab nobody has shown since it was made, or that a worker changed in the
 * background, keeps its last picture (or none) until it is shown again.
 *
 * Pixels live in a session store keyed by scene name so a workspace rebuild
 * (Zen <-> Engine frees the region) does not blank every card; the store
 * resets when Main is replaced. Fail closed: any GPU failure keeps the last
 * pixels, and a few failures in a row disable snapshots for the session.
 * `MIXAR_SCENES_DRAWER_THUMBS=0` disables them without a rebuild.
 */

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>

#include "MEM_guardedalloc.h"

#include "BLI_listbase.h"
#include "BLI_math_vector_types.hh"
#include "BLI_listbase_iterator.hh"
#include "BLI_rect.h"
#include "BLI_string.h"
#include "BLI_time.h"

#include "BKE_context.hh"
#include "BKE_global.hh"
#include "BKE_main.hh"
#include "BKE_scene.hh"
#include "BKE_wm_runtime.hh"

#include "DEG_depsgraph.hh"
#include "DEG_depsgraph_query.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_windowmanager_types.h"

#include "GPU_context.hh"
#include "GPU_immediate.hh"
#include <cmath>
#include "GPU_shader_builtin.hh"
#include "GPU_state.hh"
#include "GPU_texture.hh"
#include "GPU_viewport.hh"

#include "WM_api.hh"
#include "WM_mixar.hh"
#include "WM_types.hh"

#include "view3d_scenes_drawer.hh"

namespace blender {

/* -------------------------------------------------------------------- */
/** \name Session store
 * \{ */

struct SnapshotEntry {
  std::vector<unsigned char> pixels;
  int w = 0;
  int h = 0;
  /** Bumped on every capture; a region thumb re-copies when it differs. */
  uint64_t generation = 0;
  /** Depsgraph update count and wall clock of the last capture (throttle). */
  uint64_t update_count = 0;
  double captured_at = 0.0;
};

struct SnapshotStore {
  const Main *bmain = nullptr;
  std::string filepath;
  std::unordered_map<std::string, SnapshotEntry> by_scene;
  uint64_t next_generation = 1;
};

static SnapshotStore g_store;
/** Fail closed: set after `SNAPSHOT_MAX_FAILURES` GPU failures in a row. */
static bool g_disabled = false;
static int g_failures = 0;
static constexpr int SNAPSHOT_MAX_FAILURES = 3;
/** The shown card refreshes at most this often (seconds). */
static constexpr double SNAPSHOT_REFRESH_INTERVAL = 2.0;

static bool snapshots_enabled_env()
{
  static int state = -1;
  if (state < 0) {
    const char *value = std::getenv("MIXAR_SCENES_DRAWER_THUMBS");
    const bool off = value != nullptr &&
                     (STREQ(value, "0") || STREQ(value, "off") || STREQ(value, "false"));
    state = off ? 0 : 1;
  }
  return state == 1;
}

bool view3d_scenes_drawer_snapshots_enabled()
{
  return snapshots_enabled_env() && !g_disabled;
}

static void store_sync_main(const Main *bmain)
{
  if (bmain == nullptr) {
    return;
  }
  if (g_store.bmain != bmain || g_store.filepath != bmain->filepath) {
    g_store.by_scene.clear();
    g_store.bmain = bmain;
    g_store.filepath = bmain->filepath;
  }
}

static void snapshot_failed(const char *why)
{
  g_failures++;
  if (g_failures >= SNAPSHOT_MAX_FAILURES && !g_disabled) {
    g_disabled = true;
    fprintf(stderr,
            "[scenes_drawer] card snapshots disabled for this session after %d failures (%s)\n",
            g_failures,
            why);
  }
}

bool view3d_scenes_drawer_snapshot_exists(const std::string &scene_name)
{
  auto it = g_store.by_scene.find(scene_name);
  return it != g_store.by_scene.end() && !it->second.pixels.empty();
}

void view3d_scenes_drawer_snapshot_evict(const Main *bmain)
{
  if (bmain == nullptr) {
    return;
  }
  store_sync_main(bmain);
  for (auto it = g_store.by_scene.begin(); it != g_store.by_scene.end();) {
    const bool alive = BLI_findstring(&bmain->scenes, it->first.c_str(), offsetof(ID, name) + 2) !=
                       nullptr;
    it = alive ? std::next(it) : g_store.by_scene.erase(it);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Guards
 * \{ */

bool view3d_scenes_drawer_snapshot_blocked(const bContext *C)
{
  if (!view3d_scenes_drawer_snapshots_enabled()) {
    return true;
  }
  /* A timer-driven operator on macOS and Windows can run inside the OS resize
   * callback; GPU work there is the crash CLAUDE.md's resize rule describes. */
  if (Mixar_window_resize_dispatch_active()) {
    return true;
  }
  if (G.is_rendering || GPU_context_active_get() == nullptr) {
    return true;
  }
  const wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return true;
  }
  if (wm->runtime != nullptr && wm->runtime->is_interface_locked) {
    return true;
  }
  /* The island and pill move through a modal on their own window; the host
   * frame under them is being re-composited and re-parented while it runs. */
  static wmOperatorType *drag_ot = nullptr;
  if (drag_ot == nullptr) {
    drag_ot = WM_operatortype_find("MIXAR_OT_bubble_header_drag", true);
  }
  if (drag_ot != nullptr) {
    for (wmWindow &win : wm->windows) {
      if (WM_operator_find_modal_by_type(&win, drag_ot) != nullptr) {
        return true;
      }
    }
  }
  return false;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Capture
 * \{ */

/** Encode one linear channel for display (sRGB piecewise curve). */
static inline float srgb_encode(const float v)
{
  const float c = std::clamp(v, 0.0f, 1.0f);
  return c <= 0.0031308f ? c * 12.92f : 1.055f * std::pow(c, 1.0f / 2.4f) - 0.055f;
}

/** The overlay texture is sRGB-encoded storage read back raw: decode a byte
 * to linear the way sampling it in a shader would. */
static float srgb_decode_byte(const unsigned char b)
{
  static float lut[256];
  static bool ready = false;
  if (!ready) {
    for (int i = 0; i < 256; i++) {
      const float c = float(i) / 255.0f;
      lut[i] = c <= 0.04045f ? c / 12.92f : std::pow((c + 0.055f) / 1.055f, 2.4f);
    }
    ready = true;
  }
  return lut[b];
}

/** Copy the host viewport's finished frame to the CPU and box-resample it to
 * the thumb: the scene layer (linear float) with the premultiplied overlay
 * layer over it, averaged in linear light and then encoded for display, the
 * way `gpu_shader_image_overlays_merge_frag.glsl` composites a frame for the
 * window (`GPU_viewport_draw_to_screen`). Both textures are copied
 * to host-readable twins first, Blender's own colour-picker recipe
 * (`ViewportColorSampleSession`): the viewport's textures have no HOST_READ
 * usage, and a viewport texture sampled by a shader OUTSIDE the frame that
 * drew it comes up black on Metal (the previous renderer hit the same). A
 * read-back has no such lifetime. Returns false (last pixels kept) on any
 * failure. */
static bool snapshot_read_viewport(GPUViewport *viewport,
                                   const int thumb_w,
                                   const int thumb_h,
                                   std::vector<unsigned char> &r_pixels)
{
  gpu::Texture *color = GPU_viewport_color_texture(viewport, 0);
  gpu::Texture *overlay = GPU_viewport_overlay_texture(viewport, 0);
  if (color == nullptr) {
    return false;
  }
  const int w = GPU_texture_width(color);
  const int h = GPU_texture_height(color);
  if (w < 8 || h < 8 || w > 16384 || h > 16384) {
    return false;
  }
  auto read_copy = [&](gpu::Texture *src, const eGPUDataFormat data_format) -> void * {
    gpu::Texture *copy = GPU_texture_create_2d("scenes_drawer_snapshot_copy",
                                               w,
                                               h,
                                               1,
                                               GPU_texture_format(src),
                                               GPU_TEXTURE_USAGE_HOST_READ,
                                               nullptr);
    if (copy == nullptr) {
      return nullptr;
    }
    GPU_texture_copy(copy, src);
    GPU_memory_barrier(GPU_BARRIER_TEXTURE_UPDATE);
    void *data = GPU_texture_read(copy, data_format, 0);
    GPU_texture_free(copy);
    return data;
  };
  float *scene = static_cast<float *>(read_copy(color, GPU_DATA_FLOAT));
  if (scene == nullptr) {
    snapshot_failed("scene read-back");
    return false;
  }
  unsigned char *over = nullptr;
  if (overlay && GPU_texture_width(overlay) == w && GPU_texture_height(overlay) == h) {
    over = static_cast<unsigned char *>(read_copy(overlay, GPU_DATA_UBYTE));
  }

  r_pixels.assign(size_t(thumb_w) * size_t(thumb_h) * 4, 0);
  for (int y = 0; y < thumb_h; y++) {
    const int sy0 = (y * h) / thumb_h;
    const int sy1 = std::max(sy0 + 1, ((y + 1) * h) / thumb_h);
    for (int x = 0; x < thumb_w; x++) {
      const int sx0 = (x * w) / thumb_w;
      const int sx1 = std::max(sx0 + 1, ((x + 1) * w) / thumb_w);
      float rgb[3] = {0.0f, 0.0f, 0.0f};
      float ov[4] = {0.0f, 0.0f, 0.0f, 0.0f};
      uint32_t count = 0;
      for (int sy = sy0; sy < sy1 && sy < h; sy++) {
        const size_t row = size_t(sy) * size_t(w);
        for (int sx = sx0; sx < sx1 && sx < w; sx++) {
          const float *sp = scene + (row + size_t(sx)) * 4;
          rgb[0] += sp[0];
          rgb[1] += sp[1];
          rgb[2] += sp[2];
          if (over) {
            const unsigned char *op = over + (row + size_t(sx)) * 4;
            ov[0] += srgb_decode_byte(op[0]);
            ov[1] += srgb_decode_byte(op[1]);
            ov[2] += srgb_decode_byte(op[2]);
            ov[3] += float(op[3]) / 255.0f;
          }
          count++;
        }
      }
      unsigned char *out = r_pixels.data() + (size_t(y) * size_t(thumb_w) + size_t(x)) * 4;
      if (count == 0) {
        continue;
      }
      const float inv = 1.0f / float(count);
      const float alpha = ov[3] * inv;
      for (int c = 0; c < 3; c++) {
        /* Premultiplied overlay over the scene, in linear light. */
        const float lin = rgb[c] * inv * (1.0f - alpha) + ov[c] * inv;
        out[c] = uchar(srgb_encode(lin) * 255.0f + 0.5f);
      }
      out[3] = 255;
    }
  }
  MEM_delete_void(static_cast<void *>(scene));
  if (over) {
    MEM_delete_void(static_cast<void *>(over));
  }
  g_failures = 0;
  return true;
}

bool view3d_scenes_drawer_snapshot_capture(const bContext *C,
                                           ARegion *host_region,
                                           const Scene *scene,
                                           const int thumb_w,
                                           const int thumb_h,
                                           const bool force)
{
  Main *bmain = CTX_data_main(C);
  if (bmain == nullptr || scene == nullptr || host_region == nullptr || thumb_w < 8 ||
      thumb_h < 8 || host_region->regiontype != RGN_TYPE_WINDOW)
  {
    return false;
  }
  if (view3d_scenes_drawer_snapshot_blocked(C)) {
    return false;
  }
  store_sync_main(bmain);
  const std::string name(scene->id.name + 2);
  SnapshotEntry &entry = g_store.by_scene[name];

  /* The shown card's refresh: only after the tab changed, and not too often.
   * A forced capture (the tab is about to leave the screen) always runs. */
  const ViewLayer *view_layer = static_cast<const ViewLayer *>(scene->view_layers.first);
  const Depsgraph *deps = view_layer ? BKE_scene_get_depsgraph(scene, view_layer) : nullptr;
  const uint64_t update_count = deps ? DEG_get_update_count(deps) : 0;
  const double now = BLI_time_now_seconds();
  if (!force && !entry.pixels.empty()) {
    if (entry.update_count == update_count) {
      return false;
    }
    if (now - entry.captured_at < SNAPSHOT_REFRESH_INTERVAL) {
      return false;
    }
  }
  GPUViewport *viewport = WM_draw_region_get_viewport(host_region);
  if (viewport == nullptr) {
    /* Not drawn yet (or mid-resize): nothing to copy, and nothing to do. */
    return false;
  }
  /* The viewport's textures belong to the host window's context; the island
   * and pill windows are often the drawable one when a timer runs. */
  const wmWindowManager *wm = CTX_wm_manager(C);
  const bool switched = Mixar_window_gpu_context_push(wm, CTX_wm_window(C));
  std::vector<unsigned char> pixels;
  const bool ok = snapshot_read_viewport(viewport, thumb_w, thumb_h, pixels);
  if (switched) {
    Mixar_window_gpu_context_pop(wm);
  }
  if (!ok) {
    return false;
  }
  entry.pixels = std::move(pixels);
  entry.w = thumb_w;
  entry.h = thumb_h;
  entry.generation = g_store.next_generation++;
  entry.update_count = update_count;
  entry.captured_at = now;
  return true;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Card texture
 * \{ */

void view3d_scenes_drawer_thumb_free(ScenesDrawerThumb &t)
{
  if (t.texture) {
    GPU_texture_free(t.texture);
  }
  t.texture = nullptr;
  t.pixels.clear();
  t.pixels_w = t.pixels_h = 0;
  t.pixels_dirty = false;
  t.generation = 0;
}

void view3d_scenes_drawer_thumb_draw(ScenesDrawerThumb &t,
                                     const std::string &scene_name,
                                     const rcti &rect)
{
  /* Pull the store's latest picture into this region's copy. The store owns
   * the pixels across region rebuilds; the texture belongs to the region. */
  auto found = g_store.by_scene.find(scene_name);
  if (found != g_store.by_scene.end() && !found->second.pixels.empty() &&
      found->second.generation != t.generation)
  {
    t.pixels = found->second.pixels;
    t.pixels_w = found->second.w;
    t.pixels_h = found->second.h;
    t.generation = found->second.generation;
    t.pixels_dirty = true;
  }
  if (t.pixels.empty()) {
    return;
  }
  if (t.texture && (GPU_texture_width(t.texture) != t.pixels_w ||
                    GPU_texture_height(t.texture) != t.pixels_h))
  {
    GPU_texture_free(t.texture);
    t.texture = nullptr;
  }
  if (!t.texture) {
    t.texture = GPU_texture_create_2d("scenes_drawer_thumb",
                                      t.pixels_w,
                                      t.pixels_h,
                                      1,
                                      gpu::TextureFormat::UNORM_8_8_8_8,
                                      GPU_TEXTURE_USAGE_SHADER_READ,
                                      nullptr);
    if (!t.texture) {
      return;
    }
    t.pixels_dirty = true;
  }
  if (t.pixels_dirty) {
    GPU_texture_update(t.texture, GPU_DATA_UBYTE, t.pixels.data());
    t.pixels_dirty = false;
  }
  /* The snapshot is already in display space and opaque. */
  GPU_blend(GPU_BLEND_NONE);
  GPUSamplerState sampler = GPUSamplerState::default_sampler();
  sampler.filtering = GPU_SAMPLER_FILTERING_LINEAR;
  GPUVertFormat *format = immVertexFormat();
  const uint pos = GPU_vertformat_attr_add(format, "pos", gpu::VertAttrType::SFLOAT_32_32);
  const uint texco = GPU_vertformat_attr_add(format, "texCoord", gpu::VertAttrType::SFLOAT_32_32);
  immBindBuiltinProgram(GPU_SHADER_3D_IMAGE);
  immBindTextureSampler("image", t.texture, sampler);
  immBegin(GPU_PRIM_TRI_FAN, 4);
  immAttr2f(texco, 0.0f, 0.0f);
  immVertex2f(pos, float(rect.xmin), float(rect.ymin));
  immAttr2f(texco, 1.0f, 0.0f);
  immVertex2f(pos, float(rect.xmax + 1), float(rect.ymin));
  immAttr2f(texco, 1.0f, 1.0f);
  immVertex2f(pos, float(rect.xmax + 1), float(rect.ymax + 1));
  immAttr2f(texco, 0.0f, 1.0f);
  immVertex2f(pos, float(rect.xmin), float(rect.ymax + 1));
  immEnd();
  immUnbindProgram();
  GPU_texture_unbind(t.texture);
  GPU_blend(GPU_BLEND_ALPHA);
}

/** \} */

}  // namespace blender
