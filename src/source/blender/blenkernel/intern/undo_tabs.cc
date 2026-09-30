/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup bke
 *
 * Mixar: per-tab undo, the tag and the owner map (design M1).
 */

#include <cstdlib>
#include <cstring>
#include <string>

#include "CLG_log.h"

#include "BLI_listbase.h"
#include "BLI_utildefines.h"
#include "BLI_map.hh"
#include "BLI_string.h"
#include "BLI_time.h"
#include "BLI_assert.h"
#include "BLI_vector.hh"

#include "DNA_ID.h"
#include "DNA_scene_types.h"
#include "DNA_windowmanager_types.h"

#include "BKE_context.hh"
#include "BKE_global.hh"
#include "BKE_idprop.hh"
#include "BKE_idtype.hh"
#include "BKE_lib_query.hh"
#include "BKE_main.hh"
#include "BKE_undo_system.hh"
#include "BKE_undo_tabs.hh"
#include "BKE_wm_runtime.hh"

#include "MEM_guardedalloc.h"
#include "undo_tabs_intern.hh"

namespace blender {

static CLG_LogRef LOG = {"undo.tabs"};

/* Python-registered Scene properties (bpy.props on the Mixar side) live in the
 * ID's property group under their RNA names. */
static const char *SCENE_SESSION_PROP = "mixie_session_id";
static const char *LANE_PARENT_PROP = "mixar_workspace_main_session";
static const char *LANE_PREFIX = "agentlane:";

static bool env_disables_per_tab_undo()
{
  const char *env = std::getenv("MIXAR_PER_TAB_UNDO");
  if (env == nullptr || env[0] == '\0') {
    return false;
  }
  return env[0] == '0' || BLI_strcaseeq(env, "false") || BLI_strcaseeq(env, "off") ||
         BLI_strcaseeq(env, "no");
}

static bool g_enabled = !env_disables_per_tab_undo();
static bool g_live_diverged = false;
static bool g_last_walk_document = false;

bool BKE_undo_tabs_enabled()
{
  return g_enabled;
}

void BKE_undo_tabs_set_enabled(const bool enabled)
{
  if (g_enabled == enabled) {
    return;
  }
  g_enabled = enabled;
  CLOG_INFO(&LOG, "per-tab undo %s at runtime", enabled ? "on" : "off");
  if (!enabled && G_MAIN != nullptr) {
    wmWindowManager *wm = static_cast<wmWindowManager *>(G_MAIN->wm.first);
    if (wm != nullptr && wm->runtime != nullptr && wm->runtime->undo_stack != nullptr) {
      BKE_undosys_tab_cursors_clear(wm->runtime->undo_stack);
    }
  }
}

void BKE_undo_tabs_note_tab_walk()
{
  g_live_diverged = true;
  g_last_walk_document = false;
}

void BKE_undo_tabs_note_document_walk()
{
  g_last_walk_document = true;
}

bool BKE_undo_tabs_last_walk_was_document()
{
  return g_last_walk_document;
}

void BKE_undo_tabs_note_push()
{
  g_live_diverged = false;
}

bool BKE_undo_tabs_live_diverged()
{
  return g_live_diverged;
}

/* A `bpy.props` StringProperty on the Scene (the chat module's
 * `mixie_session_id`) lives in `id.system_properties` (Blender 4.3+); a raw
 * custom property (`scene["…"] = …`, what the headless lab writes and what the
 * backend's workspace script stamps) in `id.properties`. Read both: M5's
 * seven-tab soak found the lane mapping dead in the app because only the
 * second store was read. */
static const char *scene_string_prop(const Scene *scene, const char *name)
{
  if (scene == nullptr) {
    return nullptr;
  }
  const IDProperty *stores[2] = {scene->id.system_properties, scene->id.properties};
  for (const IDProperty *group : stores) {
    if (group == nullptr) {
      continue;
    }
    const IDProperty *prop = IDP_GetPropertyTypeFromGroup(group, name, IDP_STRING);
    if (prop == nullptr) {
      continue;
    }
    const char *value = IDP_string_get(prop);
    if (value != nullptr && value[0] != '\0') {
      return value;
    }
  }
  return nullptr;
}

bool BKE_undo_tab_scene_is_lane(const Scene *scene)
{
  const char *session = scene_string_prop(scene, SCENE_SESSION_PROP);
  return session != nullptr && STRPREFIX(session, LANE_PREFIX);
}

static Scene *scene_with_session(Main *bmain, const char *session)
{
  if (bmain == nullptr || session == nullptr) {
    return nullptr;
  }
  for (Scene &scene : bmain->scenes) {
    const char *own = scene_string_prop(&scene, SCENE_SESSION_PROP);
    if (own != nullptr && STREQ(own, session)) {
      return &scene;
    }
  }
  return nullptr;
}

uint32_t BKE_undo_tab_uid_for_scene(Main *bmain, Scene *scene)
{
  if (scene == nullptr) {
    return UNDO_TAB_DOCUMENT;
  }
  if (!BKE_undo_tab_scene_is_lane(scene)) {
    return scene->id.session_uid;
  }
  const Scene *parent = scene_with_session(bmain, scene_string_prop(scene, LANE_PARENT_PROP));
  return parent != nullptr ? parent->id.session_uid : UNDO_TAB_DOCUMENT;
}

/** The scene the active window shows: what a push with no context at all can
 * still be attributed to (a sculpt stroke ends its step with a null context
 * and the stack's active step may be another tab's; an internal memfile push
 * before a mode step belongs with that step). */
static Scene *shown_scene(Main *bmain)
{
  wmWindowManager *wm = (bmain != nullptr) ? static_cast<wmWindowManager *>(bmain->wm.first) :
                                             nullptr;
  if (wm == nullptr) {
    return nullptr;
  }
  wmWindow *win = (wm->runtime != nullptr && wm->runtime->winactive != nullptr) ?
                      wm->runtime->winactive :
                      static_cast<wmWindow *>(wm->windows.first);
  return (win != nullptr) ? win->scene : nullptr;
}

uint32_t BKE_undo_tab_uid_from_context(bContext *C)
{
  if (C == nullptr) {
    /* M5: a push with no context (sculpt's push_end, the kernel's internal
     * memfile pushes) belongs to the shown tab, never to whichever tab pushed
     * last: the seven-tab soak tagged a user's brush stroke with an agent's
     * tab that way, and the tab's undo then took the wrong step back. */
    return BKE_undo_tab_uid_for_scene(G_MAIN, shown_scene(G_MAIN));
  }
  /* The context scene first: it honours a Python `temp_override(scene=...)`,
   * which is how the agent executor pushes a checkpoint for ITS tab while the
   * window shows whatever the user is looking at (a closing checkpoint lands
   * from a timer after the user has moved on). A user operator's context
   * scene is the window's scene, so both cases read the same way. */
  Scene *scene = CTX_data_scene(C);
  if (scene == nullptr) {
    wmWindow *win = CTX_wm_window(C);
    scene = (win != nullptr) ? win->scene : nullptr;
  }
  Main *bmain = CTX_data_main(C) ? CTX_data_main(C) : G_MAIN;
  if (scene == nullptr && bmain != nullptr) {
    /* A push from a context with no scene and no window (a script run from a
     * timer, a job callback): the shown tab, which is what the executor's
     * routing pin puts on the window for an agent's script. */
    scene = shown_scene(bmain);
    CLOG_WARN(&LOG,
              "undo push with no context scene: tagged with the shown tab '%s'",
              scene ? scene->id.name + 2 : "(none)");
  }
  if (scene == nullptr) {
    return UNDO_TAB_DOCUMENT;
  }
  const uint32_t tab = BKE_undo_tab_uid_for_scene(bmain, scene);
  if (tab == UNDO_TAB_DOCUMENT) {
    CLOG_WARN(&LOG, "undo push on scene '%s' resolves to no tab (an unresolved lane?)", scene->id.name + 2);
  }
  return tab;
}

/* -------------------------------------------------------------------- */
/** \name Step annotation
 * \{ */

/** A Python-registered Scene property (``bpy.props`` on ``bpy.types.Scene``)
 * is stored in ``id.system_properties`` (Blender 4.3+); a raw custom property
 * (``scene["name"] = …``) in ``id.properties``. Either store may carry a run
 * flag; a flag set in either counts. */
static int group_int_prop(const IDProperty *group, const char *name, const int fallback)
{
  if (group == nullptr) {
    return fallback;
  }
  const IDProperty *prop = IDP_GetPropertyFromGroup(group, name);
  if (prop == nullptr) {
    return fallback;
  }
  if (prop->type == IDP_INT) {
    return IDP_int_get(prop);
  }
  if (prop->type == IDP_BOOLEAN) {
    return IDP_bool_get(prop) ? 1 : 0;
  }
  return fallback;
}

static bool scene_state_is_working(const int state)
{
  return ELEM(state, UNDO_TAB_STATE_BUSY, UNDO_TAB_STATE_MODIFYING, UNDO_TAB_STATE_AWAITING_INPUT);
}

bool BKE_undo_tab_scene_is_working(const Scene *scene)
{
  if (scene == nullptr) {
    return false;
  }
  const IDProperty *stores[2] = {scene->id.system_properties, scene->id.properties};
  for (const IDProperty *group : stores) {
    if (group_int_prop(group, "mixie_run_open", 0) != 0) {
      return true;
    }
    if (scene_state_is_working(group_int_prop(group, "mixie_chat_state", -1))) {
      return true;
    }
  }
  return false;
}

bool BKE_undo_tab_any_working(Main *bmain)
{
  if (bmain == nullptr) {
    return false;
  }
  for (const Scene &scene : bmain->scenes) {
    if (BKE_undo_tab_scene_is_lane(&scene)) {
      return true; /* a worker lane exists only while its tab's turn runs */
    }
    if (BKE_undo_tab_scene_is_working(&scene)) {
      return true;
    }
  }
  return false;
}

std::string BKE_undo_tab_scene_name(Main *bmain, const uint32_t tab_uid)
{
  if (bmain != nullptr) {
    for (const Scene &scene : bmain->scenes) {
      if (scene.id.session_uid == tab_uid) {
        return std::string(scene.id.name + 2);
      }
    }
  }
  return std::string();
}

static uint32_t g_push_tab_override = UNDO_TAB_DOCUMENT;

void BKE_undo_tabs_push_override_set(const uint32_t tab_uid)
{
  g_push_tab_override = tab_uid;
}

void BKE_undo_step_tab_annotate(UndoStep *us, bContext *C, Main *bmain, const UndoStep *inherit_from)
{
  if (us == nullptr) {
    return;
  }
  uint32_t tab = g_push_tab_override != UNDO_TAB_DOCUMENT ? g_push_tab_override :
                                                             BKE_undo_tab_uid_from_context(C);
  if (tab == UNDO_TAB_DOCUMENT && inherit_from != nullptr) {
    tab = inherit_from->mixar_tab_uid;
  }
  us->mixar_tab_uid = tab;
  if (us->mixar_owners != nullptr) {
    BKE_undo_owner_map_free(us->mixar_owners);
    us->mixar_owners = nullptr;
  }
  if (BKE_undo_tabs_enabled() && us->type != nullptr && us->type->step_foreach_ID_ref == nullptr &&
      us->use_memfile_step == false && bmain != nullptr)
  {
    /* Only memfile steps carry the map: the type with no ID references of
     * its own is the global (memfile) type. */
    if (STREQ(us->type->name, "Global Undo")) {
      us->mixar_owners = BKE_undo_owner_map_build(bmain, nullptr);
    }
  }
}

void BKE_undo_step_tab_free(UndoStep *us)
{
  if (us != nullptr && us->mixar_owners != nullptr) {
    BKE_undo_owner_map_free(us->mixar_owners);
    us->mixar_owners = nullptr;
  }
}

/** \} */

}  // namespace blender
