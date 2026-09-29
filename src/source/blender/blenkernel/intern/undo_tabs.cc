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
#include "BKE_lib_query.hh"
#include "BKE_main.hh"
#include "BKE_undo_system.hh"
#include "BKE_undo_tabs.hh"
#include "BKE_wm_runtime.hh"

#include "MEM_guardedalloc.h"

namespace blender {

static CLG_LogRef LOG = {"undo.tabs"};

/* Python-registered Scene properties (bpy.props on the Mixar side) live in the
 * ID's property group under their RNA names. */
static const char *SCENE_SESSION_PROP = "mixie_session_id";
static const char *LANE_PARENT_PROP = "mixar_workspace_main_session";
static const char *LANE_PREFIX = "agentlane:";

bool BKE_undo_tabs_enabled()
{
  static const bool enabled = [] {
    const char *env = std::getenv("MIXAR_PER_TAB_UNDO");
    return env != nullptr && env[0] != '\0' && env[0] != '0';
  }();
  return enabled;
}

static const char *scene_string_prop(const Scene *scene, const char *name)
{
  if (scene == nullptr || scene->id.properties == nullptr) {
    return nullptr;
  }
  const IDProperty *prop = IDP_GetPropertyTypeFromGroup(scene->id.properties, name, IDP_STRING);
  if (prop == nullptr) {
    return nullptr;
  }
  const char *value = IDP_string_get(prop);
  return (value != nullptr && value[0] != '\0') ? value : nullptr;
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

uint32_t BKE_undo_tab_uid_from_context(bContext *C)
{
  if (C == nullptr) {
    return UNDO_TAB_DOCUMENT;
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
  if (scene == nullptr) {
    return UNDO_TAB_DOCUMENT;
  }
  return BKE_undo_tab_uid_for_scene(CTX_data_main(C), scene);
}

/* -------------------------------------------------------------------- */
/** \name Owner map
 * \{ */

struct UndoOwnerMap {
  Map<uint32_t, uint32_t> owner;
  Vector<std::string> shared_names;
  int shared = 0;
  double build_ms = 0.0;
};

struct OwnerWalk {
  UndoOwnerMap *map;
  uint32_t tab;
};

static void owner_map_record(UndoOwnerMap *map, const ID *id, const uint32_t tab)
{
  if (id == nullptr || id->session_uid == 0) {
    return;
  }
  uint32_t *slot = map->owner.lookup_ptr(id->session_uid);
  if (slot == nullptr) {
    map->owner.add_new(id->session_uid, tab);
    return;
  }
  if (*slot != tab && *slot != UNDO_TAB_SHARED) {
    *slot = UNDO_TAB_SHARED;
    map->shared += 1;
    if (map->shared_names.size() < 32) {
      map->shared_names.append(std::string(id->name));
    }
  }
}

UndoOwnerMap *BKE_undo_owner_map_build(Main *bmain, double *r_ms)
{
  const double t0 = BLI_time_now_seconds();
  UndoOwnerMap *map = MEM_new<UndoOwnerMap>(__func__);
  if (bmain != nullptr) {
    for (Scene &scene : bmain->scenes) {
      const uint32_t tab = BKE_undo_tab_uid_for_scene(bmain, &scene);
      if (tab == UNDO_TAB_DOCUMENT) {
        continue; /* an unresolved lane: no tab can claim it */
      }
      owner_map_record(map, &scene.id, tab);
      OwnerWalk walk{map, tab};
      BKE_library_foreach_ID_link(
          bmain,
          &scene.id,
          [](LibraryIDLinkCallbackData *cb_data) -> int {
            OwnerWalk *w = static_cast<OwnerWalk *>(cb_data->user_data);
            const ID *id = *cb_data->id_pointer;
            if (id != nullptr) {
              owner_map_record(w->map, id, w->tab);
            }
            return IDWALK_RET_NOP;
          },
          &walk,
          IDWALK_READONLY | IDWALK_RECURSE);
    }
  }
  map->build_ms = (BLI_time_now_seconds() - t0) * 1000.0;
  if (r_ms != nullptr) {
    *r_ms = map->build_ms;
  }
  CLOG_DEBUG(&LOG,
             "owner map: %d ids, %d shared, %.2f ms",
             int(map->owner.size()),
             map->shared,
             map->build_ms);
  return map;
}

void BKE_undo_owner_map_free(UndoOwnerMap *map)
{
  if (map != nullptr) {
    MEM_delete(map);
  }
}

uint32_t BKE_undo_owner_map_lookup(const UndoOwnerMap *map, const uint32_t session_uid)
{
  if (map == nullptr) {
    return UNDO_TAB_DOCUMENT;
  }
  return map->owner.lookup_default(session_uid, UNDO_TAB_DOCUMENT);
}

int BKE_undo_owner_map_size(const UndoOwnerMap *map)
{
  return map != nullptr ? int(map->owner.size()) : 0;
}

int BKE_undo_owner_map_shared_count(const UndoOwnerMap *map)
{
  return map != nullptr ? map->shared : 0;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Step annotation
 * \{ */

static int scene_int_prop(const Scene *scene, const char *name, const int fallback)
{
  if (scene == nullptr || scene->id.properties == nullptr) {
    return fallback;
  }
  const IDProperty *prop = IDP_GetPropertyFromGroup(scene->id.properties, name);
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

bool BKE_undo_tab_scene_is_working(const Scene *scene)
{
  if (scene_int_prop(scene, "mixie_run_open", 0) != 0) {
    return true;
  }
  const int state = scene_int_prop(scene, "mixie_chat_state", -1);
  return ELEM(state, UNDO_TAB_STATE_BUSY, UNDO_TAB_STATE_MODIFYING, UNDO_TAB_STATE_AWAITING_INPUT);
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

/* -------------------------------------------------------------------- */
/** \name Partial restore state (M2)
 * \{ */

struct PartialState {
  bool active = false;
  /** M4: a whole-document restore, every ID re-read. */
  bool whole = false;
  uint32_t tab = UNDO_TAB_DOCUMENT;
  const UndoOwnerMap *step_owners = nullptr;
  UndoOwnerMap *live_owners = nullptr;
};

static PartialState g_partial;

static std::string shared_names_joined(const UndoOwnerMap *map)
{
  std::string out;
  if (map == nullptr) {
    return out;
  }
  for (const std::string &name : map->shared_names) {
    if (!out.empty()) {
      out += ", ";
    }
    out += name;
  }
  return out;
}

bool BKE_undo_tabs_partial_begin(Main *bmain,
                                 const uint32_t tab_uid,
                                 const UndoOwnerMap *step_owners,
                                 std::string *r_reason)
{
  BLI_assert(!g_partial.active);
  UndoOwnerMap *live = BKE_undo_owner_map_build(bmain, nullptr);
  if (BKE_undo_owner_map_shared_count(live) > 0) {
    if (r_reason) {
      *r_reason = "shared between tabs now: " + shared_names_joined(live);
    }
    BKE_undo_owner_map_free(live);
    return false;
  }
  if (step_owners != nullptr && BKE_undo_owner_map_shared_count(step_owners) > 0) {
    if (r_reason) {
      *r_reason = "shared between tabs at that step: " + shared_names_joined(step_owners);
    }
    BKE_undo_owner_map_free(live);
    return false;
  }
  g_partial.active = true;
  g_partial.tab = tab_uid;
  g_partial.step_owners = step_owners;
  g_partial.live_owners = live;
  CLOG_DEBUG(&LOG, "partial restore armed for tab %u", tab_uid);
  return true;
}

bool BKE_undo_tabs_ids_owned(Main *bmain,
                             const uint32_t tab_uid,
                             const Span<ID *> ids,
                             std::string *r_reason)
{
  UndoOwnerMap *live = BKE_undo_owner_map_build(bmain, nullptr);
  bool ok = true;
  for (ID *id : ids) {
    if (id == nullptr) {
      if (r_reason) {
        *r_reason = "a datablock that step edited no longer exists";
      }
      ok = false;
      break;
    }
    const uint32_t owner = (GS(id->name) == ID_SCE) ?
                               BKE_undo_tab_uid_for_scene(bmain, reinterpret_cast<Scene *>(id)) :
                               BKE_undo_owner_map_lookup(live, id->session_uid);
    if (owner != tab_uid) {
      if (r_reason) {
        *r_reason = std::string("'") + id->name + "' " +
                    (owner == UNDO_TAB_SHARED  ? "is shared between tabs" :
                     owner == UNDO_TAB_DOCUMENT ? "belongs to no tab" :
                                                  "belongs to another tab");
      }
      ok = false;
      break;
    }
  }
  BKE_undo_owner_map_free(live);
  return ok;
}

void BKE_undo_tabs_whole_document_begin()
{
  BLI_assert(!g_partial.active);
  g_partial = PartialState{};
  g_partial.active = true;
  g_partial.whole = true;
  CLOG_DEBUG(&LOG, "whole-document restore armed: every ID re-read");
}

void BKE_undo_tabs_partial_end()
{
  if (g_partial.live_owners != nullptr) {
    BKE_undo_owner_map_free(g_partial.live_owners);
  }
  g_partial = PartialState{};
}

bool BKE_undo_tabs_partial_active()
{
  return g_partial.active;
}

uint32_t BKE_undo_tabs_partial_tab()
{
  return g_partial.active ? g_partial.tab : UNDO_TAB_DOCUMENT;
}

UndoPartialDecision BKE_undo_tabs_partial_decide(const uint32_t session_uid, const bool has_live)
{
  if (!g_partial.active || g_partial.whole) {
    return UndoPartialDecision::Restore;
  }
  const uint32_t at_step = BKE_undo_owner_map_lookup(g_partial.step_owners, session_uid);
  const uint32_t now = BKE_undo_owner_map_lookup(g_partial.live_owners, session_uid);
  /* The tab's own datablock, at the step or now: the normal undo paths. */
  if (at_step == g_partial.tab || now == g_partial.tab) {
    return UndoPartialDecision::Restore;
  }
  /* Everything else stays exactly as it is now; what is not live anymore is
   * not brought back on this tab's behalf. */
  return has_live ? UndoPartialDecision::Keep : UndoPartialDecision::Skip;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Harness view
 * \{ */

static void json_escape_into(std::string &out, const char *text)
{
  for (const char *p = text; p != nullptr && *p; p++) {
    switch (*p) {
      case '"':
        out += "\\\"";
        break;
      case '\\':
        out += "\\\\";
        break;
      case '\n':
        out += "\\n";
        break;
      default:
        if (uint8_t(*p) < 0x20) {
          out += ' ';
        }
        else {
          out += *p;
        }
    }
  }
}

std::string BKE_undo_tabs_history_json(const wmWindowManager *wm)
{
  std::string out = "{";
  const UndoStack *ustack = (wm != nullptr && wm->runtime != nullptr) ? wm->runtime->undo_stack :
                                                                       nullptr;
  uint32_t current = UNDO_TAB_DOCUMENT;
  if (wm != nullptr) {
    const wmWindow *win = (wm->runtime != nullptr && wm->runtime->winactive != nullptr) ?
                              wm->runtime->winactive :
                              static_cast<const wmWindow *>(wm->windows.first);
    if (win != nullptr && win->scene != nullptr) {
      current = BKE_undo_tab_uid_for_scene(G_MAIN, win->scene);
    }
  }
  out += "\"enabled\":" + std::string(BKE_undo_tabs_enabled() ? "true" : "false");
  out += ",\"current_tab\":" + std::to_string(current);
  out += ",\"steps\":[";
  if (ustack != nullptr) {
    const UndoStep *cursor = (current != UNDO_TAB_DOCUMENT) ?
                                 BKE_undosys_tab_cursor(const_cast<UndoStack *>(ustack), current) :
                                 nullptr;
    int index = BLI_listbase_count(&ustack->steps) - 1;
    bool first = true;
    for (const UndoStep *us = static_cast<const UndoStep *>(ustack->steps.last); us; us = us->prev) {
      if (!first) {
        out += ",";
      }
      first = false;
      out += "{\"index\":" + std::to_string(index--);
      out += ",\"name\":\"";
      json_escape_into(out, us->name);
      out += "\",\"type\":\"";
      json_escape_into(out, us->type != nullptr ? us->type->name : "");
      out += "\",\"tab_uid\":" + std::to_string(us->mixar_tab_uid);
      out += ",\"skip\":" + std::string(us->skip ? "true" : "false");
      out += ",\"active\":" + std::string(us == ustack->step_active ? "true" : "false");
      out += ",\"cursor\":" + std::string(us == cursor ? "true" : "false");
      out += ",\"memfile\":" +
             std::string((us->type != nullptr && STREQ(us->type->name, "Global Undo")) ? "true" :
                                                                                         "false");
      out += ",\"owners\":" + std::to_string(BKE_undo_owner_map_size(us->mixar_owners));
      out += ",\"shared\":" + std::to_string(BKE_undo_owner_map_shared_count(us->mixar_owners));
      out += ",\"shared_names\":[";
      if (us->mixar_owners != nullptr) {
        bool first_name = true;
        for (const std::string &name : us->mixar_owners->shared_names) {
          if (!first_name) {
            out += ",";
          }
          first_name = false;
          out += "\"";
          json_escape_into(out, name.c_str());
          out += "\"";
        }
      }
      out += "],\"owner_map_ms\":" +
             std::to_string(us->mixar_owners != nullptr ? us->mixar_owners->build_ms : 0.0);
      out += "}";
    }
  }
  out += "]}";
  return out;
}

/** \} */

}  // namespace blender
