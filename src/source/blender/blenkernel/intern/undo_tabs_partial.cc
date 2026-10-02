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
#include <cstddef>
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
#include "BLI_set.hh"
#include "BLI_vector.hh"

#include "BLO_undofile.hh"

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
  /** Conflicts this tab did not change since the step: kept as they are live. */
  Set<uint32_t> keep;
};

static PartialState g_partial;
static UndoTabsMemfileGetFn g_memfile_get = nullptr;

void BKE_undo_tabs_memfile_getter_set(const UndoTabsMemfileGetFn fn)
{
  g_memfile_get = fn;
}

static bool step_is_memfile(const UndoStep *us)
{
  return us != nullptr && us->type != nullptr && STREQ(us->type->name, "Global Undo");
}

/** The chunks of each watched datablock in one memfile, in write order. */
using IdChunks = Map<uint32_t, Vector<const MemFileChunk *>>;

static IdChunks memfile_id_chunks(const MemFile *memfile, const Set<uint32_t> &uids)
{
  IdChunks out;
  if (memfile == nullptr) {
    return out;
  }
  for (const MemFileChunk &chunk : memfile->chunks) {
    if (uids.contains(chunk.id_session_uid)) {
      out.lookup_or_add_default(chunk.id_session_uid).append(&chunk);
    }
  }
  return out;
}

/** Where the ID struct starts in an ID's first chunk: after its block header,
 * #LargeBHead8 (32 bytes) or the legacy #SmallBHead8 (24) depending on a
 * preference. Told apart by finding the datablock's name where the ID struct
 * keeps it; -1 when neither matches (a rename: a real change anyway). */
static int64_t chunk_id_offset(const MemFileChunk *chunk, const ID *id)
{
  for (const int64_t header : {int64_t(32), int64_t(24)}) {
    const int64_t at = header + int64_t(offsetof(ID, name));
    if (at + int64_t(sizeof(id->name)) <= int64_t(chunk->size) &&
        STREQLEN(chunk->buf + at, id->name, sizeof(id->name)))
    {
      return header;
    }
  }
  return -1;
}

/** Same bytes, but for the ID header's ``recalc_up_to_undo_push``: an undo write
 * stamps the depsgraph tags the datablock collected since the previous push
 * (linking an object tags it), which is no change to its data. Identical
 * chunks share their buffer (#BLO_memfile_merge hands a freed step's buffers
 * to the next one), the common case. */
static bool id_chunks_equal(const Vector<const MemFileChunk *> *a,
                            const Vector<const MemFileChunk *> *b,
                            const ID *id)
{
  if (a == nullptr || b == nullptr) {
    return a == b;
  }
  if (a->size() != b->size()) {
    return false;
  }
  for (const int64_t i : a->index_range()) {
    const MemFileChunk *ca = (*a)[i], *cb = (*b)[i];
    if (ca->buf == cb->buf) {
      continue;
    }
    if (ca->size != cb->size) {
      return false;
    }
    int64_t skip_from = -1;
    if (i == 0 && id != nullptr) {
      const int64_t header = chunk_id_offset(ca, id);
      if (header < 0 || header != chunk_id_offset(cb, id)) {
        return false;
      }
      skip_from = header + int64_t(offsetof(ID, recalc_up_to_undo_push));
    }
    const int64_t skip_to = skip_from + int64_t(sizeof(ID::recalc_up_to_undo_push));
    if (skip_from < 0) {
      if (memcmp(ca->buf, cb->buf, ca->size) != 0) {
        return false;
      }
      continue;
    }
    if (memcmp(ca->buf, cb->buf, size_t(skip_from)) != 0 ||
        memcmp(ca->buf + skip_to, cb->buf + skip_to, ca->size - size_t(skip_to)) != 0)
    {
      return false;
    }
  }
  return true;
}

/** The memfile step whose state the live document holds: the newest memfile at
 * or below the stack's active step (tab walks never change a conflict, they keep
 * it, so for conflicts the live state is still that step's). */
static const UndoStep *live_memfile_step(const UndoStack *ustack)
{
  for (const UndoStep *us = ustack->step_active; us != nullptr; us = us->prev) {
    if (step_is_memfile(us) && g_memfile_get(us) != nullptr) {
      return us;
    }
  }
  return nullptr;
}

/** Which shared datablocks THIS tab changed between ``target`` and the live
 * state. Every pair of neighbouring memfile steps in between is compared; a
 * datablock that differs is credited to the authors of the steps in that
 * interval (#UndoStep::mixar_author_uid, which a dead redo branch keeps). A
 * change with no author fails closed. Returns false, the names in ``r_names``,
 * when this tab changed one. */
