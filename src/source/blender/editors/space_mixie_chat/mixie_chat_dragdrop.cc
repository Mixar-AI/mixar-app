/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixiechat
 *
 * Drag-and-drop support for Mixie Chat.
 * Allows dropping image files into the chat to add them as attachments.
 *
 * Architecture note: The drop operator must be a C++ operator because
 * WM_dropbox_add() validates the operator name at registration time
 * (during C++ startup), before Python operators are loaded. The C++
 * operator forwards the filepath to the Python attachment logic via
 * WM_operator_name_call at drop time, when Python is fully available.
 */

#include "MEM_guardedalloc.h"

#include "BLI_utildefines.h"

#include "DNA_space_enums.h"
#include "DNA_space_types.h"

#include "BKE_context.hh"
#include "BKE_report.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"

/* -------------------------------------------------------------------- */
/** \name Drop Image Operator
 * \{ */

static wmOperatorStatus mixie_chat_drop_image_exec(bContext *C, wmOperator *op)
{
  char filepath[FILE_MAX];
  RNA_string_get(op->ptr, "filepath", filepath);

  if (filepath[0] == '\0') {
    BKE_report(op->reports, RPT_ERROR, "No file path provided");
    return OPERATOR_CANCELLED;
  }

  /* Forward to the Python operator that handles validation, duplicate
   * checking, and attachment management. By drop time Python is loaded. */
  PointerRNA props = PointerRNA_NULL;
  WM_operator_properties_create(&props, "MIXIE_CHAT_OT_add_image_from_file");
  RNA_string_set(&props, "filepath", filepath);

  int result = WM_operator_name_call(C,
                                     "MIXIE_CHAT_OT_add_image_from_file",
                                     blender::wm::OpCallContext::ExecDefault,
                                     &props,
                                     nullptr);
  WM_operator_properties_free(&props);

  return wmOperatorStatus(result);
}

void MIXIE_CHAT_OT_drop_image(wmOperatorType *ot)
{
  ot->name = "Drop Image to Chat";
  ot->idname = "MIXIE_CHAT_OT_drop_image";
  ot->description = "Add a dropped image as a chat attachment";

  ot->exec = mixie_chat_drop_image_exec;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;

  RNA_def_string(ot->srna,
                 "filepath",
                 nullptr,
                 FILE_MAX,
                 "File Path",
                 "Path to image file");
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Image Drop Poll
 * \{ */

static bool mixie_chat_image_drop_poll(bContext *C,
                                       wmDrag *drag,
                                       const wmEvent * /*event*/)
{
  /* SPACE_AGENT_BUBBLE reuses mixie_chat_main_region_init /
   * mixie_chat_footer_region_init, so it already carries these dropbox
   * handlers; without accepting its spacetype here the poll rejected every
   * drop onto the floating bubble. Same dual-spacetype contract as every
   * other shared chat callback (selection, hit-testing, code copy, ...). */
  ScrArea *area = CTX_wm_area(C);
  if (!area || !ELEM(area->spacetype, SPACE_MIXIE_CHAT, SPACE_AGENT_BUBBLE)) {
    return false;
  }

  if (drag->type == WM_DRAG_PATH) {
    const char *path = WM_drag_get_single_path(drag);
    if (path && path[0] != '\0') {
      /* Accept any file-path drop in chat and delegate validation to the
       * Python attachment operator (validate_image_file). Relying strictly on
       * WM_drag_get_path_file_type() can reject valid OS drag sources. */
      return true;
    }
  }

  return false;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Image Drop Copy
 * \{ */

static void mixie_chat_image_drop_copy(bContext * /*C*/,
                                       wmDrag *drag,
                                       wmDropBox *drop)
{
  if (drag->type == WM_DRAG_PATH) {
    const char *path = WM_drag_get_single_path(drag);
    if (path) {
      RNA_string_set(drop->ptr, "filepath", path);
    }
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Dropbox Registration
 * \{ */

void mixie_chat_dropboxes()
{
  /* Main region (chat messages area). */
  ListBase *lb = WM_dropboxmap_find(
      "Mixie Chat", SPACE_MIXIE_CHAT, RGN_TYPE_WINDOW);

  WM_dropbox_add(lb,
                 "MIXIE_CHAT_OT_drop_image",
                 mixie_chat_image_drop_poll,
                 mixie_chat_image_drop_copy,
                 nullptr,
                 nullptr);

  /* Footer region (input area, implemented as TOOLS region).
   * Users naturally drag images onto the input field. */
  ListBase *lb_footer = WM_dropboxmap_find(
      "Mixie Chat Footer", SPACE_MIXIE_CHAT, RGN_TYPE_TOOLS);

  WM_dropbox_add(lb_footer,
                 "MIXIE_CHAT_OT_drop_image",
                 mixie_chat_image_drop_poll,
                 mixie_chat_image_drop_copy,
                 nullptr,
                 nullptr);
}

/** \} */
