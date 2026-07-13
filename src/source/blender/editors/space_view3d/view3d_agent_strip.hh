/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Agent Scene Strip: a bottom-docked 3D viewport region showing a live
 * offscreen-rendered tile for every scene except the window's active one,
 * so parallel AI agents (one per scene) can be monitored without leaving
 * the viewport. A per-tile badge marks scenes whose agent is busy.
 *
 * Successor of the removed Scene Grid editor space: same tile engine
 * (per-tile orbit camera, depsgraph change detection, rate-limited
 * offscreen renders), re-homed as a poll-driven `RGN_TYPE_EXECUTE` region
 * of the View3D space. All per-tile state (camera, GPU buffers, dirty
 * flags) is runtime-only — never written to .blend files.
 */

#pragma once

#include <cstdint>
#include <string>
#include <utility>

#include "BLI_map.hh"
#include "BLI_rect.h"
#include "BLI_vector.hh"

struct ARegion;
struct GPUOffScreen;
struct GPUViewport;
struct Main;
struct Scene;
struct ScrArea;
struct SpaceType;
struct bContext;
struct wmKeyConfig;
struct wmSpaceTypeListenerParams;
struct wmTimer;
struct wmWindowManager;

/* -------------------------------------------------------------------- */
/** \name Constants
 * \{ */

/** Gap between tiles (and region edge), in region pixels. */
#define AGENT_STRIP_TILE_GAP 4

/** Minimum interval between re-renders of one tile, in seconds (~10 Hz). */
#define AGENT_STRIP_MIN_RENDER_INTERVAL 0.1

/** Poll-tick interval: how often the refresh pass checks every tile scene's
 * depsgraph for changes. A clean tick is only flag/counter checks. */
#define AGENT_STRIP_TICK_INTERVAL 0.1

/** Clip range for the fabricated tile viewports. */
#define AGENT_STRIP_CLIP_START 0.1f
#define AGENT_STRIP_CLIP_END 1000.0f

/** Default orbit camera distance. */
#define AGENT_STRIP_DEFAULT_DIST 10.0f

/** Vertical field of view of tile viewports, in radians (~40 degrees). */
#define AGENT_STRIP_FOV_Y 0.69813f

/** Tiles smaller than this on either axis are not rendered. */
#define AGENT_STRIP_MIN_TILE_SIZE 8

/** Preferred aspect (width / height) of a strip tile. */
#define AGENT_STRIP_TILE_ASPECT 1.6f

/** Default strip height in unscaled region units (`ARegionType.prefsizey`). */
#define AGENT_STRIP_PREFSIZEY 140

/** \} */

/* -------------------------------------------------------------------- */
/** \name Runtime Types
 * \{ */

/** Turntable orbit camera, mirrors the RegionView3D viewquat/ofs/dist model. */
struct AgentStripCamera {
  float viewquat[4];
  float ofs[3];
  float dist;
};

struct AgentStripTile {
  /** Scene displayed by this tile. Resolved against bmain on every sync. */
  Scene *scene = nullptr;
  /** Scene name, used to survive tile rebuilds and scene deletion mid-drag. */
  std::string scene_name;

  /** Cached GPU buffers, recreated when the tile rect size changes. */
  GPUOffScreen *offscreen = nullptr;
  GPUViewport *viewport = nullptr;

  AgentStripCamera cam;

  /** Scene content (or camera) changed since the last render. */
  bool dirty = true;
  /** True once the offscreen holds a valid render that may be blitted. */
  bool has_render = false;
  double last_render_time = 0.0;

  /** Agent badge state at the last refresh, to redraw on flips. */
  bool was_busy = false;
  /** DEG_get_update_count() of the scene's depsgraph at the last refresh;
   * a different count means the scene was re-evaluated since. */
  uint64_t last_update_count = 0;

  /** Region-local pixel rect, recomputed by the layout pass each draw. */
  rcti rect = {};
};

