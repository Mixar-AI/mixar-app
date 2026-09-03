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
struct PointerRNA;
struct Scene;
struct ScrArea;
struct SpaceType;
struct bContext;

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
  bool auto_key = false;
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

/** Return the active Python-owned shot so native UI can bind its RNA controls.
 */
bool view3d_director_active_shot_pointer(Scene *scene, PointerRNA *r_shot_ptr);

/** Overlay controls rendered over an active View3D main region. */
void view3d_director_overlay_draw(const bContext *C, ARegion *region);

/** Register and materialize the poll-driven bottom timeline region. */
void view3d_director_timeline_region_register(SpaceType *st);
void view3d_director_timeline_region_ensure(ScrArea *area);

/* QA harness target provider (view3d_director_qa_targets.cc). */
void view3d_director_qa_targets_register();
}  // namespace blender
