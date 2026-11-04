/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Document-level helpers for the turn checkpoint restore.
 *
 * A checkpoint is a `save_as_mainfile(copy=True)` snapshot, and a copy carries
 * no recovery header, so reading it back with `wm.recover_auto_save` leaves the
 * document untitled. Python has no way to give a document its path back except
 * a real save, which is exactly what a restore must never do (it wrote the
 * artist's project file with no confirmation). This operator re-titles the
 * in-memory document and marks it modified; the next save is the artist's
 * explicit choice, like after any edit. An empty path keeps it untitled so
 * Ctrl-S opens Save As instead of landing in a hidden folder.
 */

#include "BLI_listbase.h"
#include "BLI_string.h"

#include "BKE_context.hh"
#include "BKE_main.hh"
#include "BKE_undo_system.hh"

#include "DNA_space_enums.h" /* FILE_MAX */
#include "DNA_windowmanager_types.h"

#include "ED_undo.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"

namespace blender {

static wmOperatorStatus mixie_chat_retitle_document_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  wmWindowManager *wm = CTX_wm_manager(C);
  if (bmain == nullptr) {
    return OPERATOR_CANCELLED;
  }

  char filepath[FILE_MAX];
  RNA_string_get(op->ptr, "filepath", filepath);
  if (filepath[0] != '\0') {
    STRNCPY(bmain->filepath, filepath);
  }
  else {
    bmain->filepath[0] = '\0';
  }

  /* Never a clean document: quitting or closing must ask, and a titled
   * project's Ctrl-S is now a deliberate write of the restored state. */
  WM_file_tag_modified();
  if (wm != nullptr) {
    for (wmWindow &win : wm->windows) {
      WM_window_title_refresh(wm, &win);
    }
  }
  WM_event_add_notifier(C, NC_WINDOW, nullptr);
  return OPERATOR_FINISHED;
}

/* -------------------------------------------------------------------- */
/** \name Undo stamp
 *
 * "Has the document changed since the last checkpoint jump?" is answered by
 * Blender's own undo stack: a file read resets it and every user action
 * pushes a step, while the chat's property writes and the re-title above do
 * not. Python has no view of the stack, so this operator writes a
 * fingerprint (step count, active step) into `WindowManager.mixie_chat_undo_stamp`
 * for `turn_checkpoints.undo_stamp()` to read straight back. Judging the same
 * question from depsgraph updates was wrong: a layout change (the island
 * expanding, an area changing type) flushes every ID and looked like an edit.
 * \{ */

static wmOperatorStatus mixie_chat_undo_stamp_exec(bContext *C, wmOperator * /*op*/)
{
  wmWindowManager *wm = CTX_wm_manager(C);
  if (wm == nullptr) {
    return OPERATOR_CANCELLED;
  }
  char stamp[192] = "";
  if (const UndoStack *ustack = ED_undo_stack_get()) {
    const UndoStep *active = ustack->step_active;
    BLI_snprintf(stamp,
                 sizeof(stamp),
                 "%d:%p:%s",
                 BLI_listbase_count(&ustack->steps),
                 static_cast<const void *>(active),
                 active ? active->name : "");
  }
  PointerRNA wm_ptr = RNA_id_pointer_create(&wm->id);
  PropertyRNA *prop = RNA_struct_find_property(&wm_ptr, "mixie_chat_undo_stamp");
  if (prop == nullptr) {
    return OPERATOR_CANCELLED;
  }
  RNA_property_string_set(&wm_ptr, prop, stamp);
  return OPERATOR_FINISHED;
}

void MIXIE_CHAT_OT_undo_stamp(wmOperatorType *ot)
{
  ot->name = "Undo Stamp";
  ot->idname = "MIXIE_CHAT_OT_undo_stamp";
  ot->description =
      "Write a fingerprint of the undo stack to WindowManager.mixie_chat_undo_stamp; "
      "used by the turn checkpoints to tell whether the document changed";

  ot->exec = mixie_chat_undo_stamp_exec;
  ot->flag = OPTYPE_INTERNAL;
}

/** \} */

void MIXIE_CHAT_OT_retitle_document(wmOperatorType *ot)
{
  ot->name = "Retitle Document";
  ot->idname = "MIXIE_CHAT_OT_retitle_document";
  ot->description =
      "Give the open document a file path (or none) without writing anything to disk; "
      "used by the turn checkpoint restore";

  ot->exec = mixie_chat_retitle_document_exec;
  ot->flag = OPTYPE_INTERNAL;

  RNA_def_string_file_path(ot->srna,
                           "filepath",
                           nullptr,
                           FILE_MAX,
                           "File Path",
                           "The document's path; empty leaves it untitled");
}

}  // namespace blender
