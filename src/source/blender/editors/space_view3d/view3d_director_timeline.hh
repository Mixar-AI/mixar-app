/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Runtime-only viewport and hit geometry for the Director timeline.
 */

#pragma once

#include "BLI_rect.h"
#include "BLI_vector.hh"

#include "view3d_director.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;
struct bContext;
struct wmWindowManager;

struct DirectorTimelineBeatHit {
  rctf bounds = {};
  int index = -1;
};

struct DirectorTimelineRuntime {
  bool view_initialized = false;
  bool view_user_modified = false;
  const void *shot_identity = nullptr;
  int content_first = 0;
  int content_last = 0;
  int content_count = 0;
  float view_start_frame = 0.0f;
  float view_span_frames = 1.0f;
  rctf viewport_bounds = {};
  rctf strip_bounds = {};
  blender::Vector<DirectorTimelineBeatHit> beat_hits;
  bool strip_hovered = false;
  int hovered_beat = -1;
};

DirectorTimelineRuntime *view3d_director_timeline_runtime_ensure(ARegion *region);

void view3d_director_timeline_region_init(wmWindowManager *wm, ARegion *region);
void view3d_director_timeline_region_free(ARegion *region);
void *view3d_director_timeline_region_duplicate(void *regiondata);

void view3d_director_timeline_draw_content(const ARegion *region,
                                           const DirectorViewState &state,
                                           DirectorTimelineRuntime *runtime,
                                           int margin,
                                           int unit,
                                           int content_top);
}  // namespace blender
