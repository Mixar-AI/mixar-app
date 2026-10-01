/* SPDX-FileCopyrightText: 2004 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edundo
 */

#include <cstring>

#include "CLG_log.h"

#include "DNA_object_types.h"
#include "DNA_scene_types.h"

#include "BLI_listbase.h"
#include "BLI_utildefines.h"

#include "BKE_blender_undo.hh"
#include "BKE_callbacks.hh"
#include "BKE_context.hh"
#include "BKE_global.hh"
#include "BKE_layer.hh"
#include "BKE_main.hh"
#include "BKE_paint.hh"
#include "BKE_report.hh"
#include "BKE_scene.hh"
#include "BKE_screen.hh"
#include "BKE_undo_system.hh"
#include "BKE_undo_tabs.hh"
#include "BLI_map.hh"
#include "BLI_set.hh"
#include "BLI_vector.hh"
#include "BLT_translation.hh"
#include "ED_mixar_undo.hh"
#include "UI_interface_icons.hh"

#include <string>
#include "BKE_workspace.hh"

#include "BLO_blend_validate.hh"

#include "ED_asset.hh"
#include "ED_gpencil_legacy.hh"
#include "ED_object.hh"
#include "ED_outliner.hh"
#include "ED_render.hh"
#include "ED_screen.hh"
#include "ED_sculpt.hh"
#include "ED_undo.hh"

#include "WM_api.hh"
#include "WM_toolsystem.hh"
#include "WM_types.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"
#include "RNA_enum_types.hh"

namespace blender {

/** We only need this locally. */
static CLG_LogRef LOG = {"undo"};

/* -------------------------------------------------------------------- */
/** \name Generic Undo System Access
 *
 * Non-operator undo editor functions.
 * \{ */

bool ED_undo_is_state_valid(bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);

  /* Currently only checks matching begin/end calls. */
  if (wm->runtime->undo_stack == nullptr) {
    /* No undo stack is valid, nothing to do. */
    return true;
  }
  if (wm->runtime->undo_stack->group_level != 0) {
    /* If this fails #ED_undo_grouped_begin, #ED_undo_grouped_end calls don't match. */
    return false;
  }
  if (wm->runtime->undo_stack->step_active != nullptr) {
    if (wm->runtime->undo_stack->step_active->skip == true) {
      /* Skip is only allowed between begin/end calls,
       * a state that should never happen in main event loop. */
      return false;
    }
  }
  return true;
}

void ED_undo_group_begin(bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  BKE_undosys_stack_group_begin(wm->runtime->undo_stack);
}

void ED_undo_group_end(bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  BKE_undosys_stack_group_end(wm->runtime->undo_stack);
}

/* Mixar: `type` forces the step type (a tab checkpoint is a memfile step
 * whatever the context is in), nullptr keeps the context's choice. */
static eUndoPushReturn ed_undo_push_ex(bContext *C, const char *str, const UndoType *type)
{
  CLOG_INFO(&LOG, "Push '%s'", str);
  WM_file_tag_modified();

  wmWindowManager *wm = CTX_wm_manager(C);
  if (G.background) {
    /* Python developers may have explicitly created the undo stack in background mode,
     * otherwise allow it to be nullptr, see: #60934.
     * Otherwise it must never be nullptr, even when undo is disabled. */
    if (wm->runtime->undo_stack == nullptr) {
      return UNDO_PUSH_RET_FAILURE;
    }
  }

  int steps = U.undosteps;

  /* Ensure steps that have been initialized are always pushed,
   * even when undo steps are zero.
   *
   * Note that some modes (paint, sculpt) initialize an undo step before an action runs,
   * then accumulate changes there, or restore data from it in the case of 2D painting.
   *
   * For this reason we need to handle the undo step even when undo steps is set to zero.
   */
  if ((steps <= 0) && wm->runtime->undo_stack->step_init != nullptr) {
    steps = 1;
  }
  if (steps <= 0) {
    return UNDO_PUSH_RET_FAILURE;
  }

  eUndoPushReturn push_retval;

  /* Only apply limit if this is the last undo step. */
  if (wm->runtime->undo_stack->step_active &&
      (wm->runtime->undo_stack->step_active->next == nullptr))
  {
    BKE_undosys_stack_limit_steps_and_memory(wm->runtime->undo_stack, steps - 1, 0);
  }

  /* A step a mode initialised (sculpt, paint) keeps its own type. */
  push_retval = (type != nullptr && wm->runtime->undo_stack->step_init == nullptr) ?
                    BKE_undosys_step_push_with_type(wm->runtime->undo_stack, C, str, type) :
                    BKE_undosys_step_push(wm->runtime->undo_stack, C, str);

  if (U.undomemory != 0) {
    const size_t memory_limit = size_t(U.undomemory) * 1024 * 1024;
    BKE_undosys_stack_limit_steps_and_memory(wm->runtime->undo_stack, -1, memory_limit);
  }

  if (CLOG_CHECK(&LOG, CLG_LEVEL_DEBUG)) {
    BKE_undosys_print(wm->runtime->undo_stack);
  }

  if (push_retval & UNDO_PUSH_RET_OVERRIDE_CHANGED) {
    WM_main_add_notifier(NC_WM | ND_LIB_OVERRIDE_CHANGED, nullptr);
  }
  return push_retval;
}

void ED_undo_push(bContext *C, const char *str)
{
  ed_undo_push_ex(C, str, nullptr);
}

bool ED_undo_push_memfile(bContext *C, const char *str)
{
  return (ed_undo_push_ex(C, str, BKE_UNDOSYS_TYPE_MEMFILE) & UNDO_PUSH_RET_SUCCESS) != 0;
}

/**
 * Common pre management of undo/redo (killing all running jobs, calling pre handlers, etc.).
 */
static void ed_undo_step_pre(bContext *C,
                             wmWindowManager *wm,
                             const enum eUndoStepDir undo_dir,
                             ReportList *reports)
{
  BLI_assert(ELEM(undo_dir, STEP_UNDO, STEP_REDO));

  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);

  /* undo during jobs are running can easily lead to freeing data using by jobs,
   * or they can just lead to freezing job in some other cases */
  WM_jobs_kill_all(wm);

  if (G.debug & G_DEBUG_IO) {
    if (bmain->lock != nullptr) {
      BKE_report(
          reports, RPT_DEBUG, "Checking validity of current .blend file *BEFORE* undo step");
      BLO_main_validate_libraries(bmain, reports);
    }
  }

  /* App-Handlers (pre). */
  {
    /* NOTE: ignore grease pencil for now. */
    wm->op_undo_depth++;
    BKE_callback_exec_id(
        bmain, &scene->id, (undo_dir == STEP_UNDO) ? BKE_CB_EVT_UNDO_PRE : BKE_CB_EVT_REDO_PRE);
    wm->op_undo_depth--;
  }
}

