/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * Parallel Agents panel: a right-docked 3D viewport region that slides in
 * with one card per agent of the running turn — the agent's name (derived
 * from the task it was assigned), its status and its elapsed clock. Three
 * cards are visible at a time; a longer fan-out scrolls.
 *
 * Successor of the Agent Scene Strip, which docked at the bottom and showed
 * an offscreen-rendered tile per non-active scene. Parallel agents no longer
 * get a scene each (the backend's `Task.scene_session_id` exists but is
 * unassigned), so tiles had nothing to preview: the surface is now driven by
 * the turn's task list instead.
 *
 * The card data is a read-only projection of the WindowManager mirror that
 * `mixar/modules/agent_panel/core/cards.py` writes from the chat's `todo`
 * slot. All runtime state (scroll, reveal animation, hit rects) is
 * runtime-only — never written to .blend files.
 */

#pragma once

#include "BLI_rect.h"
#include "BLI_vector.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

struct ARegion;
struct Main;
struct ScrArea;
struct SpaceType;
struct bContext;
struct wmKeyConfig;
struct wmTimer;
struct wmRegionListenerParams;
struct wmSpaceTypeListenerParams;
struct wmWindowManager;

/* -------------------------------------------------------------------- */
/** \name String Buffers
 *
 * Each buffer is strictly larger than the `maxlen` its Python property
 * declares in `agent_panel/constants.py`: `bpy.props.StringProperty(maxlen=N)`
 * registers maxlength N + 1, so a `char[N]` is an off-by-one on read. Reads go
 * through `agent_panel_read_string` (RNA_property_string_get is unbounded).
 * \{ */

#define AGENT_PANEL_TASK_ID_BUF 80  /* AGENT_TASK_ID_MAXLEN 64 */
#define AGENT_PANEL_NAME_BUF 112    /* AGENT_NAME_MAXLEN 96 */
#define AGENT_PANEL_TASK_BUF 288    /* AGENT_TASK_MAXLEN 256 */

/** \} */

/* -------------------------------------------------------------------- */
/** \name Metrics
 *
 * Unscaled UI units; every consumer multiplies by `UI_SCALE_FAC`. Fixed pixel
 * metrics clip their labels on high-DPI displays (same finding as the
 * moodboard node toolbar).
 * \{ */

/** Region height, `ARegionType.prefsizey`.
 *
 * The panel is a BOTTOM-aligned overlapping region whose cards are drawn at
 * its left, NOT a left-aligned one. Blender STACKS overlapping regions that
 * share an edge instead of letting them overlap each other, so a left-docked
 * panel pushes the tool shelf bodily out into the viewport. Tall enough for
 * the visible cards, the chevron and the margins. */
#define AGENT_PANEL_PREFSIZEY 200
/** Card pill: width and height. */
#define AGENT_PANEL_CARD_WIDTH 320
#define AGENT_PANEL_CARD_HEIGHT 40
/** Vertical gap between cards. */
#define AGENT_PANEL_CARD_GAP 8
/** Inset from the region's left edge and from the bottom of the viewport. */
#define AGENT_PANEL_MARGIN_LEFT 24
#define AGENT_PANEL_MARGIN_BOTTOM 14
/** Corner radius of a card pill. */
#define AGENT_PANEL_CARD_RADIUS 12

/** Avatar disc: diameter, and its inset from the card's left edge. */
#define AGENT_PANEL_AVATAR_SIZE 26
#define AGENT_PANEL_AVATAR_INSET 7

/** Right-hand glyph buttons: box size, gap between them, inset from the
 * card's right edge. */
#define AGENT_PANEL_ICON_SIZE 16
#define AGENT_PANEL_ICON_GAP 8
#define AGENT_PANEL_ICON_INSET 10

/** The "more agents" chevron below the stack. */
#define AGENT_PANEL_CHEVRON_WIDTH 38
#define AGENT_PANEL_CHEVRON_HEIGHT 22
#define AGENT_PANEL_CHEVRON_GAP 8

/** Cards visible before the column scrolls. Mirrors `VISIBLE_CARDS` in
 * `agent_panel/constants.py`. */
#define AGENT_PANEL_VISIBLE_CARDS 3

/** How long a finished card stays before it slides out, and how long the
 * slide takes.
 *
 * **Duplicated in `agent_panel/constants.py` (`DONE_CARD_DWELL_S` /
 * `DONE_CARD_EXIT_S`) and must agree.** Python owns WHEN the card leaves the
 * mirror; this half owns the animation, timed from the panel's own first
 * sighting of the DONE status — the two clocks share no epoch, so they are
 * never compared, only given matching durations. If this half outlasts the
 * Python one the card vanishes mid-slide. */
#define AGENT_PANEL_DONE_DWELL_SECONDS 1.2
#define AGENT_PANEL_EXIT_SECONDS 0.35

/** Seconds the slide-in takes, and the per-card stagger within it. Slow
 * enough to read as an arrival rather than a pop — the cards appear at the
 * moment a turn fans out, which is exactly when the user is looking. */
