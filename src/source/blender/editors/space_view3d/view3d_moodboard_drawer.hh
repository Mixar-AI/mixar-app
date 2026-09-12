/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Sliding moodboard drawer for Zen Mode: the whole Mixar moodboard canvas,
 * hosted in an overlapping region docked to the right edge of the 3D View and
 * slid in and out by a grip on that edge.
 *
 * The TOOL_PROPS region overlaps the viewport and stays available in Zen
 * Mode, including when shut so the grip remains visible. Grip dragging resizes
 * this region from the modal event handler and remembers its width on the
 * WindowManager. It can cover the available area without resizing WINDOW.
 * Layout preserves canvas pixel zoom and the right edge, revealing more of
 * the board as the grip moves left.
 *
 * Click open/close animates the canvas inside that chosen region width:
 * `v2d.cur` is translated and scissored, then its translation is undone. The
 * WindowManager owns amount (0..1), target (0/1), and width in UI units. C owns
 * the wall-clock cubic ease and TIMERNOTIFIER; Python's 60 Hz clock commits
 * the eased amount. Region runtime is disposable on workspace poll-out.
 *
 * Once `amount` is at `VIEW3D_MOODBOARD_DRAWER_CANVAS_MIN_AMOUNT`, the region
 * hosts the Mixie canvas keymap, View2D pan/zoom, and Mixie dropboxes behind
 * a poll, so the open board is the same surface as SPACE_MIXIE. The region
 * type's `keymapflag` stays 0: a shut overlay must not steal viewport pan.
 * View3D `TOOL_PROPS` has no edge azone — the sash would cover the open grip.
 * Event routing uses `view3d_moodboard_drawer_contains_xy`: only the grip and
 * the painted panel slice belong to this region; the scissored remainder is
 * the viewport. The grip keymap is grip-only (no canvas LEFTMOUSE), polled
 * onto the handle, and registered before `ui::region_handlers_add`.
 */

#pragma once

#include "BLI_rect.h"

#include "DNA_space_types.h"

#include "ED_moodboard_drawer.hh"

struct ARegion;
struct ARegionType;
struct ScrArea;
struct SpaceType;
struct bContext;
struct wmEvent;
struct wmKeyConfig;
struct wmWindow;
struct wmWindowManager;

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name State
 * \{ */

/** Rendered drawer amount, 0 (closed) .. 1 (open), read from the Python-owned
 * `wm.mixar_moodboard_drawer_amount`. Returns 0 when the property is missing. */
float view3d_moodboard_drawer_amount(const bContext *C);

/** Write the rendered amount. Does not move the drawer's target, so a caller
 * that wants the value to stick must set the target as well. */
void view3d_moodboard_drawer_amount_set(bContext *C, float amount);

/** Painted / hit-test amount: the wall-clock ease if a slide is running,
 * otherwise the RNA value. Draw and the update operator share this so a
 * late timer tick cannot skip ahead of what the last frame showed. */
float view3d_moodboard_drawer_display_amount(const bContext *C);

/** Start a time-based ease from the current display amount toward `target`.
 * Call *before* flipping the target so the start value is the pixels on
 * screen. */
void view3d_moodboard_drawer_slide_begin(bContext *C);

/** Drop the time-based ease (snap set, escape). */
void view3d_moodboard_drawer_slide_stop(bContext *C);

/** Grip drag: freeze the ease so the update operator cannot tug back. */
void view3d_moodboard_drawer_slide_hold(bContext *C);

/** 1 while the drawer is meant to be open, 0 while it is meant to be shut. */
int view3d_moodboard_drawer_target(const bContext *C);
void view3d_moodboard_drawer_target_set(bContext *C, int target);

/** True while the active workspace is Zen Mode. Gates the region poll, the
 * draw pass and the grip hit test, so nothing is drawn and nothing is
 * clickable outside the mode the drawer belongs to. */
bool view3d_moodboard_drawer_zen_active(const bContext *C);

/** Requested width in UI units, remembered across close/reopen. */
float view3d_moodboard_drawer_width(wmWindowManager *wm);
void view3d_moodboard_drawer_width_set(bContext *C, float width);
void view3d_moodboard_drawer_size_sync(wmWindowManager *wm, ScrArea *area, ARegion *region);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Geometry
 * \{ */

/** The live drawer region for `area`, or null when it is polled out (not Zen
 * Mode, or the area has not been laid out yet). */
ARegion *view3d_moodboard_drawer_region_find(const ScrArea *area);

/** Window-space rect of the grip for the current RNA amount, or false when
 * there is no grip to draw or click. */
bool view3d_moodboard_drawer_grip_rect(const bContext *C, rcti *r_rect);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Region lifecycle
 * \{ */

void view3d_moodboard_drawer_region_init(wmWindowManager *wm, ARegion *region);
void view3d_moodboard_drawer_region_exit(wmWindowManager *wm, ARegion *region);
void view3d_moodboard_drawer_region_draw(const bContext *C, ARegion *region);

/** True once the last drawn amount is high enough that paint and hit-test
 * share an unshifted `v2d`. Used by the Mixie/View2D handler poll. */
bool view3d_moodboard_drawer_canvas_is_active(const ARegion *region);

/** Handler poll: View2D mask plus a settled-open drawer. */
bool view3d_moodboard_drawer_canvas_handler_poll(const wmWindow *win,
                                                const ScrArea *area,
                                                const ARegion *region,
                                                const wmEvent *event);

/** Handler poll: the event is on the grip. Same rect as the operator hit-test. */
bool view3d_moodboard_drawer_grip_handler_poll(const wmWindow *win,
                                              const ScrArea *area,
                                              const ARegion *region,
                                              const wmEvent *event);

/** Register the `RGN_TYPE_TOOL_PROPS` region type on the 3D View space. */
void view3d_moodboard_drawer_region_register(SpaceType *st);

/** Seed the region on an area that predates it (startup files, existing
 * workspaces). Mirrors `view3d_director_timeline_region_ensure()`. */
void view3d_moodboard_drawer_region_ensure(wmWindowManager *wm, ScrArea *area);

/** \} */

/* -------------------------------------------------------------------- */
/** \name Operators, keymap, QA
 * \{ */

/** `view3d.moodboard_drawer_{update,toggle,set,grip}`. */
void view3d_moodboard_drawer_operatortypes();
void view3d_moodboard_drawer_keymap(wmKeyConfig *keyconf);

/** Export the panel and grip as QA harness targets. */
void view3d_moodboard_drawer_qa_targets_register();

/** \} */

}  // namespace blender