/**
 * Mixar per-tab undo: the tab an undo operator in this context walks, or
 * #UNDO_TAB_DOCUMENT for the classic walk. Read from the WINDOW's scene, the
 * scene the hold poll reads: a Python ``temp_override(scene=B)`` around
 * ``ed.undo`` from a window on an idle tab used to pass the hold and walk B
 * while B's own run was open (review 2026-10-01, R7).
 */
static uint32_t ed_undo_window_tab(const bContext *C)
{
  if (!BKE_undo_tabs_enabled()) {
    return UNDO_TAB_DOCUMENT;
  }
  wmWindow *win = CTX_wm_window(C);
  if (win == nullptr || win->scene == nullptr || BKE_undo_tab_scene_is_lane(win->scene)) {
    return UNDO_TAB_DOCUMENT;
  }
  return BKE_undo_tab_uid_for_scene(CTX_data_main(C), win->scene);
}

/**
 * Mixar per-tab undo (review 2026-10-01, R3): why a tab's walk must not start,
 * decided BEFORE #ed_undo_step_pre, whose job kill and pre handlers are side
 * effects a refusal must not have.
 *
 * - Another tab runs a job with progress (a render, an agent's preview render,
 *   a bake): every memfile restore replaces Main, so a job still holding the
 *   old one cannot survive it and the pre step cancels it. Cancelling another
 *   tab's work is not this tab's undo to make; the press waits instead.
 * - The walk itself would refuse (nothing to undo, shared or moved datablocks,
 *   a step written with per-tab undo off).
 */
static bool ed_undo_tab_walk_refused(bContext *C,
                                     wmWindowManager *wm,
                                     const uint32_t tab,
                                     const eUndoStepDir dir,
                                     std::string *r_reason,
                                     eReportType *r_type)
{
  Main *bmain = CTX_data_main(C);
  for (Scene &scene : bmain->scenes) {
    const uint32_t owner = BKE_undo_tab_uid_for_scene(bmain, &scene);
    if (owner == tab || !WM_jobs_test(wm, &scene, WM_JOB_TYPE_ANY)) {
      continue;
    }
    std::string name = BKE_undo_tab_scene_name(bmain, owner);
    if (name.empty()) {
      name = scene.id.name + 2;
    }
    *r_reason = "Undo waits for the render or bake running in '" + name +
                "' (undoing now would cancel it)";
    *r_type = RPT_WARNING;
    return true;
  }
  if (!BKE_undosys_tab_step_check(wm->runtime->undo_stack, C, tab, dir, r_reason)) {
    *r_type = RPT_INFO;
    return true;
  }
  return false;
}

static void ed_undo_tab_report_refusal(bContext *C,
                                       ReportList *reports,
                                       const eUndoStepDir dir,
                                       const std::string &reason,
                                       const eReportType type)
{
  wmWindow *win = CTX_wm_window(C);
  BKE_reportf(reports, type, "%s", reason.c_str());
  CLOG_WARN(&LOG,
            "per-tab %s refused in '%s': %s",
            (dir == STEP_UNDO) ? "undo" : "redo",
            (win && win->scene) ? win->scene->id.name + 2 : "?",
            reason.c_str());
}

/* Mixar: after a memfile restore, the depsgraph of a scene no window shows
 * keeps its object nodes, and their `id_orig` pointers, as they were: an
 * original the walk freed (created after the target step) dangles until that
 * depsgraph is rebuilt, which only happens once the scene is shown again. The
 * viewport's periodic batch sweep (#DRW_cache_free_old_batches) walks EVERY
 * scene's depsgraph and read `GS(id_orig->name)` of such an object (ASAN,
 * bonkers campaign 2026-09-30; parallel tabs give every agent scene a live
 * depsgraph). The windows' scenes are rebuilt before the next draw; the others
 * are freed here and come back when the scene is next shown or evaluated. */
static void ed_undo_free_unshown_depsgraphs(Main *bmain, wmWindowManager *wm)
{
  if (bmain == nullptr || wm == nullptr) {
    return;
  }
  blender::Set<const Scene *> shown;
  for (wmWindow &win : wm->windows) {
    if (const Scene *scene = WM_window_get_active_scene(&win)) {
      shown.add(scene);
    }
  }
  int freed = 0;
  for (Scene &scene : bmain->scenes) {
    if (scene.depsgraph_hash == nullptr || shown.contains(&scene)) {
      continue;
    }
    BKE_scene_free_depsgraph_hash(&scene);
    freed++;
  }
  if (freed > 0) {
    CLOG_DEBUG(&LOG, "undo: freed the depsgraphs of %d scene(s) no window shows", freed);
  }
}

/**
 * Common post management of undo/redo (calling post handlers, adding notifiers etc.).
 *
 * \note Also check #undo_history_exec in bottom if you change notifiers.
 */
static void ed_undo_step_post(bContext *C,
                              wmWindowManager *wm,
                              const enum eUndoStepDir undo_dir,
                              ReportList *reports)
{
  using namespace blender::ed;
  BLI_assert(ELEM(undo_dir, STEP_UNDO, STEP_REDO));

  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);

  ed_undo_free_unshown_depsgraphs(bmain, wm);
  /* App-Handlers (post). */
  {
    wm->op_undo_depth++;
    BKE_callback_exec_id(
        bmain, &scene->id, (undo_dir == STEP_UNDO) ? BKE_CB_EVT_UNDO_POST : BKE_CB_EVT_REDO_POST);
    wm->op_undo_depth--;
  }

  if (G.debug & G_DEBUG_IO) {
    if (bmain->lock != nullptr) {
      BKE_report(reports, RPT_INFO, "Checking validity of current .blend file *AFTER* undo step");
      BLO_main_validate_libraries(bmain, reports);
    }
  }

  /* Undo/redo may have invalidated a lot of data, ensure UI has also been fully updated before
   * handling next events. */
  WM_event_handling_break(*C);

  WM_event_add_notifier(C, NC_WINDOW, nullptr);
  WM_event_add_notifier(C, NC_WM | ND_UNDO, nullptr);

  WM_toolsystem_refresh_active(C);
  WM_toolsystem_refresh_screen_all(bmain);

  asset::list::storage_tag_main_data_dirty();

  if (CLOG_CHECK(&LOG, CLG_LEVEL_DEBUG)) {
    BKE_undosys_print(wm->runtime->undo_stack);
  }
}

