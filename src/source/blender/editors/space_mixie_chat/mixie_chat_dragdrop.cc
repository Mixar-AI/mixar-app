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

#include "DNA_ID.h"
#include "DNA_space_enums.h"
#include "DNA_space_types.h"
#include "DNA_image_types.h"
#include "DNA_windowmanager_types.h"

#include "BKE_context.hh"
#include "BKE_report.hh"

#include "ED_space_api.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"
#include "RNA_prototypes.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "mixie_chat_intern.hh"
/* Mixar 5.2 port: namespace wrap. */
namespace blender {

/* -------------------------------------------------------------------- */
/** \name Drop Image Operator
 * \{ */

static wmOperatorStatus mixie_chat_drop_image_exec(bContext *C, wmOperator *op)
{
  const char *attachment_operator = RNA_struct_property_is_set(op->ptr, "image_name") ?
                                        "MIXIE_CHAT_OT_add_image_from_blend" :
                                        "MIXIE_CHAT_OT_add_image_from_file";
  /* The capsule can appear before deferred Python UI registration finishes.
   * Never write attachment properties into the fallback OperatorProperties. */
  if (!WM_operatortype_find(attachment_operator, true)) {
    BKE_report(op->reports, RPT_WARNING, "Chat is still loading. Please drop the reference again.");
    return OPERATOR_CANCELLED;
  }
  if (ED_agent_bubble_is_resting_pill(C)) {
    /* A drop on the resting chat capsule explicitly targets the composer,
     * regardless of the tab that was active when the island was minimised.
     * Restore only on release, before validation so feedback has a full UI. */
    PointerRNA wm = RNA_id_pointer_create(&CTX_wm_manager(C)->id);
    PropertyRNA *tab = RNA_struct_find_property(&wm, "mixar_bubble_tab");
    int agent;
    if (tab && RNA_property_enum_value(C, &wm, tab, "AGENT", &agent)) {
      RNA_property_enum_set(&wm, tab, agent);
      RNA_property_update(C, &wm, tab);
    }
    WM_operator_name_call(
        C, "MIXAR_OT_bubble_restore", wm::OpCallContext::ExecDefault, nullptr, nullptr);
  }
  if (RNA_struct_property_is_set(op->ptr, "image_name")) {
    char name[MAX_ID_NAME - 2];
    RNA_string_get(op->ptr, "image_name", name);
    PointerRNA props = WM_operator_properties_create("MIXIE_CHAT_OT_add_image_from_blend");
    RNA_string_set(&props, "dropped_image_name", name);
    const auto result = WM_operator_name_call(C,
                                              "MIXIE_CHAT_OT_add_image_from_blend",
                                              wm::OpCallContext::ExecDefault,
                                              &props,
                                              nullptr);
    WM_operator_properties_free(&props);
    return wmOperatorStatus(result);
  }
  char filepath[FILE_MAX];
  RNA_string_get(op->ptr, "filepath", filepath);

  if (filepath[0] == '\0' && RNA_collection_length(op->ptr, "files") == 0) {
    BKE_report(op->reports, RPT_ERROR, "No file path provided");
    return OPERATOR_CANCELLED;
  }

  /* Forward to the registered Python operator for validation, duplicate
   * checking, and attachment management. */
  PointerRNA props = WM_operator_properties_create("MIXIE_CHAT_OT_add_image_from_file");
  RNA_string_set(&props, "filepath", filepath);
  RNA_string_set(&props, "directory", "");
  RNA_collection_clear(&props, "files");
  RNA_BEGIN (op->ptr, item, "files") {
    char *path = RNA_string_get_alloc(&item, "name", nullptr, 0, nullptr);
    PointerRNA file;
    RNA_collection_add(&props, "files", &file);
    RNA_string_set(&file, "name", path);
    MEM_delete_void(static_cast<void *>(path));
  }
  RNA_END;

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
  RNA_def_collection_runtime(ot->srna, "files", RNA_OperatorFileListElement, "Files", "Dropped paths");
  RNA_def_string(ot->srna, "image_name", nullptr, MAX_ID_NAME - 2, "Image", "Dropped image datablock");
  for (const char *name : {"filepath", "files", "image_name"}) {
    RNA_def_property_flag(RNA_struct_type_find_property(ot->srna, name), PROP_HIDDEN | PROP_SKIP_SAVE);
  }
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
  if (!area || !(area->spacetype == SPACE_AGENT_BUBBLE)) {
    return false;
  }
  if (area->spacetype == SPACE_AGENT_BUBBLE && !ED_agent_bubble_is_resting_pill(C)) {
    /* The HEADER map belongs only to the resting capsule. The status pill
     * above an open island and the island's tab strip are not composers. */
    const ARegion *region = CTX_wm_region(C);
    if (region && region->regiontype == RGN_TYPE_HEADER) {
      return false;
    }
    PointerRNA wm = RNA_id_pointer_create(&CTX_wm_manager(C)->id);
    PropertyRNA *tab = RNA_struct_find_property(&wm, "mixar_bubble_tab");
    int agent;
    if (!tab || !RNA_property_enum_value(C, &wm, tab, "AGENT", &agent) ||
        RNA_property_enum_get(&wm, tab) != agent)
    {
      return false;
    }
  }

  /* WM_drag_is_ID_type is also true for WM_DRAG_ASSET, but asset
   * payloads live outside drag->ids (ids.first is null). Only a
   * local Image ID can be source-filtered here. */
  if (drag->type == WM_DRAG_ID) {
    const auto *id = static_cast<const wmDragID *>(drag->ids.first);
    if (id && id->id && GS(id->id->name) == ID_IM) {
      const auto *image = reinterpret_cast<const Image *>(id->id);
      return !ELEM(image->source, IMA_SRC_MOVIE, IMA_SRC_SEQUENCE, IMA_SRC_VIEWER);
    }
    return false;
  }

  if (drag->type == WM_DRAG_PATH) {
    const char *path = WM_drag_get_single_path(drag);
    if (path && path[0] != '\0') {
      /* The agent chat has no video content part on the wire, so a movie
       * drop is refused here and the cursor shows it — otherwise the drop
       * looked accepted and only failed with a report after release. */
      if (WM_drag_has_path_file_type(drag, FILE_TYPE_MOVIE)) {
        return false;
      }
      /* Accept any other file-path drop in chat and delegate validation to
       * the Python attachment operator (validate_image_file). Relying
       * strictly on WM_drag_get_path_file_type() can reject valid OS drag
       * sources. */
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
  RNA_struct_property_unset(drop->ptr, "filepath");
  RNA_struct_property_unset(drop->ptr, "image_name");
  RNA_collection_clear(drop->ptr, "files");
  if (drag->type == WM_DRAG_PATH) {
    for (const std::string &path : WM_drag_get_paths(drag)) {
      PointerRNA file;
      RNA_collection_add(drop->ptr, "files", &file);
      RNA_string_set(&file, "name", path.c_str());
    }
  }
  else if (drag->type == WM_DRAG_ID) {
    const auto *id = static_cast<const wmDragID *>(drag->ids.first);
    if (id && id->id && GS(id->id->name) == ID_IM) {
      RNA_string_set(drop->ptr, "image_name", id->id->name + 2);
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
  ListBaseT<wmDropBox> *lb = WM_dropboxmap_find(
      "Agent Chat", SPACE_AGENT_BUBBLE, RGN_TYPE_WINDOW);

  WM_dropbox_add(lb,
                 "MIXIE_CHAT_OT_drop_image",
                 mixie_chat_image_drop_poll,
                 mixie_chat_image_drop_copy,
                 nullptr,
                 nullptr);

  /* Footer region (input area, implemented as TOOLS region).
   * Users naturally drag images onto the input field. */
  ListBaseT<wmDropBox> *lb_footer = WM_dropboxmap_find(
      "Agent Chat Composer", SPACE_AGENT_BUBBLE, RGN_TYPE_TOOLS);

  WM_dropbox_add(lb_footer,
                 "MIXIE_CHAT_OT_drop_image",
                 mixie_chat_image_drop_poll,
                 mixie_chat_image_drop_copy,
                 nullptr,
                 nullptr);

  ListBaseT<wmDropBox> *lb_pill = WM_dropboxmap_find(
      "Agent Bubble Pill", SPACE_AGENT_BUBBLE, RGN_TYPE_HEADER);
  WM_dropbox_add(lb_pill,
                 "MIXIE_CHAT_OT_drop_image",
                 mixie_chat_image_drop_poll,
                 mixie_chat_image_drop_copy,
                 nullptr,
                 nullptr);

  /* The asset picker's tile drag lands in a 3D viewport
   * (mixie_chat_asset_picker_drop.cc). */
  mixie_chat_asset_pick_dropboxes();
}

/** \} */
}  // namespace blender
