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
struct Object;
struct bContext;
struct wmEvent;
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
  /** The ruler row under the strip — the ONLY band that scrubs. Dragging
   * anywhere else in the viewport box-selects, the way the Dope Sheet
   * divides its own region. */
  rctf ruler_bounds = {};
  /** What the playhead ACTUALLY drew this frame — the line's grab band and
   * its frame pill — so grabbing the tick resolves against the paint rather
   * than against a second copy of the same arithmetic. Both are left empty
   * (xmin > xmax) while the playhead is off screen. */
  rctf playhead_line = {1.0f, -1.0f, 1.0f, -1.0f};
  rctf playhead_pill = {1.0f, -1.0f, 1.0f, -1.0f};
  blender::Vector<DirectorTimelineBeatHit> beat_hits;
  bool strip_hovered = false;
  int hovered_beat = -1;
  /** Middle-mouse pan, the way every other Blender editor pans. The view
   * lives here rather than in RNA, so the drag is tracked here too instead
   * of in a Python modal that could not reach it. */
  bool panning = false;
  int pan_anchor_x = 0;
  float pan_anchor_frame = 0.0f;
  /** Selected beat indices. View state — the .blend must not carry it — and
   * it lives beside the hit rects it refers to. Cleared whenever the shot or
   * the beat count changes, since an index means nothing across either. */
  blender::Vector<int> selected;
  /** Box select: armed by B, dragging between the press and the release. */
  bool box_arming = false;
  bool box_dragging = false;
  bool box_extend = false;
  int box_start[2] = {0, 0};
  int box_end[2] = {0, 0};
};

/** \name Selection (view3d_director_timeline_select.cc)
 * \{ */

bool director_timeline_is_selected(const DirectorTimelineRuntime &runtime, int index);

/** Drop a selection that no longer means anything (shot or count changed). */
void director_timeline_selection_sync(DirectorTimelineRuntime *runtime,
                                      const void *shot_identity,
                                      int beat_count);

/**
 * Handle a selection gesture. Returns true when the event was consumed.
 *
 * Owns: click and Shift+click on a handle, B-armed box select, A / Alt+A, and
 * the multi-beat drag and delete dispatched from a selection.
 */
bool director_timeline_selection_event(bContext *C,
                                       ARegion *region,
                                       const DirectorViewState &state,
                                       DirectorTimelineRuntime *runtime,
                                       const wmEvent *event,
                                       int hovered_beat);

/**
 * The dock's current keyframe selection, for surfaces that are not the dock.
 *
 * The Interpolation chip and its popup both need it, and neither draws in the
 * dock's region — the popup has a temporary region of its own. Finds the
 * dock through the area and reads its runtime without allocating one.
 * False (and an empty vector) when nothing is selected.
 */
bool view3d_director_timeline_selection(const bContext *C, blender::Vector<int> *r_selected);

/** The armed box, in region px, while one is being dragged. */
bool director_timeline_box_rect(const DirectorTimelineRuntime &runtime, rctf *r_rect);

/** Start a box select at \a event; the running drag is owned by
 * #director_timeline_selection_event from the next event onwards. */
void director_timeline_box_begin(DirectorTimelineRuntime *runtime, const wmEvent *event);

/** \} */

DirectorTimelineRuntime *view3d_director_timeline_runtime_ensure(ARegion *region);

void view3d_director_timeline_region_init(wmWindowManager *wm, ARegion *region);
void view3d_director_timeline_region_free(ARegion *region);
void *view3d_director_timeline_region_duplicate(void *regiondata);

/** The camera strip, and the height below which it stops reading as a row. */
constexpr float DIRECTOR_STRIP_H = 32.0f;
constexpr float DIRECTOR_STRIP_MIN_H = 18.0f;
/** The playhead's frame pill: its own band at the top of the dock. */
constexpr float DIRECTOR_PLAYHEAD_PILL_H = 25.0f;
/** Clear space between that band and the keyframe strip below it. */
constexpr float DIRECTOR_PLAYHEAD_PILL_GAP = 6.0f;
/** The ruler's major tick, and the clear space from its top to the label
 * baseline. The ruler draws them and the layout reserves them, so they are
 * one pair of tokens rather than a literal in each file. */
constexpr float DIRECTOR_RULER_TICK_H = 20.0f;
constexpr float DIRECTOR_RULER_LABEL_GAP = 8.0f;

/* -------------------------------------------------------------------- */
/** \name Shared paint primitives (view3d_director_timeline_draw.cc)
 *
 * The dock draws in two translation units — `_draw.cc` paints the strip and
 * its keyframes, `_ruler.cc` the ruler and the playhead — and both need
 * these. Declared here so neither grows a second copy that can drift.
 * \{ */

void director_timeline_draw_rect(float x1, float y1, float x2, float y2, const float color[4]);
void director_timeline_draw_round_rect(const rctf &rect, float radius, const float color[4]);

/**
 * The shot camera's native keys on the strip row centred on \a cy, drawn the
 * way the Timeline draws them (`view3d_director_timeline_keys.cc`): Blender's
 * keylist and keyframe shader, placed with the dock's frame->pixel mapping.
 * View-only marks under the beat handles. No-op without a camera.
 */
void director_timeline_draw_native_keys(Object *camera,
                                        const DirectorTimelineRuntime &runtime,
                                        const ARegion *region,
                                        float cy);
void director_timeline_draw_text(
    const char *text, float x, float y, float size, const float color[4]);
float director_timeline_text_width(const char *text, float size);

/** \} */

/** Ruler ticks and labels, in the unit the dock's chips select. */
void director_timeline_draw_ruler(const DirectorViewState &state,
                                  const DirectorTimelineRuntime &runtime,
                                  float tick_base);

/**
 * Dim everything outside the scene's frame range
 * (view3d_director_timeline_ruler.cc).
 *
 * Painted OVER the finished stack between \a bottom and \a top rather than
 * under it: the in-range stretch is the part that plays and renders, and one
 * scrim dims the ruler, its labels, the strip and the keyframes together —
 * where dimming each layer on its own would mean every layer added later
 * having to remember to.
 */
void director_timeline_draw_range_scrim(const DirectorViewState &state,
                                        const DirectorTimelineRuntime &runtime,
                                        float bottom,
                                        float top);

/** The playhead line and its frame pill (view3d_director_timeline_ruler.cc).
 *
 * Publishes what it drew into \a runtime for #director_timeline_playhead_grab.
 */
void director_timeline_draw_playhead(const DirectorViewState &state,
                                     DirectorTimelineRuntime *runtime,
                                     float bottom,
                                     float top);

/**
 * Is (\a x, \a y) on the playhead — its line or its frame pill?
 *
 * The tick is a handle: grabbing it scrubs from anywhere in the dock, not
 * only from the ruler row. Reads the rects the draw published, never
 * re-derived ones.
 */
bool director_timeline_playhead_grab(const DirectorTimelineRuntime &runtime, float x, float y);

void view3d_director_timeline_draw_content(const ARegion *region,
                                           const DirectorViewState &state,
                                           DirectorTimelineRuntime *runtime,
                                           int margin,
                                           int unit,
                                           int content_top);
}  // namespace blender