/**
 * Undo or redo one step from current active one.
 * May undo or redo several steps at once only if the target step is a 'skipped' one.
 * The target step will be the one immediately before or after the active one.
 */
static wmOperatorStatus ed_undo_step_direction(bContext *C,
                                               enum eUndoStepDir step,
                                               ReportList *reports,
                                               const bool per_tab = true)
{
  BLI_assert(ELEM(step, STEP_UNDO, STEP_REDO));

  CLOG_INFO(&LOG, "Step direction=%s", (step == STEP_UNDO) ? "STEP_UNDO" : "STEP_REDO");

  wmWindowManager *wm = CTX_wm_manager(C);

  /* Mixar per-tab undo (M2): with the flag on and the window on a scene tab,
   * walk that tab's own history and restore only its datablocks. The classic
   * document-wide walk stays for a window on no tab (and for the explicit
   * "Undo whole document" of M4). */
  const uint32_t tab = per_tab ? ed_undo_window_tab(C) : UNDO_TAB_DOCUMENT;
  if (tab != UNDO_TAB_DOCUMENT) {
    /* Every refusal is decided before the pre step (review 2026-10-01, R3): a
     * refused press kills no job and runs no handler. Nothing is restored, so
     * the post handlers do not run either: the chat module's undo_post bumps
     * the DOCUMENT epoch when the last walk was document-wide, which a refusal
     * after an Undo Whole Document would have reported, revoking the in-flight
     * commits of every other tab (review of #1746). */
    std::string reason;
    eReportType type = RPT_INFO;
    if (ed_undo_tab_walk_refused(C, wm, tab, step, &reason, &type)) {
      ed_undo_tab_report_refusal(C, reports, step, reason, type);
      return OPERATOR_CANCELLED;
    }
    ed_undo_step_pre(C, wm, step, reports);
    const bool ok = (step == STEP_UNDO) ?
                        BKE_undosys_tab_step_undo(wm->runtime->undo_stack, C, tab, &reason) :
                        BKE_undosys_tab_step_redo(wm->runtime->undo_stack, C, tab, &reason);
    if (!ok) {
      ed_undo_tab_report_refusal(C, reports, step, reason, RPT_INFO);
      return OPERATOR_CANCELLED;
    }
  }
  else {
    ed_undo_step_pre(C, wm, step, reports);
    if (step == STEP_UNDO) {
      BKE_undosys_step_undo(wm->runtime->undo_stack, C);
    }
    else {
      BKE_undosys_step_redo(wm->runtime->undo_stack, C);
    }
  }

  ed_undo_step_post(C, wm, step, reports);

  return OPERATOR_FINISHED;
}

/**
 * Undo the step matching given name.
 * May undo several steps at once.
 * The target step will be the one immediately before given named one.
 */
static int ed_undo_step_by_name(bContext *C, const char *undo_name, ReportList *reports)
{
  BLI_assert(undo_name != nullptr);

  wmWindowManager *wm = CTX_wm_manager(C);

  /* Mixar per-tab undo (review 2026-10-01, R1): Adjust Last Operation (the
   * redo panel, F9, a gizmo's redo) takes the operator's step back before
   * running it again. Found by name across the whole stack and loaded with the
   * document walk, that reverted every tab's newer work and the repeat's push
   * then truncated their history. On a tab it is the tab's walk, and only when
   * the operator's step is the tab's current one. */
  const uint32_t tab = ed_undo_window_tab(C);
  if (tab != UNDO_TAB_DOCUMENT) {
    UndoStack *ustack = wm->runtime->undo_stack;
    UndoStep *cursor = BKE_undosys_tab_cursor(ustack, tab);
    if (cursor == nullptr || !STREQ(cursor->name, undo_name)) {
      CLOG_WARN(&LOG,
                "Step name='%s' is not this tab's current step ('%s'): not repeated",
                undo_name,
                cursor ? cursor->name : "");
      return OPERATOR_CANCELLED;
    }
    wmWindow *win = CTX_wm_window(C);
    if (BKE_undo_tab_scene_is_working(win->scene)) {
      BKE_report(reports, RPT_INFO, "Unavailable while this tab's agent works");
      return OPERATOR_CANCELLED;
    }
    std::string reason;
    eReportType type = RPT_INFO;
    if (ed_undo_tab_walk_refused(C, wm, tab, STEP_UNDO, &reason, &type)) {
      ed_undo_tab_report_refusal(C, reports, STEP_UNDO, reason, type);
      return OPERATOR_CANCELLED;
    }
    ed_undo_step_pre(C, wm, STEP_UNDO, reports);
    if (!BKE_undosys_tab_step_undo(ustack, C, tab, &reason)) {
      ed_undo_tab_report_refusal(C, reports, STEP_UNDO, reason, RPT_INFO);
      return OPERATOR_CANCELLED;
    }
    ed_undo_step_post(C, wm, STEP_UNDO, reports);
    return OPERATOR_FINISHED;
  }

  UndoStep *undo_step_from_name = BKE_undosys_step_find_by_name(wm->runtime->undo_stack,
                                                                undo_name);
  if (undo_step_from_name == nullptr) {
    CLOG_ERROR(&LOG, "Step name='%s' not found in current undo stack", undo_name);

    return OPERATOR_CANCELLED;
  }

  UndoStep *undo_step_target = undo_step_from_name->prev;
  if (undo_step_target == nullptr) {
    CLOG_ERROR(&LOG, "Step name='%s' cannot be undone", undo_name);

    return OPERATOR_CANCELLED;
  }

  const int undo_dir_i = BKE_undosys_step_calc_direction(
      wm->runtime->undo_stack, undo_step_target, nullptr);
  BLI_assert(ELEM(undo_dir_i, -1, 1));
  const enum eUndoStepDir undo_dir = (undo_dir_i == -1) ? STEP_UNDO : STEP_REDO;

  CLOG_INFO(&LOG,
            "Step name='%s', found direction=%s",
            undo_name,
            (undo_dir == STEP_UNDO) ? "STEP_UNDO" : "STEP_REDO");

  ed_undo_step_pre(C, wm, undo_dir, reports);

  BKE_undosys_step_load_data_ex(wm->runtime->undo_stack, C, undo_step_target, nullptr, true);

  ed_undo_step_post(C, wm, undo_dir, reports);

  return OPERATOR_FINISHED;
}