struct AgentStripRuntime {
  blender::Vector<AgentStripTile> tiles;
  /** Cameras of removed/rebuilt tiles, keyed by scene name. */
  blender::Map<std::string, AgentStripCamera> cam_cache;
  /** GPU buffers of removed tiles; freed during draw when a context is bound. */
  blender::Vector<std::pair<GPUOffScreen *, GPUViewport *>> gpu_garbage;
  /** Periodic TIMERNOTIFIER driving the change-detection refresh while the
   * strip is visible. Owned here; removed in the region exit callback. */
  wmTimer *tick_timer = nullptr;
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name view3d_agent_strip_runtime.cc
 * \{ */

/** Register the strip's `RGN_TYPE_EXECUTE` region type on the View3D space
 * type. */
void view3d_agent_strip_region_register(SpaceType *st);

AgentStripRuntime *view3d_agent_strip_runtime_ensure(ARegion *region);

/** The strip region of `area`, or null (also for non-View3D areas). */
ARegion *view3d_agent_strip_region_find(const ScrArea *area);

/** Per-scene busy flag maintained by the Python chat module
 * (`scene.mixie_chat_is_busy`); false when the property isn't registered. */
bool view3d_agent_strip_scene_busy(Scene *scene);

/** Rebuild the tile list from all scenes in `bmain` except `scene_active`
 * (the window's active scene — already on screen in the main viewport),
 * preserving per-scene cameras and GPU buffers of scenes still present. */
void view3d_agent_strip_tiles_sync(Main *bmain,
                                   const Scene *scene_active,
                                   AgentStripRuntime *runtime);

/** Free queued GPU buffers. Must be called with an active GPU context. */
void view3d_agent_strip_gpu_garbage_flush(AgentStripRuntime *runtime);

AgentStripTile *view3d_agent_strip_tile_find_named(AgentStripRuntime *runtime,
                                                   const char *scene_name);

/** Mark every tile dirty (cheap; actual re-renders are rate-limited). */
void view3d_agent_strip_tiles_tag_dirty_all(AgentStripRuntime *runtime);
/** Mark only the tile showing `scene` dirty; returns false when not found. */
bool view3d_agent_strip_tiles_tag_dirty_scene(AgentStripRuntime *runtime, const Scene *scene);

/** Make sure the periodic poll timer exists (recreated lazily, e.g. after
 * its window closed). Called from the strip region draw. */
void view3d_agent_strip_tick_timer_ensure(const bContext *C, AgentStripRuntime *runtime);
void view3d_agent_strip_tick_timer_remove(wmWindowManager *wm, AgentStripRuntime *runtime);

/** Strip-specific additions to the View3D space listener: instant dirty
 * tagging for scene/object edits, and the periodic refresh tick. */
void view3d_agent_strip_space_listener(const wmSpaceTypeListenerParams *params);

/** Change-detection refresh: evaluates non-window-active tile scenes and
 * dirties tiles whose depsgraph did real work. Called from the View3D area
 * refresh; a no-op while the strip region is hidden. */
void view3d_agent_strip_refresh(const bContext *C, ScrArea *area);

/** \} */

/* -------------------------------------------------------------------- */
/** \name view3d_agent_strip_draw.cc
 * \{ */

void view3d_agent_strip_region_init(wmWindowManager *wm, ARegion *region);
void view3d_agent_strip_region_exit(wmWindowManager *wm, ARegion *region);
void view3d_agent_strip_region_draw(const bContext *C, ARegion *region);

/** Recompute `tile->rect` for all tiles: one left-aligned row. */
void view3d_agent_strip_layout_tiles(const ARegion *region, AgentStripRuntime *runtime);

/** Tile under the region-local mouse position, or null. */
AgentStripTile *view3d_agent_strip_tile_at(AgentStripRuntime *runtime, const int mval[2]);

/** \} */

/* -------------------------------------------------------------------- */
/** \name view3d_agent_strip_ops.cc
 * \{ */

/** Register the strip operators. Called with the other View3D operator
 * types (region-level `operatortypes` callbacks are never invoked). */
void view3d_agent_strip_operatortypes();

/** `ARegionType.keymap` callback: click-to-activate, orbit/pan drag, zoom. */
void view3d_agent_strip_keymap(wmKeyConfig *keyconf);

/** \} */
