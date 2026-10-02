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
#include <algorithm>
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
#include "DNA_object_types.h"
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
  /** Shared datablocks nobody changed since the step: kept as they are live. */
  Set<uint32_t> keep;
  /** Shared datablocks only this tab changed since the step: restored (the author
   * takes back its own change, which the other tab sees, as sharing means). */
  Set<uint32_t> restore;
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

/** Same bytes, but for the ID header's depsgraph tags: an undo write stamps the
 * tags the datablock collected since the previous push (linking an object tags
 * it, drawing an image leaves a pending recalc), which is no change to its data. Identical
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
    if (id != nullptr) {
      CLOG_DEBUG(&LOG, "%s changed: %d chunks vs %d", id->name, int(a->size()), int(b->size()));
    }
    return false;
  }
  for (const int64_t i : a->index_range()) {
    const MemFileChunk *ca = (*a)[i], *cb = (*b)[i];
    if (ca->buf == cb->buf) {
      continue;
    }
    if (ca->size != cb->size) {
      if (id != nullptr) {
        CLOG_DEBUG(&LOG, "%s changed: chunk %d is %zu bytes vs %zu", id->name, int(i), ca->size, cb->size);
      }
      return false;
    }
    int64_t skip_from = -1;
    if (i == 0 && id != nullptr) {
      const int64_t header = chunk_id_offset(ca, id);
      if (header < 0 || header != chunk_id_offset(cb, id)) {
        return false;
      }
      skip_from = header + int64_t(offsetof(ID, recalc));
    }
    /* ``recalc``, ``recalc_up_to_undo_push`` and ``recalc_after_undo_push``: depsgraph
     * tags, written as they stand at the push (an image drawn in the viewport carries
     * a pending ``recalc``), never a change of the data. */
    const int64_t skip_to = skip_from + int64_t(offsetof(ID, recalc_after_undo_push) +
                                                sizeof(ID::recalc_after_undo_push) -
                                                offsetof(ID, recalc));
    if (skip_from < 0) {
      if (memcmp(ca->buf, cb->buf, ca->size) != 0) {
        return false;
      }
      continue;
    }
    if (memcmp(ca->buf, cb->buf, size_t(skip_from)) != 0 ||
        memcmp(ca->buf + skip_to, cb->buf + skip_to, ca->size - size_t(skip_to)) != 0)
    {
      for (size_t at = 0; at < ca->size; at++) {
        if (ca->buf[at] != cb->buf[at] && !(int64_t(at) >= skip_from && int64_t(at) < skip_to)) {
          CLOG_DEBUG(&LOG, "%s changed: chunk %d differs at byte %zu of %zu", id ? id->name : "?", int(i), at, ca->size);
          break;
        }
      }
      return false;
    }
  }
  return true;
}

static int step_index(const UndoStack *ustack, const UndoStep *us)
{
  return us != nullptr ? BLI_findindex(&ustack->steps, us) : -1;
}

/** One change to a shared datablock: the stack index of the step that shows it
 * (a memfile step whose chunks for it differ from the memfile before, or a mode
 * step that names it) and an author of that change. */
struct IdChange {
  int index;
  uint32_t author;
};
using IdChanges = Map<uint32_t, Vector<IdChange>>;

/** The change history of ``watched`` across the whole stack. A memfile change is
 * credited to every author of the steps since the memfile before it (a step's
 * #UndoStep::mixar_author_uid, which a dead redo branch keeps). */