/**
 * Load the step matching given index in the stack.
 * May undo or redo several steps at once.
 * The target step will be the one indicated by the given index.
 */
static int ed_undo_step_by_index(bContext *C, const int undo_index, ReportList *reports)
{
  BLI_assert(undo_index >= 0);

  wmWindowManager *wm = CTX_wm_manager(C);

  /* Mixar per-tab undo (M3): the Undo History of a tab walks that tab to the
   * chosen step (the menu lists only its steps; the index is the stack's). */
  {
    const uint32_t tab = ed_undo_window_tab(C);
    if (tab != UNDO_TAB_DOCUMENT) {
      UndoStack *ustack = wm->runtime->undo_stack;
      UndoStep *target = static_cast<UndoStep *>(BLI_findlink(&ustack->steps, undo_index));
      UndoStep *cursor = BKE_undosys_tab_cursor(ustack, tab);
      if (target == nullptr || target == cursor) {
        return OPERATOR_CANCELLED;
      }
      const enum eUndoStepDir undo_dir = (BLI_findindex(&ustack->steps, cursor) > undo_index) ?
                                             STEP_UNDO :
                                             STEP_REDO;
      std::string reason;
      eReportType type = RPT_INFO;
      if (ed_undo_tab_walk_refused(C, wm, tab, undo_dir, &reason, &type)) {
        ed_undo_tab_report_refusal(C, reports, undo_dir, reason, type);
        return OPERATOR_CANCELLED;
      }
      ed_undo_step_pre(C, wm, undo_dir, reports);
      const bool ok = BKE_undosys_tab_step_load(ustack, C, tab, target, &reason);
      if (!ok) {
        BKE_reportf(reports, RPT_INFO, "%s", reason.c_str());
        /* The jump walks one tagged step at a time: a refusal part way leaves the
         * tab moved, and the post handlers (chat guard, epoch, live-state repair)
         * must see that walk (review 2026-10-01). Refused at the first step:
         * nothing changed, no post handlers (see ed_undo_step_direction). */
        if (BKE_undosys_tab_cursor(ustack, tab) == cursor) {
          return OPERATOR_CANCELLED;
        }
      }
      ed_undo_step_post(C, wm, undo_dir, reports);
      return OPERATOR_FINISHED;
    }
  }

  const int active_step_index = BLI_findindex(&wm->runtime->undo_stack->steps,
                                              wm->runtime->undo_stack->step_active);
  if (undo_index == active_step_index) {
    return OPERATOR_CANCELLED;
  }
  const enum eUndoStepDir undo_dir = (undo_index < active_step_index) ? STEP_UNDO : STEP_REDO;

  CLOG_INFO(&LOG,
            "Step index='%d', found direction=%s",
            undo_index,
            (undo_dir == STEP_UNDO) ? "STEP_UNDO" : "STEP_REDO");

  ed_undo_step_pre(C, wm, undo_dir, reports);

  BKE_undosys_step_load_from_index(wm->runtime->undo_stack, C, undo_index);

  ed_undo_step_post(C, wm, undo_dir, reports);

  return OPERATOR_FINISHED;
}

void ED_undo_grouped_push(bContext *C, const char *str)
{
  /* do nothing if previous undo task is the same as this one (or from the same undo group) */
  wmWindowManager *wm = CTX_wm_manager(C);
  UndoStack *ustack = wm->runtime->undo_stack;
  /* See matching check in #ED_undo_push. */
  if (G.background) {
    if (ustack == nullptr) {
      return;
    }
  }
  const UndoStep *us = ustack->step_active;
  if (us && STREQ(str, us->name)) {
    BKE_undosys_stack_clear_active(ustack);
  }

  /* push as usual */
  ED_undo_push(C, str);
}

void ED_undo_pop(bContext *C)
{
  ed_undo_step_direction(C, STEP_UNDO, nullptr);
}
void ED_undo_redo(bContext *C)
{
  ed_undo_step_direction(C, STEP_REDO, nullptr);
}

void ED_undo_push_op(bContext *C, wmOperator *op)
{
  /* in future, get undo string info? */
  ED_undo_push(C, op->type->name);
}

void ED_undo_grouped_push_op(bContext *C, wmOperator *op)
{
  if (op->type->undo_group[0] != '\0') {
    ED_undo_grouped_push(C, op->type->undo_group);
  }
  else {
    ED_undo_grouped_push(C, op->type->name);
  }
}

void ED_undo_pop_op(bContext *C, wmOperator *op)
{
  /* search back a couple of undo's, in case something else added pushes */
  ed_undo_step_by_name(C, op->type->name, op->reports);
}

bool ED_undo_is_valid(const bContext *C, const char *undoname)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  UndoStack *ustack = wm->runtime->undo_stack;
  /* Mixar per-tab undo (review 2026-10-01, R1): on a tab, an operator can be
   * adjusted only while its step is the tab's current one. */
  const uint32_t tab = ed_undo_window_tab(C);
  if (ustack && undoname && tab != UNDO_TAB_DOCUMENT) {
    const UndoStep *cursor = BKE_undosys_tab_cursor(ustack, tab);
    return cursor && STREQ(cursor->name, undoname) && BKE_undosys_tab_has_undo(ustack, tab);
  }
  return ustack && BKE_undosys_stack_has_undo(ustack, undoname);
}

bool ED_undo_has_redo_step(const bContext *C)
{
  const wmWindowManager *wm = CTX_wm_manager(C);
  UndoStack *ustack = wm->runtime->undo_stack;
  return ustack && BKE_undosys_stack_has_redo(ustack);
}

bool ED_undo_is_memfile_compatible(const bContext *C)
{
  /* Some modes don't co-exist with memfile undo, disable their use: #60593
   * (this matches 2.7x behavior). */
  const Main *bmain = CTX_data_main(C);
  const Scene *scene = CTX_data_scene(C);
  ViewLayer *view_layer = CTX_data_view_layer(C);
  if (view_layer != nullptr) {
    BKE_view_layer_synced_ensure(*bmain, scene, view_layer);
    Object *obact = BKE_view_layer_active_object_get(view_layer);
    if (obact != nullptr) {
      if (obact->mode & OB_MODE_EDIT) {
        return false;
      }
    }
  }
  return true;
}

