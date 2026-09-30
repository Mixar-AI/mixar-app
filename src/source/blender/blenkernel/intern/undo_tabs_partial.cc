/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup bke
 *
 * Mixar per-tab undo: the partial-restore state the reader consults (arm,
 * validate, decide per datablock, end), the mode-step ownership check, and
 * the harness view of the stack as JSON (``BKE_undo_tabs.hh``).
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

static bool partial_validate(Main *bmain,
                             const uint32_t tab_uid,
                             const UndoOwnerMap *step_owners,
                             const UndoOwnerMap *live,
                             std::string *r_reason)
{
  /* Sharing is judged from the pressing tab: a datablock this tab reaches
   * that another tab reaches too, now or at the step. What two other tabs
   * share does not stop this one (review 2026-09-30, finding 1). */
  std::string names;
  if (undo_tabs_owner_map_shared_for_tab(live, tab_uid, &names) > 0) {
    if (r_reason) {
      *r_reason = "shared with another tab now: " + names +
                  " (Edit > Undo Whole Document walks every tab)";
    }
    return false;
  }
  if (step_owners != nullptr && undo_tabs_owner_map_shared_for_tab(step_owners, tab_uid, &names) > 0) {
    if (r_reason) {
      *r_reason = "shared with another tab at that step: " + names +
                  " (Edit > Undo Whole Document walks every tab)";
    }
    return false;
  }
  /* A datablock the tab owned at the step but another tab owns now, or the
   * reverse (moved between tabs since): shared for this restore. Restoring it
   * as the tab's would change the tab that has it now. Fails closed. */
  if (step_owners != nullptr && bmain != nullptr) {
    std::string moved;
    int moved_count = 0;
    ID *id = nullptr;
    FOREACH_MAIN_ID_BEGIN (bmain, id) {
      const uint32_t at_step = BKE_undo_owner_map_lookup(step_owners, id->session_uid);
      const uint32_t now = BKE_undo_owner_map_lookup(live, id->session_uid);
      const bool tab_then = (at_step == tab_uid), tab_now = (now == tab_uid);
      const bool other_then = (at_step != tab_uid && at_step != UNDO_TAB_DOCUMENT);
      const bool other_now = (now != tab_uid && now != UNDO_TAB_DOCUMENT);
      if ((tab_then && other_now) || (tab_now && other_then)) {
        if (moved_count < 8) {
          moved += (moved.empty() ? "" : ", ") + std::string(id->name + 2);
        }
        moved_count++;
      }
    }
    FOREACH_MAIN_ID_END;
    if (moved_count > 0) {
      if (r_reason) {
        *r_reason = "moved between tabs since that step: " + moved +
                    " (Edit > Undo Whole Document walks every tab)";
      }
      return false;
    }
  }
  return true;
}

bool BKE_undo_tabs_partial_check(Main *bmain,
                                 const uint32_t tab_uid,
                                 const UndoOwnerMap *step_owners,
                                 std::string *r_reason)
{
  UndoOwnerMap *live = BKE_undo_owner_map_build(bmain, nullptr);
  const bool ok = partial_validate(bmain, tab_uid, step_owners, live, r_reason);
  BKE_undo_owner_map_free(live);
  return ok;
}

bool BKE_undo_tabs_partial_begin(Main *bmain,
                                 const uint32_t tab_uid,
                                 const UndoOwnerMap *step_owners,
                                 std::string *r_reason)
{
  BLI_assert(!g_partial.active);
  UndoOwnerMap *live = BKE_undo_owner_map_build(bmain, nullptr);
  if (!partial_validate(bmain, tab_uid, step_owners, live, r_reason)) {
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
    /* The tab's own, or global (no tab reaches it): a Text in the editor, a
     * Brush. Another tab's, or shared, is refused. */
    if (owner != tab_uid && owner != UNDO_TAB_DOCUMENT) {
      if (r_reason) {
        *r_reason = std::string("'") + id->name + "' " +
                    (owner == UNDO_TAB_SHARED ? "is shared between tabs" : "belongs to another tab");
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
