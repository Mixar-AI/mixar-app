/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Shared internals of the Scribble ink overlay (stylus handwriting-to-text
 * for the chat composer), split like the rules/history overlays across:
 *   - mixie_chat_ink_overlay.cc  (canvas + chrome drawing)
 *   - mixie_chat_ink_events.cc   (stroke capture, idle-commit timer, cursor)
 *   - mixie_chat_ink_util.cc     (RNA bridge, stroke store, JSON serialize,
 *                                 commit dispatch, MIXIE_CHAT_OT_ink_flush)
 *
 * Division of labour: C++ owns the pen — stylus detection, live ink capture
 * with pressure, drawing, and WHEN to convert (idle pause / close / Enter).
 * Python owns the data — `mixie_chat.ink_commit` receives the strokes JSON,
 * rasterizes it, calls the backend `/handwriting/recognize` endpoint and
 * appends the recognized text to `scene.mixie_chat_input`
 * (space_mixie_chat/core/scribble.py).
 *
 * Visibility is the Python-registered WindowManager bool
 * `mixie_chat_ink_visible` (same scheme as the rules overlay); the busy
 * indicator reads `mixie_chat_ink_busy` (written by the Python queue).
 */

#pragma once

#include <string>

#include "mixie_chat_history_intern.hh"

struct ARegion;
struct MixieChatRuntime;
struct bContext;
struct wmEvent;
struct wmWindow;
struct wmWindowManager;

/* -------------------------------------------------------------------- */
/** \name Contract Constants (lockstep with Python space_mixie_chat/constants.py)
 * \{ */

/** Byte cap of one serialized strokes payload, incl. terminator. Must stay
 * in lockstep with SCRIBBLE_COMMIT_MAXLEN — worst case is every point slot
 * used at maximum digit width (`[3840,2160,0.88],` ~ 17 bytes x 4096). */
inline constexpr int INK_JSON_MAX = 98304;

/** Idle time after the last pen-up before pending strokes auto-commit for
 * recognition (mirrored informationally as SCRIBBLE_IDLE_COMMIT_MS). */
inline constexpr double INK_IDLE_COMMIT_SEC = 0.85;

/** Idle-commit timer period. Shorter than the idle threshold so a commit
 * fires at most one period late. */
inline constexpr double INK_IDLE_TIMER_STEP = 0.25;

/** \} */

/* -------------------------------------------------------------------- */
/** \name Capture + Draw Constants
 * \{ */

/** Min distance (base px, scaled by UI_SCALE_FAC) between captured samples
 * of a live stroke — decimates high-frequency tablet input so the point
 * store covers several sentences of writing. */
inline constexpr float INK_MIN_SAMPLE_DIST = 1.2f;

/** Ink stroke width (base px). Pressure modulates alpha, not width. */
inline constexpr float INK_STROKE_WIDTH = 2.6f;

/** Hint pill along the top edge of the canvas. */
inline constexpr float INK_HINT_H = 30.0f;
inline constexpr float INK_HINT_PAD_X = 12.0f;
inline constexpr float INK_HINT_GAP = 8.0f;
inline constexpr float INK_BTN_H = 22.0f;
inline constexpr float INK_CLEAR_W = 52.0f;

/** Scrim is lighter than the rules/history overlays: the chat stays
 * readable under the writing surface. */
inline constexpr float INK_COL_SCRIM[4] = {0.02f, 0.03f, 0.04f, 0.30f};

/** \} */

/* -------------------------------------------------------------------- */
/** \name RNA Bridge + Stroke Store (mixie_chat_ink_util.cc)
 * \{ */

bool mixie_chat_ink_read_visible(wmWindowManager *wm);
bool mixie_chat_ink_read_busy(wmWindowManager *wm);
/** True once the deferred Python UI pass registered the ink props. */
bool mixie_chat_ink_feature_available(wmWindowManager *wm);
void mixie_chat_ink_reset_runtime(MixieChatRuntime *rt);

/** Full opening init of the runtime (also used by the event-side auto-open
 * paths, which pre-latch `ink_overlay_active` before the next draw). */
void mixie_chat_ink_begin_session(MixieChatRuntime *rt);

/** Append a new stroke starting at (x, y) with pressure `p`. Returns false
 * when the stroke/point store is full (the stroke is not started). */
bool mixie_chat_ink_stroke_begin(MixieChatRuntime *rt, float x, float y, float p);

/** Extend the live stroke; distance-decimated. No-op when not capturing. */
void mixie_chat_ink_stroke_extend(MixieChatRuntime *rt, float x, float y, float p);

/** Finish the live stroke (drops it again if it never gained a 2nd point
 * AND moved nowhere — single taps still keep their dot). */
void mixie_chat_ink_stroke_end(MixieChatRuntime *rt);

/** Serialize completed strokes to the frozen wire JSON
 * `{"w":..,"h":..,"strokes":[[[x,y,p],..],..]}` (region px, y up). */
std::string mixie_chat_ink_serialize(const MixieChatRuntime *rt, int winx, int winy);

/** Serialize + dispatch `mixie_chat.ink_commit` + clear committed strokes
 * (a live in-progress stroke survives). Safe only from event context. */
void mixie_chat_ink_commit(bContext *C, ARegion *region, MixieChatRuntime *rt);

/** Commit pending ink on EVERY chat surface in every window (the WM-global
 * visibility means all surfaces share one canvas session — a close from one
 * must flush them all). Body of MIXIE_CHAT_OT_ink_flush. */
void mixie_chat_ink_flush_all_surfaces(bContext *C);

/** Idle-commit timer (process-global, like the chat anim pump; rebinds to
 * the window of the most recent pen-up). Removed when the overlay closes
 * and from region exit (window close / file load would leave it dangling). */
void mixie_chat_ink_idle_timer_ensure(bContext *C);
void mixie_chat_ink_idle_timer_remove(wmWindowManager *wm);
bool mixie_chat_ink_idle_timer_matches(const wmEvent *event);

/** \} */