bool ED_undo_is_legacy_compatible_for_property(bContext *C, ID *id, PointerRNA &ptr)
{
  if (!RNA_struct_undo_check(ptr.type)) {
    return false;
  }
  /* If the whole ID type doesn't support undo there is no need to check the current context. */
  if (id && !ID_CHECK_UNDO(id)) {
    return false;
  }

  const Main *bmain = CTX_data_main(C);
  const Scene *scene = CTX_data_scene(C);
  ViewLayer *view_layer = CTX_data_view_layer(C);
  if (view_layer != nullptr) {
    BKE_view_layer_synced_ensure(*bmain, scene, view_layer);
    Object *obact = BKE_view_layer_active_object_get(view_layer);
    if (obact != nullptr) {
      if (obact->mode & OB_MODE_SCULPT) {
        /* Changing properties while in sculpt mode is expensive due to the paint BVH rebuild.
         * Avoid pushing such undo steps for now. */
        CLOG_DEBUG(&LOG, "skipping undo for sculpt-mode");
        return false;
      }
      if (obact->mode & OB_MODE_EDIT) {
        if ((id == nullptr) || (obact->data == nullptr) ||
            (GS(id->name) != GS(((ID *)obact->data)->name)))
        {
          /* No undo push on id type mismatch in edit-mode. */
          CLOG_DEBUG(&LOG, "skipping undo for edit-mode");
          return false;
        }
      }
    }
  }
  return true;
}

UndoStack *ED_undo_stack_get()
{
  wmWindowManager *wm = static_cast<wmWindowManager *>(G_MAIN->wm.first);
  return wm->runtime->undo_stack;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Undo, Undo Push & Redo Operators
 * \{ */

/**
 * Refresh to run after user activated undo/redo actions.
 */
static void ed_undo_refresh_for_op(bContext *C)
{
  /* The "last operator" should disappear, later we can tie this with undo stack nicer. */
  WM_operator_stack_clear(CTX_wm_manager(C));

  /* Keep button under the cursor active. */
  WM_event_add_mousemove(CTX_wm_window(C));

  ED_outliner_select_sync_from_all_tag(C);
}

static wmOperatorStatus ed_undo_exec(bContext *C, wmOperator *op)
{
  /* "last operator" should disappear, later we can tie this with undo stack nicer */
  WM_operator_stack_clear(CTX_wm_manager(C));
  wmOperatorStatus ret = ed_undo_step_direction(C, STEP_UNDO, op->reports);
  if (ret & OPERATOR_FINISHED) {
    ed_undo_refresh_for_op(C);
  }
  return ret;
}

static wmOperatorStatus ed_undo_push_exec(bContext *C, wmOperator *op)
{
  if (G.background) {
    /* Exception for background mode, see: #60934.
     * NOTE: since the undo stack isn't initialized on startup, background mode behavior
     * won't match regular usage, this is just for scripts to do explicit undo pushes. */
    wmWindowManager *wm = CTX_wm_manager(C);
    if (wm->runtime->undo_stack == nullptr) {
      wm->runtime->undo_stack = BKE_undosys_stack_create();
    }
  }
  char str[BKE_UNDO_STR_MAX];
  RNA_string_get(op->ptr, "message", str);
  ED_undo_push(C, str);
  return OPERATOR_FINISHED;
}

static wmOperatorStatus ed_redo_exec(bContext *C, wmOperator *op)
{
  wmOperatorStatus ret = ed_undo_step_direction(C, STEP_REDO, op->reports);
  if (ret & OPERATOR_FINISHED) {
    ed_undo_refresh_for_op(C);
  }
  return ret;
}

static wmOperatorStatus ed_undo_redo_exec(bContext *C, wmOperator * /*op*/)
{
  wmOperator *last_op = WM_operator_last_redo(C);
  wmOperatorStatus ret = ED_undo_operator_repeat(C, last_op) ? OPERATOR_FINISHED :
                                                               OPERATOR_CANCELLED;
  if (ret & OPERATOR_FINISHED) {
    /* Keep button under the cursor active. */
    WM_event_add_mousemove(CTX_wm_window(C));
  }
  return ret;
}

/* Disable in background mode, we could support if it's useful, #60934. */

static bool ed_undo_is_init_poll(bContext *C)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm->runtime->undo_stack == nullptr) {
    /* This message is intended for Python developers,
     * it will be part of the exception when attempting to call undo in background mode. */
    CTX_wm_operator_poll_msg_set(
        C,
        "Undo disabled at startup in background-mode "
        "(call `ed.undo_push()` to explicitly initialize the undo-system)");
    return false;
  }
  return true;
}

static bool ed_undo_is_init_and_screenactive_poll(bContext *C)
{
  if (ed_undo_is_init_poll(C) == false) {
    return false;
  }
  return ED_operator_screenactive(C);
}

static bool ed_undo_redo_poll(bContext *C)
{
  wmOperator *last_op = WM_operator_last_redo(C);
  return (last_op && ed_undo_is_init_and_screenactive_poll(C) &&
          WM_operator_check_ui_enabled(C, last_op->type->name));
}

/**
 * Mixar per-tab undo (M4): the hold. With the flag on, a window on a worker lane
 * or on a tab whose own agent works refuses undo, redo and the history. This is
 * the operators' own poll, so it holds through the keymap, the Edit menu, menu
 * search and Python, with no modal and no viewport lock. Other tabs' agents
 * block nothing.
 */
static bool ed_undo_tab_hold_poll(bContext *C)
{
  if (!BKE_undo_tabs_enabled()) {
    return true;
  }
  wmWindow *win = CTX_wm_window(C);
  const Scene *scene = (win != nullptr) ? win->scene : CTX_data_scene(C);
  if (scene == nullptr) {
    return true;
  }
  if (BKE_undo_tab_scene_is_lane(scene)) {
    CTX_wm_operator_poll_msg_set(C, "Undo is unavailable inside an agent's workspace");
    return false;
  }
  if (BKE_undo_tab_scene_is_working(scene)) {
    CTX_wm_operator_poll_msg_set(C, "Undo is unavailable while this tab's agent works");
    return false;
  }
  return true;
}