static bool conflicts_untouched_by_tab(const UndoStack *ustack,
                                       const uint32_t tab_uid,
                                       const UndoStep *target,
                                       const Map<uint32_t, std::string> &conflicts,
                                       const Map<uint32_t, ID *> &live_ids,
                                       std::string *r_names)
{
  const UndoStep *live = live_memfile_step(ustack);
  if (live == nullptr || g_memfile_get(target) == nullptr) {
    *r_names = "(no memfile to compare)";
    return false;
  }
  /* Oldest to newest, whichever way the walk goes (undo: target is older). */
  const int i_target = BLI_findindex(&ustack->steps, target);
  const int i_live = BLI_findindex(&ustack->steps, live);
  if (i_target == i_live) {
    return true;
  }
  const UndoStep *from = (i_target < i_live) ? target : live;
  const UndoStep *to = (i_target < i_live) ? live : target;
  Set<uint32_t> uids;
  for (const auto item : conflicts.items()) {
    uids.add(item.key);
  }
  Set<uint32_t> touched;
  IdChunks prev = memfile_id_chunks(g_memfile_get(from), uids);
  bool by_tab = false;
  for (const UndoStep *us = from->next; us != nullptr; us = us->next) {
    by_tab |= ELEM(us->mixar_author_uid, tab_uid, UNDO_TAB_DOCUMENT);
    const MemFile *memfile = step_is_memfile(us) ? g_memfile_get(us) : nullptr;
    if (memfile != nullptr) {
      IdChunks cur = memfile_id_chunks(memfile, uids);
      if (by_tab) {
        for (const uint32_t uid : uids) {
          if (!id_chunks_equal(prev.lookup_ptr(uid), cur.lookup_ptr(uid), live_ids.lookup_default(uid, nullptr))) {
            touched.add(uid);
          }
        }
      }
      prev = std::move(cur);
      by_tab = false;
    }
    if (us == to) {
      break;
    }
  }
  if (touched.is_empty()) {
    return true;
  }
  int count = 0;
  for (const uint32_t uid : touched) {
    if (count++ < 8) {
      *r_names += (r_names->empty() ? "" : ", ") + conflicts.lookup(uid);
    }
  }
  return false;
}

static void note_conflict(Map<uint32_t, std::string> &conflicts, const uint32_t uid, const std::string &name)
{
  conflicts.add(uid, name);
}

