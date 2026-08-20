/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Agent Scene Strip runtime: region-type registration, tile list sync
 * (all scenes except the window-active one), listener/refresh, and GPU
 * cleanup.
 *
 * Change-detection model (inherited from the Scene Grid editor): every
 * bpy/RNA mutation tags ALL registered depsgraphs containing the ID —
 * including the ones this strip builds for non-active scenes — so "did
 * scene X change" reduces to per-depsgraph state:
 *
 * - `DEG_id_type_any_updated()` is set at *tag* time and consumed by
 *   evaluation (`BKE_scene_graph_update_tagged()` clears it internally),
 *   so it gates whether an evaluation is worth running at all.
 * - `DEG_get_update_count()` changes exactly when an evaluation did real
 *   work and persists afterwards, so comparing it against a stored value
 *   detects changes race-free — even for window-active scenes, whose
 *   evaluation (and flag clearing) is owned by the window manager.
 *
 * A 0.1 s TIMERNOTIFIER tick drives this refresh while the strip is
 * visible; a clean tick costs only these flag/counter checks.
 */

#include <string>

#include "MEM_guardedalloc.h"

#include "BLI_listbase.h"
#include "BLI_math_rotation.h"
#include "BLI_math_vector.h"

#include "BKE_context.hh"
#include "BKE_layer.hh"
#include "BKE_main.hh"
#include "BKE_scene.hh"
#include "BKE_screen.hh"

#include "DEG_depsgraph.hh"
#include "DEG_depsgraph_query.hh"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "DRW_engine.hh"

#include "ED_screen.hh"

#include "GPU_framebuffer.hh"
#include "GPU_viewport.hh"

