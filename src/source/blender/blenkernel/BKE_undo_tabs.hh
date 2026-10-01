/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

/** \file
 * \ingroup bke
 *
 * Mixar: per-tab undo (design M1).
 *
 * A scene tab is a Blender Scene with its own chat session; worker lanes are
 * throwaway scenes tagged ``agentlane:*`` that belong to a tab. Every undo
 * step is tagged with the tab whose scene the window showed when the step
 * was pushed, and every memfile step carries an *owner map*: each ID's
 * ``session_uid`` -> the tab that reaches it. A datablock reachable from two
 * tabs is SHARED; one reachable from no tab is GLOBAL (absent from the map).
 *
 * M1 only records and exposes this (Undo History filtered per tab, a JSON
 * view for the harness); the restore is unchanged until M2.
 */

#include <cstdint>
#include <string>

#include "BLI_span.hh"

struct bContext;
struct ID;
struct Main;
struct Scene;
struct UndoStack;
struct UndoStep;
struct wmWindowManager;

namespace blender {

/** Tab id of a step pushed with no window (file load, internal pushes). */
constexpr uint32_t UNDO_TAB_DOCUMENT = 0u;
/** Owner value of an ID reachable from two or more tabs. */
constexpr uint32_t UNDO_TAB_SHARED = 0xFFFFFFFFu;
/** Owner value of an ID only a worker lane reaches (the lane scene itself and
 * what no tab reaches through it). A tab's walk never restores one: it keeps a
 * live lane as it is and never brings back a lane that is gone (a lane alive
 * when a step was written would otherwise come back on an undo onto that step,
 * with no run to own it; review 2026-10-01, R11). */
constexpr uint32_t UNDO_TAB_LANE = 0xFFFFFFFEu;
/** Design M3: the step limit keeps at least this many of a tab's own steps
 * (of those that exist) and never frees a tab's cursor step. */
constexpr int UNDO_TAB_MIN_STEPS = 8;

/** M5: per-tab undo is ON by default. ``MIXAR_PER_TAB_UNDO=0`` (or ``false`` /
 * ``off``) in the environment turns it off for the session, and the chat
 * module's config key ``per_tab_undo: false`` does the same at startup through
 * #BKE_undo_tabs_set_enabled (``WindowManager.mixar_per_tab_undo``). Gates the
 * tab walk, the hold, the history filter and the owner-map build; tags are
 * always recorded. */
bool BKE_undo_tabs_enabled();
/** The runtime kill switch. Turning it off forgets every tab's cursor; the
 * next document-wide walk re-reads every ID (see #BKE_undo_tabs_live_diverged). */
void BKE_undo_tabs_set_enabled(bool enabled);

/** M5: after a tab walk the live document is no longer the state of the
 * stack's active step, until the next push encodes it again. A document-wide
 * walk in that window must re-read every ID: the reader's identical-chunk
 * shortcut compares adjacent steps against a live document it assumes to be
 * the active step's. */
void BKE_undo_tabs_note_tab_walk();
void BKE_undo_tabs_note_push();
bool BKE_undo_tabs_live_diverged();
/** M5: the walk that ran last was document-wide (Undo Whole Document, or the
 * classic undo with the flag off) rather than one tab's. The chat module's
 * document epoch reads it (``WindowManager.mixar_last_undo_document``) to bump
 * one scene's epoch or every scene's. */
void BKE_undo_tabs_note_document_walk();
bool BKE_undo_tabs_last_walk_was_document();

/** True for a worker lane scene (``mixie_session_id`` starts with ``agentlane:``). */
bool BKE_undo_tab_scene_is_lane(const Scene *scene);

/** The tab a scene belongs to: its own ``session_uid`` for a real tab, the
 * parent tab's for a lane (``mixar_workspace_main_session`` resolved against
 * the scenes' ``mixie_session_id``), #UNDO_TAB_DOCUMENT when unresolved. */
uint32_t BKE_undo_tab_uid_for_scene(Main *bmain, Scene *scene);

/** The tab of the context's window scene, #UNDO_TAB_DOCUMENT without a window. */
uint32_t BKE_undo_tab_uid_from_context(bContext *C);

/* M4: the hold. A tab whose own agent is mid-turn or holds an open backend
 * run refuses undo, redo and the history in its window: the undo operators'
 * own poll reads the scene's run flags, so the refusal holds with no modal,
 * no viewport lock and through menu search. The flags are the chat module's
 * Python-registered Scene properties, read here as IDProperties:
 * ``mixie_run_open`` (bool) and ``mixie_chat_state`` (enum, stored as the
 * item index of ``SESSION_STATE_ITEMS``: OFFLINE 0, CONNECTING 1, IDLE 2,
 * BUSY 3, MODIFYING 4, AWAITING_INPUT 5; pinned by
 * ``tests/test_undo_hold_state_indices.py``). */
constexpr int UNDO_TAB_STATE_BUSY = 3;
constexpr int UNDO_TAB_STATE_MODIFYING = 4;
constexpr int UNDO_TAB_STATE_AWAITING_INPUT = 5;
bool BKE_undo_tab_scene_is_working(const Scene *scene);
/** Any real tab working (lanes are credited to their tab). */
bool BKE_undo_tab_any_working(Main *bmain);
/** The scene name of a tab, empty when no scene has that ``session_uid``. */
std::string BKE_undo_tab_scene_name(Main *bmain, uint32_t tab_uid);

/** Opaque: ``session_uid -> tab_uid`` for every ID reachable from a tab, plus
 * the names of the shared ones (for messages and the harness). */
struct UndoOwnerMap;

/** Walk every scene of ``bmain`` and build the map. ``r_ms`` receives the
 * build time in milliseconds when not null. Never returns null. */
UndoOwnerMap *BKE_undo_owner_map_build(Main *bmain, double *r_ms);
void BKE_undo_owner_map_free(UndoOwnerMap *map);
/** #UNDO_TAB_DOCUMENT when the ID is in no tab (global). */
uint32_t BKE_undo_owner_map_lookup(const UndoOwnerMap *map, uint32_t session_uid);
int BKE_undo_owner_map_size(const UndoOwnerMap *map);
int BKE_undo_owner_map_shared_count(const UndoOwnerMap *map);

/** An explicit tab for the next pushes, for pushes made on behalf of a tab
 * from a context whose window shows another (the agent executor's checkpoints
 * land from timers). Set before #ED_undo_push, cleared with 0 after it. */
void BKE_undo_tabs_push_override_set(uint32_t tab_uid);

/** Tag a freshly pushed step and, for a memfile step under the flag, attach
 * its owner map. ``C`` may lack a window (internal pushes): the tab is then
 * inherited from ``inherit_from`` when given. */
void BKE_undo_step_tab_annotate(UndoStep *us, bContext *C, Main *bmain, const UndoStep *inherit_from);
/** Free what #BKE_undo_step_tab_annotate attached. */
void BKE_undo_step_tab_free(UndoStep *us);

/* -------------------------------------------------------------------- */
/* Partial restore (design M2).
 *
 * A per-tab undo restores ONE tab from a memfile step: IDs that tab owns are
 * read as today, everything else keeps its live datablock, whatever the
 * memfile says. The reader consults this process-wide state (undo is main
 * thread only) instead of new fields on the upstream read parameters. */

enum class UndoPartialDecision : int8_t {
  /** Not partial, or the tab's own ID: the reader's normal undo paths. */
  Restore = 0,
  /** Another tab's, global or shared: keep the live datablock as-is. */
  Keep = 1,
  /** In the memfile, not live, not the tab's: do not read it at all. */
  Skip = 2,
};

/** Arm a partial restore of ``tab_uid`` from a step whose owner map is
 * ``step_owners`` (null, a step written with per-tab undo off, refuses). The
 * live map is built here from ``bmain``. Returns false, with their names in
 * ``r_reason``, when a LOCAL datablock this tab reaches is shared with another
 * tab in either map (a restore would change the other tab's), or when one
 * moved between tabs since the step: ownership fails closed. What two other
 * tabs share, a library-linked datablock, or a type memfile undo never
 * writes (a Brush) refuses nothing. */
bool BKE_undo_tabs_partial_begin(Main *bmain,
                                 uint32_t tab_uid,
                                 const UndoOwnerMap *step_owners,
                                 std::string *r_reason);
/** The validation #BKE_undo_tabs_partial_begin performs, without arming: false
 * (and the reason) when the restore would be refused. */
bool BKE_undo_tabs_partial_check(Main *bmain,
                                 uint32_t tab_uid,
                                 const UndoOwnerMap *step_owners,
                                 std::string *r_reason);
void BKE_undo_tabs_partial_end();
/** M4: arm a WHOLE-document restore (Edit > Undo Whole Document). After per-tab
 * walks the live document is no longer the state of the stack's active step, so
 * the reader's identical-chunk shortcut (adjacent steps only) cannot be trusted
 * for any tab: every ID is re-read, in place where it still lives. Ended by
 * #BKE_undo_tabs_partial_end; #BKE_undo_tabs_partial_tab is #UNDO_TAB_DOCUMENT. */
void BKE_undo_tabs_whole_document_begin();
bool BKE_undo_tabs_partial_active();
uint32_t BKE_undo_tabs_partial_tab();
/** The reader's per-ID question. ``has_live`` = a datablock with that
 * session_uid exists in the old Main. */
UndoPartialDecision BKE_undo_tabs_partial_decide(uint32_t session_uid, bool has_live);

/** M3: true when every ID is the tab's own in the live document (a Scene: its
 * own tab) or global (reachable from no tab: a Text, a Brush, orphan data; M5).
 * A mode step (edit mesh, sculpt, paint, text) names the datablocks it touches;
 * the tab walk applies it unless one belongs to another tab or is shared.
 * Names the offending one in ``r_reason``. */
bool BKE_undo_tabs_ids_owned(Main *bmain, uint32_t tab_uid, Span<ID *> ids, std::string *r_reason);

/** JSON array of the stack's steps, newest first, for the harness:
 * index (stack index, oldest = 0), name, type, tab_uid, skip, active, cursor
 * (the current tab's cursor step), memfile, owners, shared, shared_names,
 * owner_map_ms; current_tab is the window scene's tab. */
std::string BKE_undo_tabs_history_json(const wmWindowManager *wm);

}  // namespace blender
