/* SPDX-FileCopyrightText: 2025 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 *
 * General Mixie operators for Mixie3D mode.
 * Moodboard operators are in mixie_moodboard_ops.cc
 */

#include <cstdio>

#include "MEM_guardedalloc.h"

#include "DNA_scene_types.h"
#include "DNA_screen_types.h"
#include "DNA_space_types.h"

#include "BKE_context.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "ED_screen.hh"

#include "mixie_intern.hh"

using namespace blender::ed::mixie;

/* -------------------------------------------------------------------- */
/** \name Mixie3D Preview Select Operator
 * \{ */

static bool sam3d_preview_poll(bContext *C)
{
  /* SAM3D previews in main canvas are disabled - SAM3D is now a sidebar panel only */
  SpaceLink *sl = CTX_wm_space_data(C);
  if (sl && sl->spacetype == SPACE_MIXIE) {
    return false;  /* Always moodboard mode now, previews handled by panel */
  }
  return false;
}

static wmOperatorStatus sam3d_preview_select_invoke(bContext *C,
                                                    wmOperator * /*op*/,
                                                    const wmEvent *event)
{
  Scene *scene = CTX_data_scene(C);
  ARegion *region = CTX_wm_region(C);

  if (!scene || !region) {
    return OPERATOR_CANCELLED;
  }

  /* Check if click is on delete button first */
  int delete_idx = mixie_get_sam3d_preview_delete_at_position(
      C, region, event->mval[0], event->mval[1]);

  if (delete_idx >= 0) {
    /* Delete button clicked - pass through to let delete operator handle it */
    return OPERATOR_PASS_THROUGH;
  }

  /* Check if click is on a preview thumbnail */
  int idx = mixie_get_sam3d_preview_at_position(C, region, event->mval[0], event->mval[1]);

  if (idx < 0) {
    return OPERATOR_PASS_THROUGH;
  }

  /* Set the selected history index */
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  RNA_int_set(&scene_ptr, "mixie_selected_segmented_index", idx);

  /* Trigger redraw */
  WM_event_add_notifier(C, NC_SPACE | ND_SPACE_MIXIE, nullptr);
  ED_area_tag_redraw(CTX_wm_area(C));

  return OPERATOR_FINISHED;
}

void MIXIE_OT_sam3d_preview_select(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Select Mixie3D Preview";
  ot->idname = "MIXIE_OT_sam3d_preview_select";
  ot->description = "Select a segmented image from the preview history";

  /* api callbacks */
  ot->invoke = sam3d_preview_select_invoke;
  ot->poll = sam3d_preview_poll;

  /* flags */
  ot->flag = 0;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Mixie3D Preview Delete Operator
 * \{ */

static wmOperatorStatus sam3d_preview_delete_invoke(bContext *C,
                                                    wmOperator * /*op*/,
                                                    const wmEvent *event)
{
  Scene *scene = CTX_data_scene(C);
  ARegion *region = CTX_wm_region(C);

  if (!scene || !region) {
    return OPERATOR_CANCELLED;
  }

  /* Check if click is on a delete button */
  int idx = mixie_get_sam3d_preview_delete_at_position(C, region, event->mval[0], event->mval[1]);

  if (idx < 0) {
    return OPERATOR_PASS_THROUGH;
  }

  /* Remove the history item at this index */
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);
  PropertyRNA *history_prop = RNA_struct_find_property(&scene_ptr, "mixie_segmented_history");

  if (!history_prop) {
    return OPERATOR_CANCELLED;
  }

  /* Remove from collection */
  RNA_property_collection_remove(&scene_ptr, history_prop, idx);

  /* Update selected index if needed */
  int selected_idx = RNA_int_get(&scene_ptr, "mixie_selected_segmented_index");
  int new_count = RNA_property_collection_length(&scene_ptr, history_prop);

  if (selected_idx >= new_count) {
    RNA_int_set(&scene_ptr, "mixie_selected_segmented_index", new_count > 0 ? new_count - 1 : -1);
  }
  else if (selected_idx > idx) {
    /* Adjust selected index since an item before it was removed */
    RNA_int_set(&scene_ptr, "mixie_selected_segmented_index", selected_idx - 1);
  }

  /* Trigger redraw */
  WM_event_add_notifier(C, NC_SPACE | ND_SPACE_MIXIE, nullptr);
  ED_area_tag_redraw(CTX_wm_area(C));

  return OPERATOR_FINISHED;
}

void MIXIE_OT_sam3d_preview_delete(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Delete Mixie3D Preview";
  ot->idname = "MIXIE_OT_sam3d_preview_delete";
  ot->description = "Delete a segmented image from the preview history";

  /* api callbacks */
  ot->invoke = sam3d_preview_delete_invoke;
  ot->poll = sam3d_preview_poll;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;
}

/** \} */