static IdChanges collect_id_changes(const UndoStack *ustack, const Map<uint32_t, ID *> &watched)
{
  IdChanges out;
  Set<uint32_t> uids;
  for (const auto item : watched.items()) {
    uids.add(item.key);
  }
  IdChunks prev;
  bool have_prev = false;
  Vector<uint32_t> authors;
  /* A mode step names the OBJECT it edits (edit mesh, sculpt), but the change is
   * to its data, and it reaches no memfile until the next push of any tab flushes
   * the edit: an object's name stands for its watched data too. */
  Map<std::string, Vector<uint32_t>> by_name;
  for (const auto item : watched.items()) {
    by_name.lookup_or_add_default(item.value->name).append(item.key);
  }
  if (G_MAIN != nullptr) {
    for (const Object &ob : G_MAIN->objects) {
      const ID *data = static_cast<const ID *>(ob.data);
      if (data != nullptr && watched.contains(data->session_uid)) {
        by_name.lookup_or_add_default(ob.id.name).append_non_duplicates(data->session_uid);
      }
    }
  }
  struct RefMatch {
    const Map<std::string, Vector<uint32_t>> *by_name;
    Vector<uint32_t> found;
  };
  int index = -1;
  for (const UndoStep *us = static_cast<const UndoStep *>(ustack->steps.first); us; us = us->next) {
    index++;
    authors.append_non_duplicates(us->mixar_author_uid);
    const MemFile *memfile = (step_is_memfile(us) && g_memfile_get != nullptr) ? g_memfile_get(us) :
                                                                                  nullptr;
    if (memfile == nullptr) {
      if (us->type != nullptr && us->type->step_foreach_ID_ref != nullptr) {
        /* A mode step (a stroke, an edit-mesh step) names what it changes; matched
         * by name, as the walk resolves its references. */
        RefMatch match{&by_name, {}};
        us->type->step_foreach_ID_ref(
            const_cast<UndoStep *>(us),
            [](void *user_data, UndoRefID *id_ref) {
              RefMatch *m = static_cast<RefMatch *>(user_data);
              if (const Vector<uint32_t> *uids = m->by_name->lookup_ptr(id_ref->name)) {
                for (const uint32_t uid : *uids) {
                  m->found.append_non_duplicates(uid);
                }
              }
            },
            &match);
        for (const uint32_t uid : match.found) {
          out.lookup_or_add_default(uid).append({index, us->mixar_author_uid});
        }
      }
      continue;
    }
    IdChunks cur = memfile_id_chunks(memfile, uids);
    if (have_prev) {
      for (const uint32_t uid : uids) {
        if (!id_chunks_equal(prev.lookup_ptr(uid), cur.lookup_ptr(uid), watched.lookup(uid))) {
          for (const uint32_t author : authors) {
            out.lookup_or_add_default(uid).append({index, author});
          }
        }
      }
    }
    prev = std::move(cur);
    have_prev = true;
    authors.clear();
  }
  return out;
}

enum class SharedFate { Keep, Restore, Refuse };

/**
 * What a tab's walk does with a datablock it shares with another tab (review
 * 2026-10-02, the author rule: an undo takes back only the pressing tab's own
 * actions, wherever they landed). ``lo`` is the older of the walk's target and
 * the tab's cursor:
 *
 * - this tab did not change it after ``lo``: KEEP it exactly as it is, whatever
 *   the other tabs did to it (keeping never touches their work);
 * - this tab changed it, and another tab changed it after ``lo`` too or has an
 *   older change to it undone since (its cursor is behind that change): REFUSE,
 *   the two cannot be told apart in one memfile;
 * - only this tab changed it: RESTORE it with the tab (the other tab sees the
 *   shared datablock go back), unless it did not exist at the target while
 *   another tab uses it now (a restore would free it under that tab).
 */
static SharedFate shared_fate(const UndoStack *ustack,
                              const uint32_t tab_uid,
                              const int lo,
                              const Vector<IdChange> *changes,
                              const bool absent_at_target,
                              const char **r_why)
{
  if (changes == nullptr) {
    return SharedFate::Keep;
  }
  const int active = step_index(ustack, ustack->step_active);
  bool by_tab = false;
  const char *foreign = nullptr;
  for (const IdChange &c : *changes) {
    if (c.author == tab_uid) {
      by_tab |= c.index > lo;
      continue;
    }
    if (c.index > lo) {
      foreign = "another tab changed it since that step";
      continue;
    }
    const UndoStep *cursor = (c.author != UNDO_TAB_DOCUMENT) ?
                                 BKE_undosys_tab_cursor(const_cast<UndoStack *>(ustack), c.author) :
                                 nullptr;
    if (c.index > active || (cursor != nullptr && c.index > step_index(ustack, cursor))) {
      foreign = "another tab has taken back its own change to it";
    }
  }
  /* Keeping it exactly as it is never touches another tab's work, whatever the
   * other tabs did to it: only a restore (this tab changed it) can conflict. */
  if (!by_tab) {
    return SharedFate::Keep;
  }
  if (foreign != nullptr) {
    *r_why = foreign;
    return SharedFate::Refuse;
  }
  if (absent_at_target) {
    *r_why = "this tab made it after that step and another tab uses it now";
    return SharedFate::Refuse;
  }
  return SharedFate::Restore;
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
                             Set<uint32_t> *r_restore,
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
  if (g_memfile_get == nullptr) {
    if (r_reason) {
      *r_reason = "shared with another tab (Edit > Undo Whole Document walks every tab)";
    }
    return false;
  }
  /* The author rule (shared_fate): keep what nobody changed, restore what only
   * this tab changed, refuse what another tab changed too. */
  Map<uint32_t, ID *> watched;
  Set<uint32_t> uids;
  for (const auto item : conflicts.items()) {
    watched.add(item.key, live_ids.lookup(item.key));
    uids.add(item.key);
  }
  const IdChanges changes = collect_id_changes(ustack, watched);
  const IdChunks at_target = memfile_id_chunks(g_memfile_get(target), uids);
  const int lo = std::min(step_index(ustack, target),
                          step_index(ustack, BKE_undosys_tab_cursor(const_cast<UndoStack *>(ustack), tab_uid)));
  std::string refused;
  int restored = 0;
  for (const auto item : conflicts.items()) {
    const char *why = "";
    const Vector<IdChange> *ch = changes.lookup_ptr(item.key);
    switch (shared_fate(ustack, tab_uid, lo, ch, !at_target.contains(item.key), &why)) {
      case SharedFate::Keep:
        if (r_keep != nullptr) {
          r_keep->add(item.key);
        }
        break;
      case SharedFate::Restore:
        restored++;
        if (r_restore != nullptr) {
          r_restore->add(item.key);
        }
        break;
      case SharedFate::Refuse:
        refused += (refused.empty() ? "" : "; ") + item.value + " (" + why + ")";
        break;
    }
  }
  if (!refused.empty()) {
    if (r_reason) {
      *r_reason = "shared with another tab: " + refused + " (Edit > Undo Whole Document walks every tab)";
    }
    return false;
  }
  CLOG_DEBUG(&LOG,
             "tab %u: %d shared datablock(s), %d restored with the tab, the rest kept",
             tab_uid,
             int(conflicts.size()),
             restored);
  return true;
}