#define AGENT_PANEL_REVEAL_SECONDS 0.55
#define AGENT_PANEL_STAGGER_SECONDS 0.12

/** Animation tick while the panel is settling. Runs at display cadence, not
 * at a lazy poll rate: this timer is the ONLY thing that repaints an
 * animating panel (see `agent_panel_region_listener`), so its interval IS the
 * animation's frame rate. It exists only while something is moving. */
#define AGENT_PANEL_TICK_INTERVAL (1.0 / 60.0)

/** One wheel notch, in unscaled UI units. */
#define AGENT_PANEL_SCROLL_STEP 36

/** \} */

/* -------------------------------------------------------------------- */
/** \name Runtime Types
 * \{ */

enum class AgentCardStatus {
  Pending = 0,
  Running = 1,
  Done = 2,
  Failed = 3,
};

struct AgentPanelCard {
  char task_id[AGENT_PANEL_TASK_ID_BUF] = {};
  char name[AGENT_PANEL_NAME_BUF] = {};
  char task[AGENT_PANEL_TASK_BUF] = {};

  AgentCardStatus status = AgentCardStatus::Pending;

  /** Python-clock readings. Only ever used as the DIFFERENCE `ended - started`:
   * `time.monotonic()` and `BLI_time_now_seconds()` need not share an epoch, so
   * comparing one against the other would print nonsense. A duration inside one
   * clock is valid across both. */
  float started_at = 0.0f;
  float ended_at = 0.0f;

  /** True while the user's dismissal is playing out — the mirror's own
   * `dismissing` flag. The row is removed only once the card has left, so a
   * click never makes it vanish from under the cursor. */
  bool dismissing = false;

  /** `BLI_time_now_seconds()` when this card was first SEEN leaving (finished,
   * or dismissed), carried across syncs by `task_id`. Drives the slide-out.
   * Zero while the card is staying: a FAILED card never leaves on its own,
   * since a failure is the one thing here the user may still need to act on. */
  double seen_exit_at = 0.0;

  /** `BLI_time_now_seconds()` when this card was first SEEN running, carried
   * across syncs by `task_id`. The live elapsed clock counts from here — which
   * is when the client learned the agent started, and so what the user saw. */
  double seen_running_at = 0.0;

  /** True while the eye has this card showing its full task instead of the
   * short agent name. Pure view state: carried across syncs by `task_id`,
   * never mirrored back to Python. */
  bool expanded = false;

  /** Region-local pixel rects. Written by the layout pass, read by draw, the
   * hit test and the QA target provider — one owner, three readers. */
  rcti rect = {};
  /** The eye button: expands the card to show the full task. */
  rcti eye_rect = {};
  /** The right-hand slot: a dismiss cross while the agent works, the outcome
   * glyph once it has settled. */
  rcti action_rect = {};
};

struct AgentPanelRuntime {
  blender::Vector<AgentPanelCard> cards;

  /** Scroll offset in region pixels, clamped to [0, scroll_max]. */
  float scroll = 0.0f;
  float scroll_max = 0.0f;

  /** The "more agents" chevron's rect, empty while the stack fits. */
  rcti chevron_rect = {};

  /** Slide-in progress, 0 (off-screen left) to 1 (docked). Restarted when a
   * NEW fan-out arrives — see `view3d_agent_panel_cards_sync`. */
  double reveal_started_at = 0.0;

  /** `wm.mixar_agent_cards_generation` as of the last sync. Python bumps it
   * for every new fan-out; a change resets the scroll and replays the
   * slide-in. This cannot be inferred here: `cards_sync` runs only from the
   * region draw and draw does not run while the panel is poll-hidden, so
   * between turns `cards` still holds the PREVIOUS turn's entries. */
  int generation = -1;

  /** The card column's clipping rect, region-local pixels. Written by the
   * layout pass beside the card rects, and the ONE definition of "visible":
   * draw scissors to it, the hit test rejects outside it, and the QA target
   * provider skips what it excludes. `region->winy` is the whole area height
   * on a right dock, so culling against the region instead would paint every
   * card of a long fan-out and make the scroll pointless. */
  rcti column_rect = {};