static bool ed_undo_poll(bContext *C)
{
  if (!ed_undo_is_init_and_screenactive_poll(C)) {
    return false;
  }
  if (!ed_undo_tab_hold_poll(C)) {
    return false;
  }
  UndoStack *undo_stack = CTX_wm_manager(C)->runtime->undo_stack;
  /* Mixar per-tab undo (M5): nothing to undo when the tab has no own step
   * before its cursor (its reserve floor, or a tab with no edits yet). */
  if (const uint32_t tab = ed_undo_window_tab(C); tab != UNDO_TAB_DOCUMENT) {
    return BKE_undosys_tab_has_undo(undo_stack, tab);
  }
  return (undo_stack->step_active != nullptr) && (undo_stack->step_active->prev != nullptr);
}

void ED_OT_undo(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Undo";
  ot->description = "Undo previous action";
  ot->idname = "ED_OT_undo";

  /* API callbacks. */
  ot->exec = ed_undo_exec;
  ot->poll = ed_undo_poll;
}

void ED_OT_undo_push(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Undo Push";
  ot->description = "Add an undo state (internal use only)";
  ot->idname = "ED_OT_undo_push";

  /* API callbacks. */
  ot->exec = ed_undo_push_exec;
  /* Unlike others undo operators this initializes undo stack. */
  ot->poll = ED_operator_screenactive;

  ot->flag = OPTYPE_INTERNAL;

  RNA_def_string(ot->srna,
                 "message",
                 "Add an undo step *function may be moved*",
                 BKE_UNDO_STR_MAX,
                 "Undo Message",
                 "");
}

static bool ed_redo_poll(bContext *C)
{
  if (!ed_undo_is_init_and_screenactive_poll(C)) {
    return false;
  }
  if (!ed_undo_tab_hold_poll(C)) {
    return false;
  }
  UndoStack *undo_stack = CTX_wm_manager(C)->runtime->undo_stack;
  /* Mixar per-tab undo (M2): the document's active step stays at the top while
   * tabs walk their own history; redo is available when THIS tab is behind. */
  if (const uint32_t tab = ed_undo_window_tab(C); tab != UNDO_TAB_DOCUMENT) {
    return BKE_undosys_tab_has_redo(undo_stack, tab);
  }
  return (undo_stack->step_active != nullptr) && (undo_stack->step_active->next != nullptr);
}

void ED_OT_redo(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Redo";
  ot->description = "Redo previous action";
  ot->idname = "ED_OT_redo";

  /* API callbacks. */
  ot->exec = ed_redo_exec;
  ot->poll = ed_redo_poll;
}