#include "RNA_access.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "view3d_agent_strip.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Agent Busy Flag
 * \{ */

bool view3d_agent_strip_scene_busy(Scene *scene)
{
  /* Same graceful-degradation pattern as the Mixie Chat footer: when the
   * Python property isn't registered, `find_property` returns null and we
   * default to "not busy" instead of asserting. */
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *busy_prop = RNA_struct_find_property(&scene_ptr, "mixie_chat_is_busy");
  return busy_prop ? RNA_property_boolean_get(&scene_ptr, busy_prop) : false;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Runtime Lifecycle
 * \{ */

ARegion *view3d_agent_strip_region_find(const ScrArea *area)
{
  if (!area || area->spacetype != SPACE_VIEW3D) {
    return nullptr;
  }
  return BKE_area_find_region_type(area, RGN_TYPE_EXECUTE);
}

AgentStripRuntime *view3d_agent_strip_runtime_ensure(ARegion *region)
{
  if (!region->regiondata) {
    region->regiondata = MEM_new<AgentStripRuntime>("AgentStripRuntime");
    /* Runtime-only payload: blend-write must skip it and area duplication
     * must not shallow-copy it. */
    region->flag |= RGN_FLAG_TEMP_REGIONDATA;
  }
  return static_cast<AgentStripRuntime *>(region->regiondata);
}

static void tile_gpu_queue_free(AgentStripRuntime *runtime, AgentStripTile &tile)
{
  if (tile.offscreen || tile.viewport) {
    runtime->gpu_garbage.append({tile.offscreen, tile.viewport});
    tile.offscreen = nullptr;
    tile.viewport = nullptr;
    tile.has_render = false;
  }
}

void view3d_agent_strip_gpu_garbage_flush(AgentStripRuntime *runtime)
{
  for (auto &[offscreen, viewport] : runtime->gpu_garbage) {
    if (viewport) {
      GPU_viewport_free(viewport);
    }
    if (offscreen) {
      GPU_offscreen_free(offscreen);
    }
  }
  runtime->gpu_garbage.clear();
}

/** `ARegionType.free`: region is being destroyed (area close, file load,
 * quit) — outside drawing, where no GPU context is guaranteed. Borrow the
 * draw-manager context, as the XR session does for its offscreen surfaces. */
static void agent_strip_region_free(ARegion *region)
{
  AgentStripRuntime *runtime = static_cast<AgentStripRuntime *>(region->regiondata);
  if (!runtime) {
    return;
  }

  for (AgentStripTile &tile : runtime->tiles) {
    tile_gpu_queue_free(runtime, tile);
  }
  if (!runtime->gpu_garbage.is_empty()) {
    DRW_gpu_context_enable();
    view3d_agent_strip_gpu_garbage_flush(runtime);
    DRW_gpu_context_disable();
  }

  MEM_delete(runtime);
  region->regiondata = nullptr;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Poll-Tick Timer
 * \{ */

void view3d_agent_strip_tick_timer_ensure(const bContext *C, AgentStripRuntime *runtime)
{
  if (runtime->tick_timer) {
    return;
  }
  wmWindowManager *wm = CTX_wm_manager(C);
  wmWindow *win = CTX_wm_window(C);
  if (!wm || !win) {
    return;
  }
  /* Fires NC_SPACE | ND_SPACE_AGENT_STRIP_TICK; the space listener turns it
   * into an area refresh where the actual change detection runs. Timer
   * lifetime follows the window — if that window closes, the WM frees the
   * timer and the next draw (in whichever window) re-creates it here. */
  runtime->tick_timer = WM_event_timer_add_notifier(
      wm, win, NC_SPACE | ND_SPACE_AGENT_STRIP_TICK, AGENT_STRIP_TICK_INTERVAL);
}

void view3d_agent_strip_tick_timer_remove(wmWindowManager *wm, AgentStripRuntime *runtime)
{
  if (!runtime || !runtime->tick_timer) {
    return;
  }
  /* Plain remove, not WM_event_timer_remove_notifier: it membership-checks
   * before touching the timer, so this stays safe when the timer's window
   * already closed and the WM freed it. The notifier variant writes to the
   * timer first. Customdata is a packed uint (WM_TIMER_NO_FREE_CUSTOM_DATA),
   * nothing to free. */
  WM_event_timer_remove(wm, nullptr, runtime->tick_timer);
  runtime->tick_timer = nullptr;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Camera Defaults & Tile Sync
 * \{ */

static void agent_strip_camera_init_default(AgentStripCamera *cam)
{
  /* Turntable user view: pitch the top view up 65 degrees, then rotate 30
   * degrees around world Z — close to the default View3D startup angle. */
  float qx[4], qz[4];
  axis_angle_to_quat_single(qx, 'X', DEG2RADF(-65.0f));
  axis_angle_to_quat_single(qz, 'Z', DEG2RADF(30.0f));
  mul_qt_qtqt(cam->viewquat, qx, qz);
  normalize_qt(cam->viewquat);

  zero_v3(cam->ofs);
  cam->dist = AGENT_STRIP_DEFAULT_DIST;
}

/** Scenes shown by the strip: every scene in bmain order except the
 * window's active one (that scene already fills the main viewport). */
static blender::Vector<Scene *> agent_strip_scenes(Main *bmain, const Scene *scene_active)
{
  blender::Vector<Scene *> scenes;
  for (Scene &scene_iter : bmain->scenes) {
    Scene *scene = &scene_iter;
    if (scene != scene_active) {
      scenes.append(scene);
    }
  }
  return scenes;
}

static bool tiles_match_scenes(const AgentStripRuntime *runtime,
                               const blender::Vector<Scene *> &scenes)
{
  if (runtime->tiles.size() != scenes.size()) {
    return false;
  }
  for (const int i : scenes.index_range()) {
    const AgentStripTile &tile = runtime->tiles[i];
    if (tile.scene != scenes[i] || tile.scene_name != scenes[i]->id.name + 2) {
      return false;
    }
  }
  return true;
}

void view3d_agent_strip_tiles_sync(Main *bmain,
                                   const Scene *scene_active,
                                   AgentStripRuntime *runtime)
{
  const blender::Vector<Scene *> scenes = agent_strip_scenes(bmain, scene_active);
  if (tiles_match_scenes(runtime, scenes)) {
    return;
  }

  blender::Vector<AgentStripTile> new_tiles;

  for (Scene *scene : scenes) {
    const char *name = scene->id.name + 2;

    /* Reuse the existing tile for this scene to keep its camera and GPU
     * buffers. Match by pointer first, then by name (scene pointers change
     * across undo steps while the scene logically persists). */
    AgentStripTile *old_tile = nullptr;
    for (AgentStripTile &tile : runtime->tiles) {
      if (tile.scene == scene) {
        old_tile = &tile;
        break;
      }
    }
    if (!old_tile) {
      for (AgentStripTile &tile : runtime->tiles) {
        if (tile.scene != nullptr && tile.scene_name == name) {
          old_tile = &tile;
          break;
        }
      }
    }

    if (old_tile) {
      AgentStripTile tile = std::move(*old_tile);
      /* Mark consumed: raw pointers survive a move, the cleanup loop below
       * must not double-free or cache this slot. */
      old_tile->scene = nullptr;
      old_tile->offscreen = nullptr;
      old_tile->viewport = nullptr;
      tile.scene = scene;
      tile.scene_name = name;
      tile.dirty = true;
      new_tiles.append(std::move(tile));
    }
    else {
      AgentStripTile tile;
      tile.scene = scene;
      tile.scene_name = name;
      if (const AgentStripCamera *cached = runtime->cam_cache.lookup_ptr(tile.scene_name)) {
        tile.cam = *cached;
      }
      else {
        agent_strip_camera_init_default(&tile.cam);
      }
      new_tiles.append(std::move(tile));
    }
  }

  /* Tiles whose scene is gone: remember the camera, queue GPU buffers. */
  for (AgentStripTile &tile : runtime->tiles) {
    if (tile.scene == nullptr) {
      continue; /* Consumed by a move above. */
    }
    runtime->cam_cache.add_overwrite(tile.scene_name, tile.cam);
    tile_gpu_queue_free(runtime, tile);
  }

  runtime->tiles = std::move(new_tiles);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Tile Lookups & Dirty Tagging
 * \{ */

AgentStripTile *view3d_agent_strip_tile_find_named(AgentStripRuntime *runtime,
                                                   const char *scene_name)
{
  for (AgentStripTile &tile : runtime->tiles) {
    if (tile.scene_name == scene_name) {
      return &tile;
    }
  }
  return nullptr;
}

void view3d_agent_strip_tiles_tag_dirty_all(AgentStripRuntime *runtime)
{
  for (AgentStripTile &tile : runtime->tiles) {
    tile.dirty = true;
  }
}

bool view3d_agent_strip_tiles_tag_dirty_scene(AgentStripRuntime *runtime, const Scene *scene)
{
  for (AgentStripTile &tile : runtime->tiles) {
    if (tile.scene == scene) {
      tile.dirty = true;
      return true;
    }
  }
  return false;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Space Listener & Refresh
 * \{ */

static bool agent_strip_region_visible(const ARegion *region)
{
  return region && !(region->flag & (RGN_FLAG_HIDDEN | RGN_FLAG_POLL_FAILED));
}

void view3d_agent_strip_space_listener(const wmSpaceTypeListenerParams *params)
{
  ScrArea *area = params->area;
  const wmNotifier *wmn = params->notifier;

  ARegion *region = view3d_agent_strip_region_find(area);
  if (!agent_strip_region_visible(region)) {
    return;
  }
  AgentStripRuntime *runtime = static_cast<AgentStripRuntime *>(region->regiondata);

  bool changed = false;

  switch (wmn->category) {
    case NC_SCENE:
    case NC_OBJECT:
    case NC_GEOM:
    case NC_MATERIAL:
    case NC_ANIMATION:
    case NC_WORLD:
    case NC_LAMP:
    case NC_IMAGE:
      /* Instant (sub-tick) response for operator/UI edits. When the notifier
       * references a scene we know, dirty only that tile; otherwise we can't
       * attribute it — dirty all. Re-render cost is bounded by the per-tile
       * rate limit, and anything missed here is caught by the poll tick. */
      if (runtime) {
        if (!(wmn->reference &&
              view3d_agent_strip_tiles_tag_dirty_scene(runtime,
                                                       static_cast<Scene *>(wmn->reference))))
        {
          view3d_agent_strip_tiles_tag_dirty_all(runtime);
        }
      }
      changed = true;
      break;
    case NC_SPACE:
      if (wmn->data == ND_SPACE_AGENT_STRIP_TICK) {
        /* Poll tick: refresh only. The refresh tags a redraw itself when it
         * actually finds changes — tagging redraws here would render every
         * tile at the tick rate for no reason. */
        ED_area_tag_refresh(area);
      }
      else if (wmn->data == ND_SPACE_AGENT_STRIP) {
        if (runtime) {
          view3d_agent_strip_tiles_tag_dirty_all(runtime);
        }
        changed = true;
      }
      break;
    case NC_WINDOW:
    case NC_SCREEN:
      /* Theme / layout / active-scene changes: highlight border only. */
      ED_region_tag_redraw(region);
      break;
  }

  if (changed) {
    ED_area_tag_refresh(area);
    ED_region_tag_redraw(region);
  }
}

static bool scene_is_window_active(const wmWindowManager *wm, const Scene *scene)
{
  for (const wmWindow &win_iter : wm->windows) {
    const wmWindow *win = &win_iter;
    if (WM_window_get_active_scene(win) == scene) {
      return true;
    }
  }
  return false;
}

void view3d_agent_strip_refresh(const bContext *C, ScrArea *area)
{
  ARegion *region = view3d_agent_strip_region_find(area);
  if (!agent_strip_region_visible(region)) {
    return;
  }

  Main *bmain = CTX_data_main(C);
  wmWindowManager *wm = CTX_wm_manager(C);

  AgentStripRuntime *runtime = view3d_agent_strip_runtime_ensure(region);
  view3d_agent_strip_tiles_sync(bmain, CTX_data_scene(C), runtime);

  bool any_pending = false;
  bool badge_flipped = false;

  for (AgentStripTile &tile : runtime->tiles) {
    /* Agent badge: a flipped busy dot needs a redraw, not a re-render. */
    const bool busy = view3d_agent_strip_scene_busy(tile.scene);
    if (busy != tile.was_busy) {
      tile.was_busy = busy;
      badge_flipped = true;
    }

    ViewLayer *view_layer = static_cast<ViewLayer *>(tile.scene->view_layers.first);
    if (!view_layer) {
      continue;
    }

    Depsgraph *depsgraph = BKE_scene_get_depsgraph(tile.scene, view_layer);
    if (!depsgraph) {
      depsgraph = BKE_scene_ensure_depsgraph(bmain, tile.scene, view_layer);
      if (!depsgraph) {
        continue;
      }
    }

    /* Window-active scenes are evaluated by the WM right after this refresh
     * phase; evaluating (and thereby clearing tags) here would race it. For
     * all other scenes nothing evaluates them but us.
     *
     * An update count of 0 means ensured-but-never-evaluated: such a graph
     * has no tags (it contains no IDs yet, so tagging passed it by) and the
     * tile can still hold a render — tiles are recycled by scene name when
     * pointers change (undo, agent deleting + recreating a scene) — so
     * neither other condition fires. Skipping evaluation here would leave a
     * graph the draw callback can never use: it has no evaluated scene or
     * view layer, and rendering it would crash creating the draw context. */
    if (!scene_is_window_active(wm, tile.scene)) {
      if (DEG_id_type_any_updated(depsgraph) || !tile.has_render ||
          DEG_get_update_count(depsgraph) == 0)
      {
        BKE_scene_graph_update_tagged(depsgraph, bmain);
      }
    }

    const uint64_t update_count = DEG_get_update_count(depsgraph);
    if (update_count != tile.last_update_count) {
      tile.last_update_count = update_count;
      tile.dirty = true;
    }

    if (tile.dirty || !tile.has_render) {
      any_pending = true;
    }
  }

  /* Dirty tiles only render during a draw — make sure one follows. Without
   * this the region can sit on a stale frame until some unrelated event
   * happens to redraw it. */
  if (any_pending || badge_flipped) {
    ED_region_tag_redraw(region);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Region Type Registration
 * \{ */

static bool agent_strip_region_poll(const RegionPollParams *params)
{
  /* The strip shows every scene but the window-active one, so it exists
   * exactly when the file has more than one scene. Polls run every
   * event-loop cycle, which keeps the region in sync with scenes that
   * agents add or remove without any notifier. */
  const Main *bmain = CTX_data_main(params->context);
  return BLI_listbase_count_at_most(&bmain->scenes, 2) > 1;
}

static void *agent_strip_region_duplicate(void * /*poin*/)
{
  /* Runtime is per-region; copies (area split/duplicate) start fresh. */
  return nullptr;
}

void view3d_agent_strip_region_register(SpaceType *st)
{
  /* Agent strip: fully custom GPU drawing — no ED_KEYMAP_UI, its
   * ui_region_handler could consume LEFTMOUSE before our keymap (same
   * reasoning as the Mixie Chat main region). */
  ARegionType *art = MEM_new_zeroed<ARegionType>("spacetype view3d agent strip region");
  art->regionid = RGN_TYPE_EXECUTE;
  art->prefsizey = AGENT_STRIP_PREFSIZEY;
  art->keymapflag = 0;
  art->poll = agent_strip_region_poll;
  art->init = view3d_agent_strip_region_init;
  art->exit = view3d_agent_strip_region_exit;
  art->draw = view3d_agent_strip_region_draw;
  art->free = agent_strip_region_free;
  art->duplicate = agent_strip_region_duplicate;
  BLI_addhead(&st->regiontypes, art);
}

/** \} */
}  // namespace blender
