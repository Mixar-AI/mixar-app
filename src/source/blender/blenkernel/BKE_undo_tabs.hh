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

struct bContext;
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

/** ``MIXAR_PER_TAB_UNDO=1`` in the environment (read once). Gates the
 * history filter and the owner-map build; tags are always recorded. */
bool BKE_undo_tabs_enabled();

/** True for a worker lane scene (``mixie_session_id`` starts with ``agentlane:``). */
bool BKE_undo_tab_scene_is_lane(const Scene *scene);

/** The tab a scene belongs to: its own ``session_uid`` for a real tab, the
 * parent tab's for a lane (``mixar_workspace_main_session`` resolved against
 * the scenes' ``mixie_session_id``), #UNDO_TAB_DOCUMENT when unresolved. */
uint32_t BKE_undo_tab_uid_for_scene(Main *bmain, Scene *scene);

/** The tab of the context's window scene, #UNDO_TAB_DOCUMENT without a window. */
uint32_t BKE_undo_tab_uid_from_context(bContext *C);

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

/** Tag a freshly pushed step and, for a memfile step under the flag, attach
 * its owner map. ``C`` may lack a window (internal pushes): the tab is then
 * inherited from ``inherit_from`` when given. */
void BKE_undo_step_tab_annotate(UndoStep *us, bContext *C, Main *bmain, const UndoStep *inherit_from);
/** Free what #BKE_undo_step_tab_annotate attached. */
void BKE_undo_step_tab_free(UndoStep *us);

/** JSON array of the stack's steps, newest first, for the harness:
 * name, type, tab_uid, current (the window scene's tab), skip, active,
 * memfile, owners, shared, shared_names, owner_map_ms. */
std::string BKE_undo_tabs_history_json(const wmWindowManager *wm);

}  // namespace blender