bool BKE_undo_tabs_partial_check(Main *bmain,
                                 const UndoStack *ustack,
                                 const uint32_t tab_uid,
                                 const UndoStep *target,
                                 std::string *r_reason)
{
  UndoOwnerMap *live = BKE_undo_owner_map_build(bmain, nullptr);
  const bool ok = partial_validate(bmain, ustack, tab_uid, target, live, nullptr, nullptr, r_reason);
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
  Set<uint32_t> keep, restore;
  if (!partial_validate(bmain, ustack, tab_uid, target, live, &keep, &restore, r_reason)) {
    BKE_undo_owner_map_free(live);
    return false;
  }
  g_partial.active = true;
  g_partial.tab = tab_uid;
  g_partial.step_owners = target->mixar_owners;
  g_partial.live_owners = live;
  g_partial.keep = std::move(keep);
  g_partial.restore = std::move(restore);
  CLOG_DEBUG(&LOG, "partial restore armed for tab %u", tab_uid);
  return true;
}

bool BKE_undo_tabs_ids_owned(Main *bmain,
                             const uint32_t tab_uid,
                             const Span<ID *> ids,
                             std::string *r_reason,
                             const Set<uint32_t> *shared_ok)
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
    if (owner == UNDO_TAB_SHARED && shared_ok != nullptr && shared_ok->contains(id->session_uid)) {
      continue; /* shared, and no other tab touched it since this tab's cursor */
    }
    if (owner != tab_uid && owner != UNDO_TAB_DOCUMENT) {
      if (r_reason) {
        *r_reason = std::string("'") + (id->name + 2) + "' " +
                    (owner == UNDO_TAB_SHARED ? "is shared between tabs" : "belongs to another tab");
      }
      ok = false;
      break;
    }
  }
  BKE_undo_owner_map_free(live);
  return ok;
}

Set<uint32_t> BKE_undo_tabs_shared_ok(const UndoStack *ustack,
                                      const uint32_t tab_uid,
                                      const UndoStep *target,
                                      const Span<ID *> ids)
{
  Set<uint32_t> ok;
  if (ustack == nullptr || target == nullptr || ids.is_empty()) {
    return ok;
  }
  Map<uint32_t, ID *> watched;
  for (ID *id : ids) {
    if (id != nullptr) {
      watched.add(id->session_uid, id);
    }
  }
  const IdChanges changes = collect_id_changes(ustack, watched);
  const int lo = std::min(step_index(ustack, target),
                          step_index(ustack, BKE_undosys_tab_cursor(const_cast<UndoStack *>(ustack), tab_uid)));
  for (const auto item : watched.items()) {
    const char *why = "";
    if (shared_fate(ustack, tab_uid, lo, changes.lookup_ptr(item.key), false, &why) != SharedFate::Refuse) {
      ok.add(item.key);
    }
  }
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
  /* A shared datablock only this tab changed since the step: the tab's to restore. */
  if (g_partial.restore.contains(session_uid)) {
    return UndoPartialDecision::Restore;
  }
  /* A shared datablock nobody changed since the step: exactly as it is live. */
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
