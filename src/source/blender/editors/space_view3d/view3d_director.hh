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

constexpr int VIEW3D_DIRECTOR_TIMELINE_HEIGHT = 164;

struct DirectorBeatView {
  int frame = 0;
  int index = 0;
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
  bool auto_key = false;
  /** Ruler labels time in minutes (`ruler_unit == MIN`) rather than seconds. */
  bool ruler_minutes = false;
  int active_beat_index = 0;
  int frame_current = 0;
  int frame_start = 0;
  int frame_end = 0;
  int scene_frame_start = 0;
  float fps = 24.0f;
  const void *shot_identity = nullptr;
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

/**
 * Aerial map teardown for the WINDOW region's `ARegionType.free`
 * (view3d_director_minimap.cc): frees the map's GPU buffers when \a region
 * is the one that last drew it. Runs outside drawing, so it borrows the
 * draw-manager context the way the agent strip's region free does.
 */
void view3d_director_minimap_region_free(ARegion *region);
}  // namespace blender
