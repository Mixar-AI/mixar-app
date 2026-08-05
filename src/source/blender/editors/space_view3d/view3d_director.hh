/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Native viewport shell for Mixar's sparse camera Director.
 */

#pragma once

#include "BLI_vector.hh"

struct ARegion;
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
  int version = 1;
  int active_beat_index = 0;
  int frame_current = 0;
  int frame_start = 0;
  int frame_end = 0;
  float fps = 24.0f;
  char shot_name[128] = {};
  char camera_name[128] = {};
  blender::Vector<DirectorBeatView> beats;
};

/** Read the Python-owned Director PropertyGroups without assuming registration.
 */
bool view3d_director_state_read(Scene *scene, DirectorViewState *r_state);

/** Overlay controls rendered over an active View3D main region. */
void view3d_director_overlay_draw(const bContext *C, ARegion *region);

/** Register and materialize the poll-driven bottom timeline region. */
void view3d_director_timeline_region_register(SpaceType *st);
void view3d_director_timeline_region_ensure(ScrArea *area);