  /** Periodic TIMERNOTIFIER driving the reveal animation and the elapsed
   * clocks. Owned here; removed in the region exit callback. */
  wmTimer *tick_timer = nullptr;
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name view3d_agent_panel_cards.cc
 * \{ */

/** Register the panel's `RGN_TYPE_EXECUTE` region type on the View3D space. */
void view3d_agent_panel_region_register(SpaceType *st);

AgentPanelRuntime *view3d_agent_panel_runtime_ensure(ARegion *region);

/** The panel region of `area`, or null (also for non-View3D areas). */
ARegion *view3d_agent_panel_region_find(const ScrArea *area);

/** Panel additions to the View3D space listener.
 *
 * The panel region is POLL-driven, and region polls only re-run on a screen
 * refresh — a redraw tag is not one. Without this the panel does not appear
 * when a turn fans out (nor close when the cards are cleared) until some
 * unrelated edit happens to refresh the screen. The mirror's RNA writes emit
 * `NC_WINDOW`, which is what this turns into a refresh. */
void view3d_agent_panel_space_listener(const wmSpaceTypeListenerParams *params);

/** Cards the panel should show, read from `wm.mixar_agent_cards_active`.
 * A single property read: the region poll calls it every event-loop cycle. */
int view3d_agent_panel_card_count(const bContext *C);

/** Rebuild `runtime->cards` from the WindowManager mirror, preserving the
 * `seen_running_at` clock of cards still present. */
void view3d_agent_panel_cards_sync(const bContext *C, AgentPanelRuntime *runtime);

/** Recompute `card->rect` for every card: one top-down column, offset by the
 * scroll position and the reveal animation. Also updates `column_rect` and
 * `scroll_max`, and re-clamps `scroll` against it. */
void view3d_agent_panel_layout_cards(const ARegion *region, AgentPanelRuntime *runtime);

/** True while `rect` has any part inside the clipped card column. */
bool view3d_agent_panel_card_visible(const AgentPanelRuntime *runtime, const rcti &rect);

enum class AgentPanelHit {
  None = 0,
  /** The card body — no action, but the click is consumed rather than
   * falling through to the viewport behind the pill. */
  Card,
  /** The eye: swap the card between its agent name and its full task. */
  Eye,
  /** The right-hand slot: dismiss this card. */
  Action,
  /** The "more agents" chevron below the stack. */
  Chevron,
};

/** What is under `mval`. `r_card_index` is set for card hits only. */
AgentPanelHit view3d_agent_panel_hit_test(AgentPanelRuntime *runtime,
                                          const int mval[2],
                                          int *r_card_index);

/** Slide-out progress of a finished card, 0 (still docked) to 1 (gone). */
float view3d_agent_panel_exit_progress(const AgentPanelCard &card);

/** Reveal progress, 0..1, of the whole panel (`card_index` < 0) or of one
 * staggered card. */
float view3d_agent_panel_reveal(const AgentPanelRuntime *runtime, int card_index);

/** True while the panel still needs per-frame updates (sliding in, or an
 * agent is running and its clock is ticking). */
bool view3d_agent_panel_is_animating(const AgentPanelRuntime *runtime);

void view3d_agent_panel_tick_timer_ensure(const bContext *C, AgentPanelRuntime *runtime);
void view3d_agent_panel_tick_timer_remove(wmWindowManager *wm, AgentPanelRuntime *runtime);

/** \} */

/* -------------------------------------------------------------------- */
/** \name view3d_agent_panel_draw.cc
 * \{ */

void view3d_agent_panel_region_init(wmWindowManager *wm, ARegion *region);
void view3d_agent_panel_region_exit(wmWindowManager *wm, ARegion *region);
void view3d_agent_panel_region_draw(const bContext *C, ARegion *region);

/** \} */

/* -------------------------------------------------------------------- */
/** \name view3d_agent_panel_glyphs.cc
 * \{ */

void view3d_agent_panel_draw_disc(float cx, float cy, float radius, const float color[4]);
void view3d_agent_panel_glyph_line(
    float x1, float y1, float x2, float y2, float width, const float color[4]);
void view3d_agent_panel_glyph_eye(const rcti &box, float scale, const float color[4]);
void view3d_agent_panel_glyph_cross(const rcti &box, float scale, const float color[4]);
void view3d_agent_panel_glyph_check(const rcti &box, float scale, const float color[4]);
void view3d_agent_panel_glyph_chevrons_down(const rcti &box, float scale, const float color[4]);

/** The Mixar mark on a card's avatar disc. Falls back to the brand gradient
 * when the bundled logo can't be loaded. */
void view3d_agent_panel_draw_mark(
    float cx, float cy, float radius, const float tint_a[4], const float tint_b[4]);

/** Release the cached logo image. Called from the region exit callback, so
 * the bundled PNG is not held for the life of the process. */
void view3d_agent_panel_mark_free();

/** \} */

/* -------------------------------------------------------------------- */
/** \name view3d_agent_panel_ops.cc
 * \{ */

/** Register the panel operators. Called with the other View3D operator types
 * (region-level `operatortypes` callbacks are never invoked). */
void view3d_agent_panel_operatortypes();

/** `ARegionType.keymap` callback: wheel scrolling. The bindings that actually
 * survive a GUI keyconfig preset reload live in the ADDON keyconfig
 * (`agent_panel/ui/keymap.py`); this populates the default config. */
void view3d_agent_panel_keymap(wmKeyConfig *keyconf);

/** \} */

/* -------------------------------------------------------------------- */
/** \name view3d_agent_panel_qa.cc
 * \{ */

void view3d_agent_panel_qa_targets_register();

/** \} */

}  // namespace blender
