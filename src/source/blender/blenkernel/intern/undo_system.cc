/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup bke
 *
 * Used by ED_undo.hh, internal implementation.
 */

#include <cstdio>
#include <cstring>

#include "CLG_log.h"

#include "BLI_listbase.h"
#include "BLI_string.h"
#include "BLI_sys_types.h"
#include "BLI_utildefines.h"

#include "BLT_translation.hh"

#include "DNA_listBase.h"
#include "DNA_windowmanager_types.h"

#include "BKE_context.hh"
#include "BKE_global.hh"
#include "BKE_lib_id.hh"
#include "BKE_lib_override.hh"
#include "BKE_library.hh"
#include "BKE_main.hh"
#include "BKE_undo_system.hh"
#include "BKE_undo_tabs.hh"

#include "DNA_scene_types.h"

#include "BLI_set.hh"

#include "BLI_map.hh"
#include "BLI_memory_utils.hh"
#include "BLI_vector.hh"

#include "RNA_access.hh"

#include "MEM_guardedalloc.h"

/* Header to pull symbols from the file which otherwise might get stripped away. */
#include "BKE_blender_undo.hh"

namespace blender {

#define undo_stack _wm_undo_stack_disallow /* pass in as a variable always. */

/** Odd requirement of Blender that we always keep a memfile undo in the stack. */
#define WITH_GLOBAL_UNDO_KEEP_ONE

/** Make sure all ID's created at the point we add an undo step that uses ID's. */
#define WITH_GLOBAL_UNDO_ENSURE_UPDATED

/**
 * Make sure we don't apply edits on top of a newer memfile state, see: #56163.
 * \note Keep an eye on this, could solve differently.
 */
#define WITH_GLOBAL_UNDO_CORRECT_ORDER

/** We only need this locally. */
static CLG_LogRef LOG = {"undo"};

/* -------------------------------------------------------------------- */
/** \name Mixar per-tab cursors
 * \{ */

using TabCursors = Map<uint32_t, UndoStep *>;

static TabCursors *tab_cursors_get(UndoStack *ustack, const bool ensure)
{
  if (ustack->mixar_tab_cursors == nullptr && ensure) {
    ustack->mixar_tab_cursors = MEM_new<TabCursors>(__func__);
  }
  return static_cast<TabCursors *>(ustack->mixar_tab_cursors);
}

static void tab_cursors_free(UndoStack *ustack)
{
  if (ustack->mixar_tab_cursors != nullptr) {
    MEM_delete(static_cast<TabCursors *>(ustack->mixar_tab_cursors));
    ustack->mixar_tab_cursors = nullptr;
  }
}

/** A step is going away: any tab whose cursor sat on it moves to the top. */
static void tab_cursors_drop_step(TabCursors *cursors, const UndoStep *us)
{
  if (cursors == nullptr) {
    return;
  }
  Vector<uint32_t> gone;
  for (auto item : cursors->items()) {
    if (item.value == us) {
      gone.append(item.key);
    }
  }
  for (const uint32_t tab : gone) {
    cursors->remove(tab);
  }
}

/** A step is going away: no live cursor and no step's snapshot may point at it. */
static void tab_cursors_forget_step(UndoStack *ustack, const UndoStep *us)
{
  tab_cursors_drop_step(tab_cursors_get(ustack, false), us);
  for (UndoStep &it : ustack->steps) {
    tab_cursors_drop_step(static_cast<TabCursors *>(it.mixar_cursors), us);
  }
}

/** A copy of the live cursors for a step's snapshot; null when no tab is behind. */
static TabCursors *tab_cursors_snapshot(UndoStack *ustack)
{
  TabCursors *cursors = tab_cursors_get(ustack, false);
  if (cursors == nullptr || cursors->is_empty()) {
    return nullptr;
  }
  return MEM_new<TabCursors>(__func__, *cursors);
}

static void tab_cursors_snapshot_free(UndoStep *us)
{
  if (us->mixar_cursors != nullptr) {
    MEM_delete(static_cast<TabCursors *>(us->mixar_cursors));
    us->mixar_cursors = nullptr;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Undo Types
 * \{ */

const UndoType *BKE_UNDOSYS_TYPE_IMAGE = nullptr;
const UndoType *BKE_UNDOSYS_TYPE_MEMFILE = nullptr;
const UndoType *BKE_UNDOSYS_TYPE_PAINTCURVE = nullptr;
const UndoType *BKE_UNDOSYS_TYPE_PARTICLE = nullptr;
const UndoType *BKE_UNDOSYS_TYPE_SCULPT = nullptr;
const UndoType *BKE_UNDOSYS_TYPE_TEXT = nullptr;

static ListBaseT<UndoType> g_undo_types = {nullptr, nullptr};

/* An unused function with public linkage just to ensure symbols from the blender_undo.cc are not
 * stripped. */
void bke_undo_system_linker_workaround();
void bke_undo_system_linker_workaround()
{
  BLI_assert_unreachable();
  BKE_memfile_undo_free(nullptr);
}

static const UndoType *BKE_undosys_type_from_context(bContext *C)
{
  for (const UndoType &ut : g_undo_types) {
    /* No poll means we don't check context. */
    if (ut.poll && ut.poll(C)) {
      return &ut;
    }
  }
  return nullptr;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Internal Nested Undo Checks
 *
 * Make sure we're not running undo operations from 'step_encode', 'step_decode' callbacks.
 * bugs caused by this situation aren't _that_ hard to spot but aren't always so obvious.
 * Best we have a check which shows the problem immediately.
 * \{ */

#define WITH_NESTED_UNDO_CHECK

#ifdef WITH_NESTED_UNDO_CHECK
static bool g_undo_callback_running = false;
#  define UNDO_NESTED_ASSERT(state) BLI_assert(g_undo_callback_running == state)
#  define UNDO_NESTED_CHECK_BEGIN \
    { \
      UNDO_NESTED_ASSERT(false); \
      g_undo_callback_running = true; \
    } \
    ((void)0)
#  define UNDO_NESTED_CHECK_END \
    { \
      UNDO_NESTED_ASSERT(true); \
      g_undo_callback_running = false; \
    } \
    ((void)0)
#else
#  define UNDO_NESTED_ASSERT(state) ((void)0)
#  define UNDO_NESTED_CHECK_BEGIN ((void)0)
#  define UNDO_NESTED_CHECK_END ((void)0)
#endif

/** \} */

/* -------------------------------------------------------------------- */
/** \name Internal Callback Wrappers
 *
 * #UndoRefID is simply a way to avoid in-lining name copy and lookups,
 * since it's easy to forget a single case when done inline (crashing in some cases).
 *
 * \{ */

static void undosys_id_ref_store(void * /*user_data*/, UndoRefID *id_ref)
{
  BLI_assert(id_ref->name[0] == '\0');
  if (id_ref->ptr) {
    STRNCPY(id_ref->name, id_ref->ptr->name);
    if (id_ref->ptr->lib) {
      STRNCPY(id_ref->library_filepath_abs, id_ref->ptr->lib->runtime->filepath_abs);
    }
    else {
      id_ref->library_filepath_abs[0] = '\0';
    }
    /* Not needed, just prevents stale data access. */
    id_ref->ptr = nullptr;
  }
}

static void undosys_id_ref_resolve(void *user_data, UndoRefID *id_ref)
{
  /* NOTE: we could optimize this,
   * for now it's not too bad since it only runs when we access undo! */
  Main *bmain = static_cast<Main *>(user_data);
  id_ref->ptr = BKE_libblock_find_name_and_library_filepath(
      bmain,
      GS(id_ref->name),
      id_ref->name + 2,
      (id_ref->library_filepath_abs[0] ? id_ref->library_filepath_abs : nullptr));
}

static bool undosys_step_encode(bContext *C, Main *bmain, UndoStack *ustack, UndoStep *us)
{
  CLOG_DEBUG(&LOG, "addr=%p, name='%s', type='%s'", us, us->name, us->type->name);
  UNDO_NESTED_CHECK_BEGIN;
  bool ok = us->type->step_encode(C, bmain, us);
  UNDO_NESTED_CHECK_END;
  if (ok) {
    if (us->type->step_foreach_ID_ref != nullptr) {
      /* Don't use from context yet because sometimes context is fake and
       * not all members are filled in. */
      us->type->step_foreach_ID_ref(us, undosys_id_ref_store, bmain);
    }

#ifdef WITH_GLOBAL_UNDO_CORRECT_ORDER
    if (us->type == BKE_UNDOSYS_TYPE_MEMFILE) {
      ustack->step_active_memfile = us;
    }
#endif
  }
  if (ok == false) {
    CLOG_DEBUG(&LOG, "encode callback didn't create undo step");
  }
  return ok;
}

static void undosys_step_decode(bContext *C,
                                Main *bmain,
                                UndoStack *ustack,
                                UndoStep *us,
                                const eUndoStepDir dir,
                                bool is_final)
{
  CLOG_DEBUG(&LOG, "addr=%p, name='%s', type='%s'", us, us->name, us->type->name);

  if (us->type->step_foreach_ID_ref) {
#ifdef WITH_GLOBAL_UNDO_CORRECT_ORDER
    if (us->type != BKE_UNDOSYS_TYPE_MEMFILE) {
      for (UndoStep *us_iter = us->prev; us_iter; us_iter = us_iter->prev) {
        if (us_iter->type == BKE_UNDOSYS_TYPE_MEMFILE) {
          if (us_iter == ustack->step_active_memfile) {
            /* Common case, we're already using the last memfile state. */
          }
          else {
            /* Load the previous memfile state so any ID's referenced in this
             * undo step will be correctly resolved, see: #56163. */
            undosys_step_decode(C, bmain, ustack, us_iter, dir, false);
            /* May have been freed on memfile read. */
            bmain = G_MAIN;
          }
          break;
        }
      }
    }
#endif
    /* Don't use from context yet because sometimes context is fake and
     * not all members are filled in. */
    us->type->step_foreach_ID_ref(us, undosys_id_ref_resolve, bmain);
  }

  UNDO_NESTED_CHECK_BEGIN;
  us->type->step_decode(C, bmain, us, dir, is_final);
  UNDO_NESTED_CHECK_END;

#ifdef WITH_GLOBAL_UNDO_CORRECT_ORDER
  if (us->type == BKE_UNDOSYS_TYPE_MEMFILE) {
    ustack->step_active_memfile = us;
  }
#endif
}

static void undosys_step_free_and_unlink(UndoStack *ustack, UndoStep *us)
{
  CLOG_DEBUG(&LOG, "addr=%p, name='%s', type='%s'", us, us->name, us->type->name);
  UNDO_NESTED_CHECK_BEGIN;
  us->type->step_free(us);
  UNDO_NESTED_CHECK_END;
  BKE_undo_step_tab_free(us);
  tab_cursors_snapshot_free(us);
  tab_cursors_forget_step(ustack, us);

  BLI_remlink(&ustack->steps, us);
  MEM_delete(us);

#ifdef WITH_GLOBAL_UNDO_CORRECT_ORDER
  if (ustack->step_active_memfile == us) {
    ustack->step_active_memfile = nullptr;
  }
#endif
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Undo Stack
 * \{ */

#ifndef NDEBUG
static void undosys_stack_validate(UndoStack *ustack, bool expect_non_empty)
{
  if (ustack->step_active != nullptr) {
    BLI_assert(!ustack->steps.is_empty());
    BLI_assert(BLI_findindex(&ustack->steps, ustack->step_active) != -1);
  }
  if (expect_non_empty) {
    BLI_assert(!ustack->steps.is_empty());
  }
}
#else
static void undosys_stack_validate(UndoStack * /*ustack*/, bool /*expect_non_empty*/) {}
#endif

UndoStack *BKE_undosys_stack_create()
{
  UndoStack *ustack = MEM_new_zeroed<UndoStack>(__func__);
  return ustack;
}

void BKE_undosys_stack_destroy(UndoStack *ustack)
{
  BKE_undosys_stack_clear(ustack);
  tab_cursors_free(ustack);
  MEM_delete(ustack);
}

void BKE_undosys_stack_clear(UndoStack *ustack)
{
  UNDO_NESTED_ASSERT(false);
  CLOG_DEBUG(&LOG, "steps=%d", ustack->steps.count());
  for (UndoStep *us = static_cast<UndoStep *>(ustack->steps.last), *us_prev; us; us = us_prev) {
    us_prev = us->prev;
    undosys_step_free_and_unlink(ustack, us);
  }
  if (UndoStep *us = ustack->step_init) {
    undosys_step_free_and_unlink(ustack, us);
    ustack->step_init = nullptr;
  }
  ustack->steps.clear_no_delete();
  ustack->step_active = nullptr;
  tab_cursors_free(ustack);
}

void BKE_undosys_stack_clear_active(UndoStack *ustack)
{
  /* Remove active and all following undo-steps. */
  UndoStep *us = ustack->step_active;

  if (us) {
    ustack->step_active = us->prev;
    bool is_not_empty = ustack->step_active != nullptr;

    while (ustack->steps.last != ustack->step_active) {
      UndoStep *us_iter = static_cast<UndoStep *>(ustack->steps.last);
      undosys_step_free_and_unlink(ustack, us_iter);
      undosys_stack_validate(ustack, is_not_empty);
    }
  }
}

/* Caller is responsible for handling active. */
static void undosys_stack_clear_all_last(UndoStack *ustack, UndoStep *us)
{
  if (us) {
    bool is_not_empty = true;
    UndoStep *us_iter;
    do {
      us_iter = static_cast<UndoStep *>(ustack->steps.last);
      BLI_assert(us_iter != ustack->step_active);
      undosys_step_free_and_unlink(ustack, us_iter);
      undosys_stack_validate(ustack, is_not_empty);
    } while (us != us_iter);
  }
}

static void undosys_stack_clear_all_first(UndoStack *ustack, UndoStep *us, UndoStep *us_exclude)
{
  if (us && us == us_exclude) {
    us = us->prev;
  }

  if (us) {
    bool is_not_empty = true;
    UndoStep *us_iter;
    do {
      us_iter = static_cast<UndoStep *>(ustack->steps.first);
      if (us_iter == us_exclude) {
        us_iter = us_iter->next;
      }
      BLI_assert(us_iter != ustack->step_active);
      undosys_step_free_and_unlink(ustack, us_iter);
      undosys_stack_validate(ustack, is_not_empty);
    } while (us != us_iter);
  }
}

static bool undosys_stack_push_main(UndoStack *ustack, const char *name, Main *bmain)
{
  UNDO_NESTED_ASSERT(false);
  BLI_assert(ustack->step_init == nullptr);
  CLOG_DEBUG(&LOG, "Push main '%s'", name);
  bContext *C_temp = CTX_create();
  CTX_data_main_set(C_temp, bmain);
  eUndoPushReturn ret = BKE_undosys_step_push_with_type(
      ustack, C_temp, name, BKE_UNDOSYS_TYPE_MEMFILE);
  CTX_free(C_temp);
  return (ret & UNDO_PUSH_RET_SUCCESS);
}

void BKE_undosys_stack_init_from_main(UndoStack *ustack, Main *bmain)
{
  UNDO_NESTED_ASSERT(false);
  undosys_stack_push_main(ustack, IFACE_("Original"), bmain);
}

void BKE_undosys_stack_init_from_context(UndoStack *ustack, bContext *C)
{
  const UndoType *ut = BKE_undosys_type_from_context(C);
  if (!ELEM(ut, nullptr, BKE_UNDOSYS_TYPE_MEMFILE)) {
    BKE_undosys_step_push_with_type(ustack, C, IFACE_("Original Mode"), ut);
  }
}

bool BKE_undosys_stack_has_undo(const UndoStack *ustack, const char *name)
{
  if (name) {
    const UndoStep *us = static_cast<UndoStep *>(
        BLI_rfindstring(&ustack->steps, name, offsetof(UndoStep, name)));
    return us && us->prev;
  }

  return !ustack->steps.is_empty();
}

bool BKE_undosys_stack_has_redo(const UndoStack *ustack)
{
  if (!ustack->step_active) {
    return false;
  }
  return ustack->step_active->next != nullptr;
}

UndoStep *BKE_undosys_stack_active_with_type(UndoStack *ustack, const UndoType *ut)
{
  UndoStep *us = ustack->step_active;
  while (us && (us->type != ut)) {
    us = us->prev;
  }
  return us;
}

UndoStep *BKE_undosys_stack_init_or_active_with_type(UndoStack *ustack, const UndoType *ut)
{
  UNDO_NESTED_ASSERT(false);
  if (ustack->step_init && (ustack->step_init->type == ut)) {
    return ustack->step_init;
  }
  return BKE_undosys_stack_active_with_type(ustack, ut);
}

/**
 * Mixar per-tab undo (M3): the step limit is per tab too. `us` is the oldest
 * step the document-wide count keeps; move it older until every tab keeps at
 * least #UNDO_TAB_MIN_STEPS of its own non-skip steps (of those that exist)
 * and no tab's cursor step is freed: a tab that walked back while other tabs
 * pushed must still find its way forward.
 */
static UndoStep *undosys_tab_limit_extend(UndoStack *ustack,
                                          UndoStep *us,
                                          Set<const UndoStep *> &r_pinned)
{
  /* The reserve and the cursor pin are for tabs that still exist: a closed
   * tab's steps age out like any other's, and its cursor entry goes, or every
   * tab closed in a session would hold its last eight steps and pin one for
   * good (review 2026-09-30, finding 2). */
  Set<uint32_t> live;
  if (G_MAIN != nullptr) {
    for (Scene &scene : G_MAIN->scenes) {
      const uint32_t tab = BKE_undo_tab_uid_for_scene(G_MAIN, &scene);
      if (tab != UNDO_TAB_DOCUMENT) {
        live.add(tab);
      }
    }
  }
  TabCursors *cursors = tab_cursors_get(ustack, false);
  if (cursors != nullptr) {
    cursors->remove_if([&](auto item) { return !live.contains(item.key); });
  }
  Map<uint32_t, int> kept;
  for (UndoStep *it = static_cast<UndoStep *>(ustack->steps.last); it != nullptr; it = it->prev) {
    if (!it->skip && it->mixar_tab_uid != UNDO_TAB_DOCUMENT && live.contains(it->mixar_tab_uid)) {
      kept.lookup_or_add(it->mixar_tab_uid, 0) += 1;
    }
    if (it == us) {
      break;
    }
  }
  for (UndoStep *it = us->prev; it != nullptr; it = it->prev) {
    bool keep = false;
    if (cursors != nullptr) {
      for (auto item : cursors->items()) {
        if (item.value == it) {
          keep = true;
        }
      }
    }
    if (!it->skip && it->mixar_tab_uid != UNDO_TAB_DOCUMENT && live.contains(it->mixar_tab_uid)) {
      int &n = kept.lookup_or_add(it->mixar_tab_uid, 0);
      if (n < UNDO_TAB_MIN_STEPS) {
        n += 1;
        keep = true;
      }
    }
    if (keep) {
      r_pinned.add(it);
      us = it;
    }
  }
  return us;
}

/**
 * Mixar per-tab undo (review 2026-10-01, R2): the reserve keeps a tab's own
 * steps and its cursor, not everything pushed after them. Upstream frees only
 * the oldest steps, so a reserve step deep in the stack used to keep every
 * later step alive: one idle tab and an agent building elsewhere grew the stack
 * without bound (undo_steps 8: 61 of 60 pushes kept). Between the reserve's
 * cutoff and the document-wide one, every memfile step the reserve does not
 * pin is freed. Only a memfile step followed by another memfile step: a mode
 * step resolves its references against the memfile before it, and freeing a
 * memfile merges its chunks into the next one (#BLO_memfile_merge), whose
 * neighbour's "identical in the future" flags the memfile type recomputes.
 */
static void undosys_tab_limit_free_between(UndoStack *ustack,
                                           UndoStep *us_from,
                                           const UndoStep *us_doc,
                                           const Set<const UndoStep *> &pinned)
{
  int freed = 0;
  UndoStep *it = us_from;
  while (it != nullptr && it != us_doc) {
    UndoStep *next = it->next;
    if (!pinned.contains(it) && it->type == BKE_UNDOSYS_TYPE_MEMFILE && next != nullptr &&
        next->type == BKE_UNDOSYS_TYPE_MEMFILE && it != ustack->step_active &&
        it != ustack->step_active_memfile && it != us_from)
    {
      undosys_step_free_and_unlink(ustack, it);
      freed++;
    }
    it = next;
  }
  if (freed > 0) {
    CLOG_DEBUG(&LOG, "per-tab limit: freed %d step(s) between the tabs' reserves", freed);
  }
}

void BKE_undosys_stack_limit_steps_and_memory(UndoStack *ustack, int steps, size_t memory_limit)
{
  UNDO_NESTED_ASSERT(false);
  if ((steps == -1) && (memory_limit == 0)) {
    return;
  }

  CLOG_DEBUG(&LOG, "Limit steps=%d, memory_limit=%zu", steps, memory_limit);
  UndoStep *us;
  UndoStep *us_exclude = nullptr;
  /* keep at least two (original + other) */
  size_t data_size_all = 0;
  size_t us_count = 0;
  for (us = static_cast<UndoStep *>(ustack->steps.last); us && us->prev; us = us->prev) {
    if (memory_limit) {
      data_size_all += us->data_size;
      if (data_size_all > memory_limit) {
        CLOG_DEBUG(&LOG,
                   "At step %zu: data_size_all=%zu >= memory_limit=%zu",
                   us_count,
                   data_size_all,
                   memory_limit);
        break;
      }
    }
    if (steps != -1) {
      if (us_count == steps) {
        break;
      }
      if (us->skip == false) {
        us_count += 1;
      }
    }
  }

  CLOG_DEBUG(&LOG, "Total steps %zu: data_size_all=%zu", us_count, data_size_all);

  UndoStep *us_doc = us;
  Set<const UndoStep *> pinned;
  if (us && BKE_undo_tabs_enabled()) {
    us = undosys_tab_limit_extend(ustack, us, pinned);
  }

  if (us) {
#ifdef WITH_GLOBAL_UNDO_KEEP_ONE
    /* Hack, we need to keep at least one BKE_UNDOSYS_TYPE_MEMFILE. */
    if (us->type != BKE_UNDOSYS_TYPE_MEMFILE) {
      us_exclude = us->prev;
      while (us_exclude && us_exclude->type != BKE_UNDOSYS_TYPE_MEMFILE) {
        us_exclude = us_exclude->prev;
      }
      /* Once this is outside the given number of 'steps', undoing onto this state
       * may skip past many undo steps which is confusing, instead,
       * disallow stepping onto this state entirely. */
      if (us_exclude) {
        us_exclude->skip = true;
      }
    }
#endif
    /* Free from first to last, free functions may update de-duplication info
     * (see #MemFileUndoStep). */
    undosys_stack_clear_all_first(ustack, us->prev, us_exclude);
    if (us != us_doc) {
      undosys_tab_limit_free_between(ustack, us, us_doc, pinned);
    }
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Undo Step
 * \{ */

UndoStep *BKE_undosys_step_push_init_with_type(UndoStack *ustack,
                                               bContext *C,
                                               const char *name,
                                               const UndoType *ut)
{
  UNDO_NESTED_ASSERT(false);
  if (ut->step_encode_init) {
    undosys_stack_validate(ustack, false);

    if (UndoStep *us = ustack->step_init) {
      undosys_step_free_and_unlink(ustack, us);
      ustack->step_init = nullptr;
    }
    if (ustack->step_active) {
      undosys_stack_clear_all_last(ustack, ustack->step_active->next);
    }

    UndoStep *us = static_cast<UndoStep *>(MEM_new_zeroed(ut->step_size, __func__));
    if (name != nullptr) {
      STRNCPY(us->name, name);
    }
    us->type = ut;
    ustack->step_init = us;
    CLOG_INFO(&LOG, "Initialize type='%s'", ut->name);
    CLOG_DEBUG(&LOG, "addr=%p, name='%s', type='%s'", us, us->name, us->type->name);
    ut->step_encode_init(C, us);
    undosys_stack_validate(ustack, false);
    return us;
  }

  return nullptr;
}

UndoStep *BKE_undosys_step_push_init(UndoStack *ustack, bContext *C, const char *name)
{
  UNDO_NESTED_ASSERT(false);
  const UndoType *ut = BKE_undosys_type_from_context(C);
  if (ut == nullptr) {
    return nullptr;
  }
  return BKE_undosys_step_push_init_with_type(ustack, C, name, ut);
}

eUndoPushReturn BKE_undosys_step_push_with_type(UndoStack *ustack,
                                                bContext *C,
                                                const char *name,
                                                const UndoType *ut)
{
  BLI_assert((ut->flags & UNDOTYPE_FLAG_NEED_CONTEXT_FOR_ENCODE) == 0 || C != nullptr);

  UNDO_NESTED_ASSERT(false);
  undosys_stack_validate(ustack, false);
  bool is_not_empty = ustack->step_active != nullptr;
  eUndoPushReturn retval = UNDO_PUSH_RET_FAILURE;

  /* Might not be final place for this to be called - probably only want to call it from some
   * undo handlers, not all of them? */
  eRNAOverrideMatchResult report_flags = RNA_OVERRIDE_MATCH_RESULT_INIT;
  BKE_lib_override_library_main_operations_create(
      G_MAIN, false, reinterpret_cast<int *>(&report_flags));
  if (report_flags & RNA_OVERRIDE_MATCH_RESULT_CREATED) {
    retval |= UNDO_PUSH_RET_OVERRIDE_CHANGED;
  }

  /* Remove all undo-steps after (also when 'ustack->step_active == nullptr'). */
  while (ustack->steps.last != ustack->step_active) {
    UndoStep *us_iter = static_cast<UndoStep *>(ustack->steps.last);
    undosys_step_free_and_unlink(ustack, us_iter);
    undosys_stack_validate(ustack, is_not_empty);
  }

  if (ustack->step_active) {
    BLI_assert(BLI_findindex(&ustack->steps, ustack->step_active) != -1);
  }

#ifdef WITH_GLOBAL_UNDO_ENSURE_UPDATED
  if (ut->step_foreach_ID_ref != nullptr) {
    if (G_MAIN->is_memfile_undo_written == false) {
      const char *name_internal = "MemFile Internal (pre)";
      /* Don't let 'step_init' cause issues when adding memfile undo step. */
      void *step_init = ustack->step_init;
      ustack->step_init = nullptr;
      const bool ok = undosys_stack_push_main(ustack, name_internal, G_MAIN);
      /* Restore 'step_init'. */
      ustack->step_init = static_cast<UndoStep *>(step_init);
      if (ok) {
        UndoStep *us = static_cast<UndoStep *>(ustack->steps.last);
        BLI_assert(STREQ(us->name, name_internal));
        us->skip = true;
#  ifdef WITH_GLOBAL_UNDO_CORRECT_ORDER
        ustack->step_active_memfile = us;
#  endif
      }
    }
  }
#endif

  bool use_memfile_step = false;
  {
    UndoStep *us = ustack->step_init ?
                       ustack->step_init :
                       static_cast<UndoStep *>(MEM_new_zeroed(ut->step_size, __func__));
    ustack->step_init = nullptr;
    if (us->name[0] == '\0') {
      STRNCPY(us->name, name);
    }
    us->type = ut;
    /* True by default, code needs to explicitly set it to false if necessary. */
    us->use_old_bmain_data = true;
    /* Initialized, not added yet. */

    CLOG_DEBUG(&LOG, "addr=%p, name='%s', type='%s'", us, us->name, us->type->name);

    if (!undosys_step_encode(C, G_MAIN, ustack, us)) {
      MEM_delete(us);
      undosys_stack_validate(ustack, true);
      return retval;
    }
    /* Mixar: tag the step with its tab; an internal push (no window in the
     * context) inherits the tab of the step it follows. */
    BKE_undo_step_tab_annotate(us, C, G_MAIN, ustack->step_active);
    /* A push in a tab whose cursor is behind: that tab's redo branch dies
     * (its newer steps lose the tag, they still carry the other tabs'
     * history) and the tab is at the top again. */
    if (TabCursors *cursors = tab_cursors_get(ustack, false)) {
      if (UndoStep **cursor = cursors->lookup_ptr(us->mixar_tab_uid)) {
        for (UndoStep *it = (*cursor)->next; it != nullptr; it = it->next) {
          if (it->mixar_tab_uid == us->mixar_tab_uid) {
            /* The tab's dead redo branch: no tab walks it, and the
             * document-wide walk must not either (the campaign of 09-30: Undo
             * Whole Document stepped into a state the tab had discarded), so
             * it is a skip step from here on. Its memfile stays in the chain
             * for the steps above it. */
            it->mixar_tab_uid = UNDO_TAB_DOCUMENT;
            it->skip = true;
          }
        }
        cursors->remove(us->mixar_tab_uid);
      }
    }
    us->mixar_cursors = tab_cursors_snapshot(ustack);
    BKE_undo_tabs_note_push(); /* the live document is this step's state again */
    ustack->step_active = us;
    BLI_addtail(&ustack->steps, us);
    use_memfile_step = us->use_memfile_step;
  }

  if (use_memfile_step) {
    /* Make this the user visible undo state, so redo always applies
     * on top of the mem-file undo instead of skipping it. see: #67256. */
    UndoStep *us_prev = ustack->step_active;
    const char *name_internal = us_prev->name;
    const bool ok = undosys_stack_push_main(ustack, name_internal, G_MAIN);
    if (ok) {
      UndoStep *us = static_cast<UndoStep *>(ustack->steps.last);
      BLI_assert(STREQ(us->name, name_internal));
      /* The inner push tagged and snapshotted the memfile step already; only
       * the tab is corrected to the mode step's (review of #1746: a second
       * snapshot here leaked the first). */
      us->mixar_tab_uid = us_prev->mixar_tab_uid;
      us_prev->skip = true;
#ifdef WITH_GLOBAL_UNDO_CORRECT_ORDER
      ustack->step_active_memfile = us;
#endif
      ustack->step_active = us;
    }
  }

  if (ustack->group_level > 0) {
    /* Temporarily set skip for the active step.
     * This is an invalid state which must be corrected once the last group ends. */
    ustack->step_active->skip = true;
  }

  undosys_stack_validate(ustack, true);
  return (retval | UNDO_PUSH_RET_SUCCESS);
}

eUndoPushReturn BKE_undosys_step_push(UndoStack *ustack, bContext *C, const char *name)
{
  UNDO_NESTED_ASSERT(false);
  const UndoType *ut = ustack->step_init ? ustack->step_init->type :
                                           BKE_undosys_type_from_context(C);
  if (ut == nullptr) {
    return UNDO_PUSH_RET_FAILURE;
  }
  return BKE_undosys_step_push_with_type(ustack, C, name, ut);
}

UndoStep *BKE_undosys_step_same_type_next(UndoStep *us)
{
  if (us) {
    const UndoType *ut = us->type;
    while ((us = us->next)) {
      if (us->type == ut) {
        return us;
      }
    }
  }
  return us;
}

UndoStep *BKE_undosys_step_same_type_prev(UndoStep *us)
{
  if (us) {
    const UndoType *ut = us->type;
    while ((us = us->prev)) {
      if (us->type == ut) {
        return us;
      }
    }
  }
  return us;
}

UndoStep *BKE_undosys_step_find_by_name_with_type(UndoStack *ustack,
                                                  const char *name,
                                                  const UndoType *ut)
{
  for (UndoStep &us : ustack->steps.items_reversed()) {
    if (us.type == ut) {
      if (STREQ(name, us.name)) {
        return &us;
      }
    }
  }
  return nullptr;
}

UndoStep *BKE_undosys_step_find_by_name(UndoStack *ustack, const char *name)
{
  return static_cast<UndoStep *>(BLI_rfindstring(&ustack->steps, name, offsetof(UndoStep, name)));
}

UndoStep *BKE_undosys_step_find_by_type(UndoStack *ustack, const UndoType *ut)
{
  for (UndoStep &us : ustack->steps.items_reversed()) {
    if (us.type == ut) {
      return &us;
    }
  }
  return nullptr;
}

eUndoStepDir BKE_undosys_step_calc_direction(const UndoStack *ustack,
                                             const UndoStep *us_target,
                                             const UndoStep *us_reference)
{
  if (us_reference == nullptr) {
    us_reference = ustack->step_active;
  }

  BLI_assert(us_reference != nullptr);

  /* Note that we use heuristics to make this lookup as fast as possible in most common cases,
   * assuming that:
   *  - Most cases are just undo or redo of one step from active one.
   *  - Otherwise, it is typically faster to check future steps since active one is usually close
   *    to the end of the list, rather than its start. */
  /* NOTE: in case target step is the active one, we assume we are in an undo case... */
  if (ELEM(us_target, us_reference, us_reference->prev)) {
    return STEP_UNDO;
  }
  if (us_target == us_reference->next) {
    return STEP_REDO;
  }

  /* Search forward, and then backward. */
  for (UndoStep *us_iter = us_reference->next; us_iter != nullptr; us_iter = us_iter->next) {
    if (us_iter == us_target) {
      return STEP_REDO;
    }
  }
  for (UndoStep *us_iter = us_reference->prev; us_iter != nullptr; us_iter = us_iter->prev) {
    if (us_iter == us_target) {
      return STEP_UNDO;
    }
  }

  BLI_assert_msg(0,
                 "Target undo step not found, this should not happen and may indicate an undo "
                 "stack corruption");
  return STEP_INVALID;
}

/**
 * When reading undo steps for undo/redo,
 * some extra checks are needed when so the correct undo step is decoded.
 */
static UndoStep *undosys_step_iter_first(UndoStep *us_reference, const eUndoStepDir undo_dir)
{
  if (us_reference->type->flags & UNDOTYPE_FLAG_DECODE_ACTIVE_STEP) {
    /* Reading this step means an undo action reads undo twice.
     * This should be avoided where possible, however some undo systems require it.
     *
     * Redo skips the current state as this represents the currently loaded state. */
    return (undo_dir == -1) ? us_reference : us_reference->next;
  }

  /* Typical case, skip reading the current undo step. */
  return (undo_dir == -1) ? us_reference->prev : us_reference->next;
}

bool BKE_undosys_step_load_data_ex(UndoStack *ustack,
                                   bContext *C,
                                   UndoStep *us_target,
                                   UndoStep *us_reference,
                                   const bool use_skip)
{
  UNDO_NESTED_ASSERT(false);
  if (us_target == nullptr) {
    CLOG_ERROR(&LOG, "called with a nullptr target step");
    return false;
  }
  undosys_stack_validate(ustack, true);

  if (us_reference == nullptr) {
    us_reference = ustack->step_active;
  }
  if (us_reference == nullptr) {
    CLOG_ERROR(&LOG, "could not find a valid initial active target step as reference");
    return false;
  }

  /* This considers we are in undo case if both `us_target` and `us_reference` are the same. */
  const eUndoStepDir undo_dir = BKE_undosys_step_calc_direction(ustack, us_target, us_reference);
  BLI_assert(undo_dir != STEP_INVALID);

  /* This will be the active step once the undo process is complete.
   *
   * In case we do skip 'skipped' steps, the final active step may be several steps backward from
   * the one passed as parameter. */
  UndoStep *us_target_active = us_target;
  if (use_skip) {
    while (us_target_active != nullptr && us_target_active->skip) {
      us_target_active = (undo_dir == -1) ? us_target_active->prev : us_target_active->next;
    }
    if (us_target_active == nullptr) {
      CLOG_DEBUG(&LOG,
                 "undo/redo did not find a step after stepping over skip-steps "
                 "(undo limit exceeded)");
      return false;
    }
  }

  CLOG_DEBUG(&LOG,
             "addr=%p, name='%s', type='%s', undo_dir=%d",
             us_target,
             us_target->name,
             us_target->type->name,
             undo_dir);

  /* Mixar per-tab undo (M5): a document-wide walk after tab walks. The live
   * document is not the active step's state, so the reader's identical-chunk
   * shortcut cannot be trusted for any tab: re-read every ID (in place where it
   * still lives). Armed here for Undo Whole Document and for the classic walk
   * after the runtime kill switch alike. */
  const bool reread_all = BKE_undo_tabs_live_diverged() && !BKE_undo_tabs_partial_active();
  if (!BKE_undo_tabs_partial_active()) {
    BKE_undo_tabs_note_document_walk(); /* a document-wide walk, flag on or off */
  }
  if (reread_all) {
    BKE_undo_tabs_whole_document_begin();
  }
  BLI_SCOPED_DEFER([&]() {
    if (reread_all) {
      BKE_undo_tabs_partial_end();
      BKE_undo_tabs_note_push(); /* the live document is the target's state now */
    }
    /* Every tab now stands where it stood when the reached step was written:
     * its cursor snapshot says so. Restored after every document-wide walk,
     * flag on or off, so the cursors agree with the live document the moment
     * per-tab undo is (re)enabled (the isolation scenario's kill-switch block:
     * a classic undo with the flag off, then the flag back on, then per-tab
     * redos that must reach every tab's top). */
    BKE_undosys_tab_cursors_restore(ustack, ustack->step_active);
  });

  /* Undo/Redo steps until we reach given target step (or beyond if it has to be skipped),
   * from given reference step. */
  bool is_processing_extra_skipped_steps = false;
  UndoStep *us_first = undosys_step_iter_first(us_reference, undo_dir);
  if (reread_all && undo_dir == STEP_UNDO && us_first == us_reference &&
      us_reference->is_applied == false)
  {
    /* Mixar per-tab undo (M5): a type that decodes its active step on undo
     * (sculpt, paint, text) whose active step a tab walk already un-applied.
     * Decoding it again would apply the undo delta twice (the sculpt node
     * swaps coordinates); the full re-read of the target replaces every ID
     * anyway. */
    us_first = us_reference->prev;
  }
  for (UndoStep *us_iter = us_first; us_iter != nullptr;
       us_iter = (undo_dir == -1) ? us_iter->prev : us_iter->next)
  {
    BLI_assert(us_iter != nullptr);

    const bool is_final = (us_iter == us_target_active);

    if (!is_final && is_processing_extra_skipped_steps) {
      BLI_assert(us_iter->skip == true);
      CLOG_DEBUG(&LOG,
                 "undo/redo continue with skip addr=%p, name='%s', type='%s'",
                 us_iter,
                 us_iter->name,
                 us_iter->type->name);
    }

    undosys_step_decode(C, G_MAIN, ustack, us_iter, undo_dir, is_final);
    ustack->step_active = us_iter;

    if (us_iter == us_target) {
      is_processing_extra_skipped_steps = true;
    }

    if (is_final) {
      /* Undo/Redo process is finished and successful. */
      return true;
    }
  }

  BLI_assert_msg(
      false,
      "This should never be reached, either undo stack is corrupted, or code above is buggy");
  return false;
}

bool BKE_undosys_step_load_data(UndoStack *ustack, bContext *C, UndoStep *us_target)
{
  /* Note that here we do not skip 'skipped' steps by default. */
  return BKE_undosys_step_load_data_ex(ustack, C, us_target, nullptr, false);
}

void BKE_undosys_step_load_from_index(UndoStack *ustack, bContext *C, const int index)
{
  UndoStep *us_target = static_cast<UndoStep *>(BLI_findlink(&ustack->steps, index));
  BLI_assert(us_target->skip == false);
  if (us_target == ustack->step_active) {
    return;
  }
  BKE_undosys_step_load_data(ustack, C, us_target);
}

bool BKE_undosys_step_undo_with_data_ex(UndoStack *ustack,
                                        bContext *C,
                                        UndoStep *us_target,
                                        bool use_skip)
{
  /* In case there is no active step, we consider we just load given step, so reference must be
   * itself (due to weird 'load current active step in undo case' thing, see comments in
   * #BKE_undosys_step_load_data_ex). */
  UndoStep *us_reference = ustack->step_active != nullptr ? ustack->step_active : us_target;

  BLI_assert(BKE_undosys_step_calc_direction(ustack, us_target, us_reference) == -1);

  return BKE_undosys_step_load_data_ex(ustack, C, us_target, us_reference, use_skip);
}

bool BKE_undosys_step_undo_with_data(UndoStack *ustack, bContext *C, UndoStep *us_target)
{
  return BKE_undosys_step_undo_with_data_ex(ustack, C, us_target, true);
}

bool BKE_undosys_step_undo(UndoStack *ustack, bContext *C)
{
  if (ustack->step_active != nullptr) {
    return BKE_undosys_step_undo_with_data(ustack, C, ustack->step_active->prev);
  }
  return false;
}

bool BKE_undosys_step_redo_with_data_ex(UndoStack *ustack,
                                        bContext *C,
                                        UndoStep *us_target,
                                        bool use_skip)
{
  /* In case there is no active step, we consider we just load given step, so reference must be
   * the previous one. */
  UndoStep *us_reference = ustack->step_active != nullptr ? ustack->step_active : us_target->prev;

  BLI_assert(BKE_undosys_step_calc_direction(ustack, us_target, us_reference) == 1);

  return BKE_undosys_step_load_data_ex(ustack, C, us_target, us_reference, use_skip);
}

bool BKE_undosys_step_redo_with_data(UndoStack *ustack, bContext *C, UndoStep *us_target)
{
  return BKE_undosys_step_redo_with_data_ex(ustack, C, us_target, true);
}

bool BKE_undosys_step_redo(UndoStack *ustack, bContext *C)
{
  if (ustack->step_active != nullptr) {
    return BKE_undosys_step_redo_with_data(ustack, C, ustack->step_active->next);
  }
  return false;
}

/* -------------------------------------------------------------------- */
/** \name Mixar per-tab walk (M2)
 * \{ */

/** The newest step tagged with the tab at or below the document's active step:
 * where a tab with no cursor entry stands (its state is that step's). */
static UndoStep *undosys_tab_newest_step(UndoStack *ustack, const uint32_t tab_uid)
{
  for (UndoStep *us = ustack->step_active; us != nullptr; us = us->prev) {
    if (!us->skip && us->mixar_tab_uid == tab_uid) {
      return us;
    }
  }
  return nullptr;
}

UndoStep *BKE_undosys_tab_cursor(UndoStack *ustack, const uint32_t tab_uid)
{
  if (TabCursors *cursors = tab_cursors_get(ustack, false)) {
    if (UndoStep **cursor = cursors->lookup_ptr(tab_uid)) {
      return *cursor;
    }
  }
  return undosys_tab_newest_step(ustack, tab_uid);
}

/** The tab's next own step after ``ref``: its redo target. After a whole-document
 * undo (M4) a tab with no cursor entry still has redo when its steps sit above
 * the document's active step. */
static UndoStep *undosys_tab_next_step(const UndoStack *ustack, const UndoStep *ref, const uint32_t tab_uid)
{
  /* No cursor and no own step at or below the document's active step (a
   * whole-document walk went past the tab's first step): every step of the
   * tab sits above the active step, and the first of them is the redo target
   * (review of #1746). */
  UndoStep *start = nullptr;
  if (ref != nullptr) {
    start = ref->next;
  }
  else if (ustack->step_active != nullptr) {
    start = ustack->step_active->next;
  }
  else {
    start = static_cast<UndoStep *>(ustack->steps.first);
  }
  for (UndoStep *us = start; us != nullptr; us = us->next) {
    if (!us->skip && us->mixar_tab_uid == tab_uid) {
      return us;
    }
  }
  return nullptr;
}

bool BKE_undosys_tab_has_redo(UndoStack *ustack, const uint32_t tab_uid)
{
  return undosys_tab_next_step(ustack, BKE_undosys_tab_cursor(ustack, tab_uid), tab_uid) != nullptr;
}

bool BKE_undosys_tab_has_undo(UndoStack *ustack, const uint32_t tab_uid)
{
  const UndoStep *ref = BKE_undosys_tab_cursor(ustack, tab_uid);
  for (const UndoStep *us = ref ? ref->prev : nullptr; us != nullptr; us = us->prev) {
    if (!us->skip && us->mixar_tab_uid == tab_uid) {
      return true;
    }
  }
  return false;
}

void BKE_undosys_tab_cursors_clear(UndoStack *ustack)
{
  if (TabCursors *cursors = tab_cursors_get(ustack, false)) {
    cursors->clear();
  }
}

void BKE_undosys_tab_cursors_restore(UndoStack *ustack, const UndoStep *from)
{
  BKE_undosys_tab_cursors_clear(ustack);
  const TabCursors *snapshot = from ? static_cast<const TabCursors *>(from->mixar_cursors) : nullptr;
  if (snapshot == nullptr || snapshot->is_empty()) {
    return;
  }
  TabCursors *cursors = tab_cursors_get(ustack, true);
  for (auto item : snapshot->items()) {
    if (BLI_findindex(&ustack->steps, item.value) != -1) {
      cursors->add_overwrite(item.key, item.value);
    }
  }
}

static bool undosys_tab_step_is_global(const UndoStep *us)
{
  return us->type != nullptr && STREQ(us->type->name, "Global Undo");
}

/**
 * Decode one step for a tab. A memfile step is a partial restore of the tab's
 * datablocks. A mode step (edit mesh, sculpt, paint, text; M3) names the
 * datablocks it touches: it is applied as today once they are all the tab's,
 * WITHOUT the #WITH_GLOBAL_UNDO_CORRECT_ORDER memfile preload (that reload of
 * the previous memfile would restore every tab; the references resolve by
 * name against the live document, which is the tab's current state).
 */
static bool undosys_tab_step_decode(UndoStack *ustack,
                                    bContext *C,
                                    const uint32_t tab_uid,
                                    UndoStep *target,
                                    const eUndoStepDir dir,
                                    const bool is_final,
                                    std::string *r_reason)
{
  CLOG_DEBUG(&LOG,
             "tab %u %s to addr=%p name='%s' type='%s'",
             tab_uid,
             dir == STEP_UNDO ? "undo" : "redo",
             static_cast<void *>(target),
             target->name,
             target->type->name);
  if (!undosys_tab_step_is_global(target)) {
    Vector<ID *> refs;
    if (target->type->step_foreach_ID_ref) {
      target->type->step_foreach_ID_ref(target, undosys_id_ref_resolve, G_MAIN);
      target->type->step_foreach_ID_ref(
          target,
          [](void *user_data, UndoRefID *id_ref) {
            static_cast<Vector<ID *> *>(user_data)->append(id_ref->ptr);
          },
          &refs);
    }
    if (!BKE_undo_tabs_ids_owned(G_MAIN, tab_uid, refs, r_reason)) {
      return false;
    }
    UNDO_NESTED_CHECK_BEGIN;
    target->type->step_decode(C, G_MAIN, target, dir, is_final);
    UNDO_NESTED_CHECK_END;
    return true;
  }
  if (!BKE_undo_tabs_partial_begin(G_MAIN, tab_uid, target->mixar_owners, r_reason)) {
    return false;
  }
  undosys_step_decode(C, G_MAIN, ustack, target, dir, is_final);
  BKE_undo_tabs_partial_end();
  return true;
}

/**
 * Would #undosys_tab_step_decode accept ``target``? The same checks, none of
 * the work: a mode step's datablocks must be the tab's or global, a memfile
 * step's owner maps must hold nothing shared or moved. Asked before an active
 * step (sculpt, paint, text) is decoded on the way to ``target``, so a refusal
 * never leaves that step half-undone (review of #1746).
 */
static bool undosys_tab_step_check(bContext * /*C*/,
                                   const uint32_t tab_uid,
                                   UndoStep *target,
                                   std::string *r_reason)
{
  if (!undosys_tab_step_is_global(target)) {
    Vector<ID *> refs;
    if (target->type->step_foreach_ID_ref) {
      target->type->step_foreach_ID_ref(target, undosys_id_ref_resolve, G_MAIN);
      target->type->step_foreach_ID_ref(
          target,
          [](void *user_data, UndoRefID *id_ref) {
            static_cast<Vector<ID *> *>(user_data)->append(id_ref->ptr);
          },
          &refs);
    }
    return BKE_undo_tabs_ids_owned(G_MAIN, tab_uid, refs, r_reason);
  }
  return BKE_undo_tabs_partial_check(G_MAIN, tab_uid, target->mixar_owners, r_reason);
}

static bool undosys_tab_step_apply(UndoStack *ustack,
                                   bContext *C,
                                   const uint32_t tab_uid,
                                   UndoStep *target,
                                   const eUndoStepDir dir,
                                   std::string *r_reason)
{
  if (!undosys_tab_step_decode(ustack, C, tab_uid, target, dir, true, r_reason)) {
    return false;
  }
  BKE_undo_tabs_note_tab_walk();
  TabCursors *cursors = tab_cursors_get(ustack, true);
  /* Back on its newest step, the tab is at the top again: no cursor entry. */
  if (target == undosys_tab_newest_step(ustack, tab_uid)) {
    cursors->remove(tab_uid);
  }
  else {
    cursors->add_overwrite(tab_uid, target);
  }
  return true;
}

bool BKE_undosys_tab_step_undo(UndoStack *ustack, bContext *C, const uint32_t tab_uid, std::string *r_reason)
{
  /* The cursor is the tab's step whose memfile holds the state the tab shows
   * now; undo restores the tab from the tagged step before it (a memfile step
   * holds the state AFTER its operator ran, so "one step back" for the tab is
   * the previous step it pushed). */
  UndoStep *ref = BKE_undosys_tab_cursor(ustack, tab_uid);
  if (ref == nullptr) {
    if (r_reason) {
      *r_reason = "nothing to undo in this tab";
    }
    return false;
  }
  for (UndoStep *us = ref->prev; us != nullptr; us = us->prev) {
    if (us->skip || us->mixar_tab_uid != tab_uid) {
      continue;
    }
    /* Some mode steps (sculpt, paint, text) undo by decoding THEMSELVES in
     * the undo direction before the step beneath is read, as
     * #undosys_step_iter_first does for the document walk. */
    if (ref->type->flags & UNDOTYPE_FLAG_DECODE_ACTIVE_STEP) {
      /* The step beneath must be acceptable BEFORE the active step is
       * un-applied: a refusal after that would leave the active step
       * half-undone and the next press would apply its delta twice. */
      if (!undosys_tab_step_check(C, tab_uid, us, r_reason)) {
        return false;
      }
      if (!undosys_tab_step_decode(ustack, C, tab_uid, ref, STEP_UNDO, false, r_reason)) {
        return false;
      }
    }
    return undosys_tab_step_apply(ustack, C, tab_uid, us, STEP_UNDO, r_reason);
  }
  if (r_reason) {
    *r_reason = "nothing to undo in this tab";
  }
  return false;
}

bool BKE_undosys_tab_step_redo(UndoStack *ustack, bContext *C, const uint32_t tab_uid, std::string *r_reason)
{
  UndoStep *target = undosys_tab_next_step(ustack, BKE_undosys_tab_cursor(ustack, tab_uid), tab_uid);
  if (target == nullptr) {
    if (r_reason) {
      *r_reason = "nothing to redo in this tab";
    }
    return false;
  }
  return undosys_tab_step_apply(ustack, C, tab_uid, target, STEP_REDO, r_reason);
}

bool BKE_undosys_tab_step_check(UndoStack *ustack,
                                bContext *C,
                                const uint32_t tab_uid,
                                const eUndoStepDir dir,
                                std::string *r_reason)
{
  UndoStep *ref = BKE_undosys_tab_cursor(ustack, tab_uid);
  if (dir == STEP_REDO) {
    UndoStep *target = undosys_tab_next_step(ustack, ref, tab_uid);
    if (target == nullptr) {
      if (r_reason) {
        *r_reason = "nothing to redo in this tab";
      }
      return false;
    }
    return undosys_tab_step_check(C, tab_uid, target, r_reason);
  }
  for (UndoStep *us = ref ? ref->prev : nullptr; us != nullptr; us = us->prev) {
    if (us->skip || us->mixar_tab_uid != tab_uid) {
      continue;
    }
    if ((ref->type->flags & UNDOTYPE_FLAG_DECODE_ACTIVE_STEP) &&
        !undosys_tab_step_check(C, tab_uid, ref, r_reason))
    {
      return false;
    }
    return undosys_tab_step_check(C, tab_uid, us, r_reason);
  }
  if (r_reason) {
    *r_reason = "nothing to undo in this tab";
  }
  return false;
}

bool BKE_undosys_tab_step_load(
    UndoStack *ustack, bContext *C, const uint32_t tab_uid, UndoStep *target, std::string *r_reason)
{
  if (target == nullptr || target->skip || target->mixar_tab_uid != tab_uid) {
    if (r_reason) {
      *r_reason = "that step is not this tab's";
    }
    return false;
  }
  UndoStep *cursor = BKE_undosys_tab_cursor(ustack, tab_uid);
  if (cursor == target) {
    if (r_reason) {
      *r_reason = "this tab is already at that step";
    }
    return false;
  }
  const eUndoStepDir dir = (cursor != nullptr &&
                            BLI_findindex(&ustack->steps, target) <
                                BLI_findindex(&ustack->steps, cursor)) ?
                               STEP_UNDO :
                               STEP_REDO;
  /* One tagged step at a time: mode steps need their neighbours applied in
   * order, and each memfile step is a complete restore of the tab anyway. */
  int guard = BLI_listbase_count(&ustack->steps) + 1;
  while (BKE_undosys_tab_cursor(ustack, tab_uid) != target) {
    if (--guard < 0) {
      if (r_reason) {
        *r_reason = "the walk did not reach that step";
      }
      return false;
    }
    const bool ok = (dir == STEP_UNDO) ? BKE_undosys_tab_step_undo(ustack, C, tab_uid, r_reason) :
                                         BKE_undosys_tab_step_redo(ustack, C, tab_uid, r_reason);
    if (!ok) {
      return false;
    }
  }
  return true;
}

/** \} */

UndoType *BKE_undosys_type_append(void (*undosys_fn)(UndoType *))
{
  UndoType *ut = MEM_new_zeroed<UndoType>(__func__);

  undosys_fn(ut);

  BLI_addtail(&g_undo_types, ut);

  return ut;
}

void BKE_undosys_type_free_all()
{
  while (UndoType *ut = static_cast<UndoType *>(BLI_pophead(&g_undo_types))) {
    MEM_delete(ut);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Undo Stack Grouping
 *
 * This enables skip while group-level is set.
 * In general it's not allowed that #UndoStack.step_active have 'skip' enabled.
 *
 * This rule is relaxed for grouping, however it's important each call to
 * #BKE_undosys_stack_group_begin has a matching #BKE_undosys_stack_group_end.
 *
 * - Levels are used so nesting is supported, where the last call to #BKE_undosys_stack_group_end
 *   will set the active undo step that should not be skipped.
 *
 * - Correct begin/end is checked by an assert since any errors here will cause undo
 *   to consider all steps part of one large group.
 *
 * - Calls to begin/end with no undo steps being pushed is supported and does nothing.
 *
 * \{ */

void BKE_undosys_stack_group_begin(UndoStack *ustack)
{
  BLI_assert(ustack->group_level >= 0);
  ustack->group_level += 1;
}

void BKE_undosys_stack_group_end(UndoStack *ustack)
{
  ustack->group_level -= 1;
  BLI_assert(ustack->group_level >= 0);

  if (ustack->group_level == 0) {
    if (LIKELY(ustack->step_active != nullptr)) {
      ustack->step_active->skip = false;
    }
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name ID Reference Utilities
 *
 * Unfortunately we need this for a handful of places.
 * \{ */

static void UNUSED_FUNCTION(BKE_undosys_foreach_ID_ref(UndoStack *ustack,
                                                       UndoTypeForEachIDRefFn foreach_ID_ref_fn,
                                                       void *user_data))
{
  for (UndoStep &us : ustack->steps) {
    const UndoType *ut = us.type;
    if (ut->step_foreach_ID_ref != nullptr) {
      ut->step_foreach_ID_ref(&us, foreach_ID_ref_fn, user_data);
    }
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Debug Helpers
 * \{ */

void BKE_undosys_print(UndoStack *ustack)
{
  if (!ustack) {
    printf("No undo steps recorded yet.\n");
    return;
  }
  printf("Undo %d Steps (*: active, #=applied, M=memfile-active, S=skip)\n",
         ustack->steps.count());
  int index = 0;
  for (UndoStep &us : ustack->steps) {
    printf("[%c%c%c%c] %3d {%p} type='%s', name='%s', tab=%u, owners=%d\n",
           (&us == ustack->step_active) ? '*' : ' ',
           us.is_applied ? '#' : ' ',
           (&us == ustack->step_active_memfile) ? 'M' : ' ',
           us.skip ? 'S' : ' ',
           index,
           static_cast<void *>(&us),
           us.type->name,
           us.name,
           us.mixar_tab_uid,
           BKE_undo_owner_map_size(us.mixar_owners));
    index++;
  }
}

/** \} */

}  // namespace blender