void ED_OT_undo_redo(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Undo and Redo";
  ot->description = "Undo and redo previous action";
  ot->idname = "ED_OT_undo_redo";

  /* API callbacks. */
  ot->exec = ed_undo_redo_exec;
  ot->poll = ed_undo_redo_poll;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Operator Repeat
 * \{ */

bool ED_undo_operator_repeat(bContext *C, wmOperator *op)
{
  bool success = false;

  if (op) {
    CLOG_INFO(&LOG, "Operator repeat idname='%s'", op->type->idname);
    wmWindowManager *wm = CTX_wm_manager(C);
    const ScrArea *area = CTX_wm_area(C);
    Scene *scene = CTX_data_scene(C);

    /* keep in sync with logic in view3d_panel_operator_redo() */
    ARegion *region_orig = CTX_wm_region(C);
    /* If the redo is called from a HUD, this knows about the region type the operator was
     * initially called in, so attempt to restore that. */
    ARegion *redo_region_from_hud = (region_orig->regiontype == RGN_TYPE_HUD) ?
                                        ui::ED_area_type_hud_redo_region_find(area, region_orig) :
                                        nullptr;
    ARegion *region_repeat = redo_region_from_hud ? redo_region_from_hud :
                                                    BKE_area_find_region_active_win(area);

    if (region_repeat) {
      CTX_wm_region_set(C, region_repeat);
    }

    if (WM_operator_repeat_check(C, op) && WM_operator_poll(C, op->type) &&
        /* NOTE: undo/redo can't run if there are jobs active,
         * check for screen jobs only so jobs like material/texture/world preview
         * (which copy their data), won't stop redo, see #29579.
         *
         * NOTE: WM_operator_check_ui_enabled() jobs test _must_ stay in sync with this. */
        (WM_jobs_test(wm, scene, WM_JOB_TYPE_ANY) == 0))
    {
      if (G.debug & G_DEBUG) {
        printf("redo_cb: operator redo %s\n", op->type->name);
      }

      WM_operator_free_all_after(wm, op);

      if ((ed_undo_step_by_name(C, op->type->name, op->reports) & OPERATOR_FINISHED) == 0) {
        /* Mixar per-tab undo (review 2026-10-01, R1): nothing was taken back (not
         * this tab's current step, its agent works, the walk was refused).
         * Running the operator again now would apply it a second time. */
        CTX_wm_region_set(C, region_orig);
        return false;
      }

      if (op->type->check) {
        if (op->type->check(C, op)) {
          /* check for popup and re-layout buttons */
          ARegion *region_popup = CTX_wm_region_popup(C);
          if (region_popup) {
            ED_region_tag_refresh_ui(region_popup);
          }
        }
      }

      const wmOperatorStatus retval = WM_operator_repeat(C, op);
      if ((retval & OPERATOR_FINISHED) == 0) {
        if (G.debug & G_DEBUG) {
          printf("redo_cb: operator redo failed: %s, return %d\n", op->type->name, retval);
        }
        ED_undo_redo(C);
      }
      else {
        success = true;
      }
    }
    else {
      if (G.debug & G_DEBUG) {
        printf("redo_cb: WM_operator_repeat_check returned false %s\n", op->type->name);
      }
    }

    /* set region back */
    CTX_wm_region_set(C, region_orig);
  }
  else {
    CLOG_WARN(&LOG, "called with nullptr 'op'");
  }

  return success;
}

void ED_undo_operator_repeat_cb(bContext *C, void *arg_op, void * /*arg_unused*/)
{
  ED_undo_operator_repeat(C, static_cast<wmOperator *>(arg_op));
}

void ED_undo_operator_repeat_cb_evt(bContext *C, void *arg_op, int /*arg_unused*/)
{
  ED_undo_operator_repeat(C, static_cast<wmOperator *>(arg_op));
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Undo History Operator
 *
 * See `TOPBAR_MT_undo_history` which is used to access this operator.
 * \{ */

/* NOTE: also check #ed_undo_step() in top if you change notifiers. */
static bool ed_undo_history_poll(bContext *C)
{
  return ed_undo_is_init_and_screenactive_poll(C) && ed_undo_tab_hold_poll(C);
}

/* -------------------------------------------------------------------- */
/** \name Mixar: Undo Whole Document (M4)
 *
 * The classic document-wide walk, one step back, behind a confirmation that
 * names the tabs it moves. Refused while any tab's agent works or a worker
 * lane exists. Every tab's cursor is forgotten: after it, every tab stands at
 * the document's active step, and a tab's Shift-Ctrl-Z redoes its own steps
 * above it.
 * \{ */

static bool ed_undo_whole_document_poll(bContext *C)
{
  if (!BKE_undo_tabs_enabled()) {
    CTX_wm_operator_poll_msg_set(C, "Per-tab undo is off; Undo already covers the whole document");
    return false;
  }
  if (!ed_undo_is_init_and_screenactive_poll(C)) {
    return false;
  }
  UndoStack *ustack = CTX_wm_manager(C)->runtime->undo_stack;
  if (ustack->step_active == nullptr || ustack->step_active->prev == nullptr) {
    return false;
  }
  if (BKE_undo_tab_any_working(CTX_data_main(C))) {
    CTX_wm_operator_poll_msg_set(C, "Undo Whole Document is unavailable while an agent works");
    return false;
  }
  return true;
}

/** The tabs a whole-document undo moves: those with a step above the target
 * (the step being taken back) and those standing behind their newest step. */
static std::string ed_undo_whole_document_tabs(bContext *C, const UndoStep *target)
{
  UndoStack *ustack = CTX_wm_manager(C)->runtime->undo_stack;
  Main *bmain = CTX_data_main(C);
  blender::Vector<uint32_t> tabs;
  for (const UndoStep *us = target ? target->next : nullptr; us != nullptr; us = us->next) {
    if (!us->skip && us->mixar_tab_uid != UNDO_TAB_DOCUMENT && !tabs.contains(us->mixar_tab_uid)) {
      tabs.append(us->mixar_tab_uid);
    }
  }
  for (const Scene &scene : bmain->scenes) {
    const uint32_t tab = scene.id.session_uid;
    if (tabs.contains(tab) || BKE_undo_tab_scene_is_lane(&scene)) {
      continue;
    }
    /* Behind its newest step now, or behind it when the target was written. */
    if (BKE_undosys_tab_has_redo(ustack, tab) ||
        (target->mixar_cursors != nullptr &&
         static_cast<const blender::Map<uint32_t, UndoStep *> *>(target->mixar_cursors)->contains(tab)))
    {
      tabs.append(tab);
    }
  }
  std::string names;
  for (const uint32_t tab : tabs) {
    const std::string name = BKE_undo_tab_scene_name(bmain, tab);
    if (name.empty()) {
      continue;
    }
    names += (names.empty() ? "" : ", ") + name;
  }
  return names;
}

static wmOperatorStatus ed_undo_whole_document_exec(bContext *C, wmOperator *op)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  WM_operator_stack_clear(wm);
  /* After per-tab walks the live document is not the active step's state: the
   * document walk re-reads every ID, and it restores the reached step's cursor
   * snapshot itself (BKE_undosys_step_load_data_ex), which says where each tab
   * stood when that state was written. */
  wmOperatorStatus ret = ed_undo_step_direction(C, STEP_UNDO, op->reports, false);
  if (ret & OPERATOR_FINISHED) {
    ed_undo_refresh_for_op(C);
  }
  return ret;
}

static wmOperatorStatus ed_undo_whole_document_invoke(bContext *C, wmOperator *op, const wmEvent * /*event*/)
{
  UndoStack *ustack = CTX_wm_manager(C)->runtime->undo_stack;
  UndoStep *target = ustack->step_active ? ustack->step_active->prev : nullptr;
  while (target != nullptr && target->skip) {
    target = target->prev;
  }
  if (target == nullptr) {
    return OPERATOR_CANCELLED;
  }
  const std::string tabs = ed_undo_whole_document_tabs(C, target);
  std::string message = std::string("Every tab goes back to \"") + target->name + "\".";
  if (!tabs.empty()) {
    message += " Tabs that change: " + tabs + ".";
  }
  return WM_operator_confirm_ex(C,
                                op,
                                IFACE_("Undo Whole Document"),
                                message.c_str(),
                                IFACE_("Undo"),
                                blender::ui::AlertIcon::Warning,
                                false);
}

void ED_OT_undo_whole_document(wmOperatorType *ot)
{
  ot->name = "Undo Whole Document";
  ot->description =
      "Step the whole document back one step, every tab at once, as the classic undo did (the "
      "Undo entry walks only this tab)";
  ot->idname = "ED_OT_undo_whole_document";
  ot->invoke = ed_undo_whole_document_invoke;
  ot->exec = ed_undo_whole_document_exec;
  ot->poll = ed_undo_whole_document_poll;
}

/** \} */

static wmOperatorStatus undo_history_exec(bContext *C, wmOperator *op)
{
  PropertyRNA *prop = RNA_struct_find_property(op->ptr, "item");
  if (RNA_property_is_set(op->ptr, prop)) {
    const int item = RNA_property_int_get(op->ptr, prop);
    const int ret = ed_undo_step_by_index(C, item, op->reports);
    if (ret & OPERATOR_FINISHED) {
      ed_undo_refresh_for_op(C);

      WM_event_add_notifier(C, NC_WINDOW, nullptr);
      return OPERATOR_FINISHED;
    }
  }
  return OPERATOR_CANCELLED;
}

static wmOperatorStatus undo_history_invoke(bContext *C, wmOperator *op, const wmEvent * /*event*/)
{
  PropertyRNA *prop = RNA_struct_find_property(op->ptr, "item");
  if (RNA_property_is_set(op->ptr, prop)) {
    return undo_history_exec(C, op);
  }

  WM_menu_name_call(C, "TOPBAR_MT_undo_history", wm::OpCallContext::InvokeDefault);
  return OPERATOR_FINISHED;
}

void ED_OT_undo_history(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Undo History";
  ot->description = "Undo or redo specific action in history";
  ot->idname = "ED_OT_undo_history";

  /* API callbacks. */
  ot->invoke = undo_history_invoke;
  ot->exec = undo_history_exec;
  ot->poll = ed_undo_history_poll;

  RNA_def_int(ot->srna, "item", 0, 0, INT_MAX, "Item", "", 0, INT_MAX);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Undo Helper Functions
 * \{ */

void ED_undo_object_set_active_or_warn(const Main &bmain,
                                       Scene *scene,
                                       ViewLayer *view_layer,
                                       Object *ob,
                                       const char *info,
                                       CLG_LogRef *log)
{
  using namespace blender::ed;
  BKE_view_layer_synced_ensure(bmain, scene, view_layer);
  Object *ob_prev = BKE_view_layer_active_object_get(view_layer);
  if (ob_prev != ob) {
    Base *base = BKE_view_layer_base_find(view_layer, ob);
    if (base != nullptr) {
      view_layer->basact = base;
      object::base_active_refresh(G_MAIN, scene, view_layer);
    }
    else {
      /* Should never fail, may not crash but can give odd behavior. */
      CLOG_WARN(log, "'%s' failed to restore active object: '%s'", info, ob->id.name + 2);
    }
  }
}

void ED_undo_object_editmode_validate_scene_from_windows(wmWindowManager *wm,
                                                         const Scene *scene_ref,
                                                         Scene **scene_p,
                                                         ViewLayer **view_layer_p)
{
  if (*scene_p == scene_ref) {
    return;
  }
  for (wmWindow &win : wm->windows) {
    if (win.scene == scene_ref) {
      *scene_p = win.scene;
      *view_layer_p = WM_window_get_active_view_layer(&win);
      return;
    }
  }
}

void ED_undo_object_editmode_restore_helper(Scene *scene,
                                            ViewLayer *view_layer,
                                            Object **object_array,
                                            uint object_array_len,
                                            uint object_array_stride)
{
  using namespace blender::ed;
  Main *bmain = G_MAIN;
  /* Don't request unique data because we want to de-select objects when exiting edit-mode
   * for that to be done on all objects we can't skip ones that share data. */
  Vector<Base *> bases = ED_undo_editmode_bases_from_view_layer(*bmain, scene, view_layer);
  for (Base *base : bases) {
    (base->object->data)->tag |= ID_TAG_DOIT;
  }
  Object **ob_p = object_array;
  for (uint i = 0; i < object_array_len;
       i++, ob_p = static_cast<Object **>(POINTER_OFFSET(ob_p, object_array_stride)))
  {
    Object *obedit = *ob_p;
    object::editmode_enter_ex(bmain, scene, obedit, object::EM_NO_CONTEXT);
    (obedit->data)->tag &= ~ID_TAG_DOIT;
  }
  for (Base *base : bases) {
    const ID *id = base->object->data;
    if (id->tag & ID_TAG_DOIT) {
      object::editmode_exit_ex(bmain, scene, base->object, object::EM_FREEDATA);
      /* Ideally we would know the selection state it was before entering edit-mode,
       * for now follow the convention of having them unselected when exiting the mode. */
      object::base_select(base, object::BA_DESELECT);
    }
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Undo View Layer Helper Functions
 *
 * Needed because view layer functions such as
 * #BKE_view_layer_array_from_objects_in_edit_mode_unique_data also check visibility,
 * which is not reliable when it comes to object undo operations,
 * since hidden objects can be operated on in the properties editor,
 * and local collections may be used.
 * \{ */

Vector<Object *> ED_undo_editmode_objects_from_view_layer(const Main &bmain,
                                                          const Scene *scene,
                                                          ViewLayer *view_layer)
{
  BKE_view_layer_synced_ensure(bmain, scene, view_layer);
  Base *baseact = BKE_view_layer_active_base_get(view_layer);
  if ((baseact == nullptr) || (baseact->object->mode & OB_MODE_EDIT) == 0) {
    return {};
  }
  Set<const ID *> object_data;
  const short object_type = baseact->object->type;
  Vector<Object *> objects(object_data.size());
  /* Base iteration, starting with the active-base to ensure it's the first item in the array.
   * Looping over the active-base twice is OK as the tag check prevents it being handled twice. */
  for (Base *base = baseact,
            *base_next = static_cast<Base *>(BKE_view_layer_object_bases_get(view_layer)->first);
       base;
       base = base_next, base_next = base_next ? base_next->next : nullptr)
  {
    Object *ob = base->object;
    if ((ob->type == object_type) && (ob->mode & OB_MODE_EDIT)) {
      if (object_data.add(static_cast<const ID *>(ob->data))) {
        objects.append(ob);
      }
    }
  }
  BLI_assert(!object_data.is_empty());
  BLI_assert(objects[0] == baseact->object);
  return objects;
}

Vector<Base *> ED_undo_editmode_bases_from_view_layer(const Main &bmain,
                                                      const Scene *scene,
                                                      ViewLayer *view_layer)
{
  BKE_view_layer_synced_ensure(bmain, scene, view_layer);
  Base *baseact = BKE_view_layer_active_base_get(view_layer);
  if ((baseact == nullptr) || (baseact->object->mode & OB_MODE_EDIT) == 0) {
    return {};
  }
  Set<const ID *> object_data;
  const short object_type = baseact->object->type;
  Vector<Base *> bases;
  /* Base iteration, starting with the active-base to ensure it's the first item in the array.
   * Looping over the active-base twice is OK as the tag check prevents it being handled twice. */
  for (Base *base = BKE_view_layer_active_base_get(view_layer),
            *base_next = static_cast<Base *>(BKE_view_layer_object_bases_get(view_layer)->first);
       base;
       base = base_next, base_next = base_next ? base_next->next : nullptr)
  {
    Object *ob = base->object;
    if ((ob->type == object_type) && (ob->mode & OB_MODE_EDIT)) {
      if (object_data.add(static_cast<const ID *>(ob->data))) {
        bases.append(base);
      }
    }
  }

  BLI_assert(!object_data.is_empty());
  BLI_assert(bases[0] == baseact);
  return bases;
}

size_t ED_undosys_total_memory_calc(UndoStack *ustack)
{
  size_t total_memory = 0;

  for (UndoStep *us = static_cast<UndoStep *>(ustack->steps.first); us != nullptr; us = us->next) {
    if (us->type == BKE_UNDOSYS_TYPE_SCULPT) {
      total_memory += ed::sculpt_paint::undo::step_memory_size_get(us);
    }
    else if (us->data_size > 0) {
      total_memory += us->data_size;
    }
  }

  return total_memory;
}

/** \} */

}  // namespace blender