static bool partial_validate(Main *bmain,
                             const UndoStack *ustack,
                             const uint32_t tab_uid,
                             const UndoStep *target,
                             const UndoOwnerMap *live,
                             Set<uint32_t> *r_keep,
                             std::string *r_reason)
{
  const UndoOwnerMap *step_owners = target ? target->mixar_owners : nullptr;
  /* A memfile step written while per-tab undo was off carries no owner map.
   * Without it the reader cannot tell what the tab owned THEN: a datablock the
   * tab had at the step and deleted since would be skipped as "not this tab's"
   * and silently never come back (review 2026-10-01, R5). Fails closed. */
  if (step_owners == nullptr) {
    if (r_reason) {
      *r_reason =
          "that step was recorded while per-tab undo was off (Edit > Undo Whole Document walks "
          "every tab)";
    }
    return false;
  }
  /* The conflicts: local datablocks this tab reaches that another tab reaches
   * too, now or at the step (what two OTHER tabs share is none of this tab's
   * business; review 2026-09-30, finding 1). */
  Map<uint32_t, std::string> conflicts;
  for (const UndoOwnerMap *map : {live, step_owners}) {
    for (const auto item : map->shared_name.items()) {
      const Vector<uint32_t> *tabs = map->shared_by.lookup_ptr(item.key);
      if (tabs != nullptr && tabs->contains(tab_uid)) {
        note_conflict(conflicts, item.key, item.value);
      }
    }
  }
  /* A datablock this tab owned at the step and another single tab owns now, or
   * the reverse, moved between them: restoring this tab would leave it in
   * neither tab (or pull it back from the other). Refused, as before. */
  Map<uint32_t, ID *> live_ids;
  std::string moved;
  int moved_count = 0;
  {
    auto is_other = [&](const uint32_t owner) {
      return !ELEM(owner, tab_uid, UNDO_TAB_DOCUMENT, UNDO_TAB_LANE);
    };
    ID *id = nullptr;
    FOREACH_MAIN_ID_BEGIN (bmain, id) {
      live_ids.add(id->session_uid, id);
      const uint32_t at_step = BKE_undo_owner_map_lookup(step_owners, id->session_uid);
      const uint32_t now = BKE_undo_owner_map_lookup(live, id->session_uid);
      /* A worker lane is not another tab: what the tab's lane built and merged
       * into the tab moved within the tab. */
      const bool single_then = is_other(at_step) && at_step != UNDO_TAB_SHARED;
      const bool single_now = is_other(now) && now != UNDO_TAB_SHARED;
      if ((at_step == tab_uid && single_now) || (now == tab_uid && single_then)) {
        if (moved_count++ < 8) {
          moved += (moved.empty() ? "" : ", ") + std::string(id->name + 2);
        }
      }
    }
    FOREACH_MAIN_ID_END;
  }
  if (moved_count > 0) {
    if (r_reason) {
      *r_reason = "moved between tabs since that step: " + moved +
                  " (Edit > Undo Whole Document walks every tab)";
    }
    return false;
  }
  if (conflicts.is_empty()) {
    return true;
  }
  /* A shared datablock that no longer exists cannot be kept (the restored
   * datablocks of this tab may point at it). */
  std::string gone;
  for (const auto item : conflicts.items()) {
    if (!live_ids.contains(item.key)) {
      gone += (gone.empty() ? "" : ", ") + item.value;
    }
  }
  if (!gone.empty()) {
    if (r_reason) {
      *r_reason = "shared with another tab at that step and gone since: " + gone +
                  " (Edit > Undo Whole Document walks every tab)";
    }
    return false;
  }
  /* Kept as they are, unless this tab changed one since the step (a restore
   * would have to revert it under the other tab). Another tab's changes to it
   * are that tab's business: keeping them is the point of a per-tab walk. */
  std::string touched;
  if (g_memfile_get == nullptr ||
      !conflicts_untouched_by_tab(ustack, tab_uid, target, conflicts, live_ids, &touched))
  {
    if (r_reason) {
      *r_reason = "shared with another tab and changed in this tab since that step: " + touched +
                  " (Edit > Undo Whole Document walks every tab)";
    }
    return false;
  }
  if (r_keep != nullptr) {
    for (const auto item : conflicts.items()) {
      r_keep->add(item.key);
    }
  }
  CLOG_DEBUG(&LOG, "tab %u: %d shared datablock(s) kept as they are", tab_uid, int(conflicts.size()));
  return true;
}

bool BKE_undo_tabs_partial_check(Main *bmain,
                                 const UndoStack *ustack,
                                 const uint32_t tab_uid,
                                 const UndoStep *target,
                                 std::string *r_reason)
{
  UndoOwnerMap *live = BKE_undo_owner_map_build(bmain, nullptr);
  const bool ok = partial_validate(bmain, ustack, tab_uid, target, live, nullptr, r_reason);
  BKE_undo_owner_map_free(live);
  return ok;
}

bool BKE_undo_tabs_partial_begin(Main *bmain,
                                 const UndoStack *ustack,
                                 const uint32_t tab_uid,
                                 const UndoStep *target,
                                 std::string *r_reason)
{
  BLI_assert(!g_partial.active);
  UndoOwnerMap *live = BKE_undo_owner_map_build(bmain, nullptr);
  Set<uint32_t> keep;
  if (!partial_validate(bmain, ustack, tab_uid, target, live, &keep, r_reason)) {
    BKE_undo_owner_map_free(live);
    return false;
  }
  g_partial.active = true;
  g_partial.tab = tab_uid;
  g_partial.step_owners = target->mixar_owners;
  g_partial.live_owners = live;
  g_partial.keep = std::move(keep);
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
  /* A conflict this tab did not change: exactly as it is live. */
  if (g_partial.keep.contains(session_uid)) {
    return has_live ? UndoPartialDecision::Keep : UndoPartialDecision::Skip;
  }
  const uint32_t at_step = BKE_undo_owner_map_lookup(g_partial.step_owners, session_uid);
  const uint32_t now = BKE_undo_owner_map_lookup(g_partial.live_owners, session_uid);
  /* The tab's own datablock, at the step or now: the normal undo paths. */
  if (at_step == g_partial.tab || now == g_partial.tab) {
    return UndoPartialDecision::Restore;
  }
  /* Everything else stays exactly as it is now; what is not live anymore is
   * not brought back on this tab's behalf (a worker lane among them). */
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
