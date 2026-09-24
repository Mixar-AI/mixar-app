/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Native viewport shell for Mixar's sparse camera Director.
 */

#pragma once

#include <string>

#include "BLI_vector.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;
struct Object;
struct PointerRNA;
struct Scene;
struct ScrArea;
struct SpaceType;
struct bContext;
struct wmOperatorType;

/**
 * The dock's height — FIXED, not a preference: the user cannot resize it.
 *
 * It has to hold the whole stack: the dock's control row, the playhead's
 * band, the camera strip, and the ruler's ticks and labels. At 164 it did
 * not — the strip's height is what the layout took the shortfall out of, and
 * it went to ZERO, taking every keyframe on it with it.
 * `tests/director/test_timeline_layout.py` does that arithmetic against the
 * layout's own constants so the budget can never silently collapse again;
 * this is exactly the height at which the strip is whole, with no slack.
 */
constexpr int VIEW3D_DIRECTOR_TIMELINE_HEIGHT = 219;

struct DirectorBeatView {
  int frame = 0;
  int index = 0;
  /** The beat carries a captured still; the dock's badge says so. */
  bool has_still = false;
};

struct DirectorViewState {
  bool available = false;
  bool active = false;
  bool timeline_expanded = true;
  bool has_shot = false;
  bool has_camera = false;
  bool locked = false;
  bool navigate_mode = true;
  bool explore_mode = false;
  /** `navigation_mode == AERIAL`: the main viewport looks down on the scene. */
  bool aerial_mode = false;
  /** Blender's own walk navigation is running; the top strip's hints follow. */
  bool walking = false;
  bool auto_key = false;
  /** A live take is armed: every frame playback passes keys the camera. */
  bool recording = false;
  /** Ruler labels frame numbers (`ruler_unit == FRAMES`) rather than time. */
  bool ruler_frames = false;
  int active_beat_index = 0;
  int frame_current = 0;
  int frame_start = 0;
  int frame_end = 0;
  /* The SCENE's own range. `frame_start` / `frame_end` above collapse onto
   * the beats' span once a shot has any, so the dock keeps the scene's
   * separately — it is what the Start/End fields edit and what the timeline
   * shades as the live stretch. */
  int scene_frame_start = 0;
  int scene_frame_end = 0;
  float fps = 24.0f;
  const void *shot_identity = nullptr;
  /** The active shot's camera, for this draw only: the dock draws its native
   * keys (`view3d_director_timeline_keys.cc`). Null without one. */
  Object *shot_camera = nullptr;
  std::string camera_name = "Camera";
  blender::Vector<DirectorBeatView> beats;
};

/** Read the Python-owned Director PropertyGroups without assuming registration.
 */
bool view3d_director_state_read(Scene *scene, DirectorViewState *r_state);

/** RNA pointer to the Python-owned `scene.mixar_director` state, if any. */
bool view3d_director_state_pointer(Scene *scene, PointerRNA *r_state_ptr);

/** Cheap `is_directing` read for operator polls (no shot/beat walk). */
bool view3d_director_is_directing(Scene *scene);

/** Cheap `navigation_mode` enum index for operator polls (-1 when unavailable). */
int view3d_director_navigation_mode(Scene *scene);

/** Return the active Python-owned shot so native UI can bind its RNA controls.
 */
bool view3d_director_active_shot_pointer(Scene *scene, PointerRNA *r_shot_ptr);

/**
 * The active shot's camera object, or null; `r_locked` reports the take's
 * LOCKED state. Shared by the nudge, the aerial map and its placement modal
 * so every native camera writer resolves the same object the same way.
 */
Object *view3d_director_shot_camera(Scene *scene, bool *r_locked);

/** Overlay controls rendered over an active View3D main region. */
void view3d_director_overlay_draw(const bContext *C, ARegion *region);

/** Register and materialize the poll-driven bottom timeline region. */
void view3d_director_timeline_region_register(SpaceType *st);
void view3d_director_timeline_region_ensure(ScrArea *area);

/* QA harness target provider (view3d_director_qa_targets.cc). */
void view3d_director_qa_targets_register();

/** Native Director operators (view3d_director_nudge.cc): the hold-to-move
 * `MIXAR_OT_director_nudge_camera` behind the W/A/S/D/Q/E hints and the
 * `MIXAR_OT_director_place_camera` behind the aerial map and Aerial mode. Appended from the View3D
 * space-level `operatortypes` callback. */
void view3d_director_operatortypes();

/** Click/drag-to-place modal over the aerial map or the Aerial-mode stage
 * (view3d_director_place_camera.cc). */
void MIXAR_OT_director_place_camera(wmOperatorType *ot);

/** Wheel-scroll the "My Cameras" list (view3d_director_cinema_cameras.cc).
 * Its poll is the card's only hit test: the Cinema surface paints and never
 * hit-tests, so the wheel is scoped by the rect the painter published. */
void MIXAR_OT_director_scroll_cameras(wmOperatorType *ot);
void MIXAR_OT_director_walk(wmOperatorType *ot);

/** Install the Cinema surface's UI handler on a View3D WINDOW region.
 * UI handlers run before every keymap, which is the only way a gesture
 * over a painted card can beat `view3d.zoom`. */
void view3d_director_cinema_region_init(struct ARegion *region);

/**
 * Aerial map teardown for the WINDOW region's `ARegionType.free`
 * (view3d_director_minimap.cc): frees the map's GPU buffers when \a region
 * is the one that last drew it. Runs outside drawing, so it borrows the
 * draw-manager context the way the agent strip's region free does.
 */
void view3d_director_minimap_region_free(ARegion *region);
}  // namespace blender
