/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Renaming a canvas frame IN PLACE.
 *
 * The pencil above a selected frame, F2, a double-click on its title strip
 * and the zero-question Ctrl+G all land here. None of them opens a dialog:
 * they turn the name already painted above the frame into a text field,
 * exactly where that name is, so the user edits the thing they are looking
 * at. Enter applies, Esc puts the old name back, a click elsewhere applies --
 * the outliner's rename, on the board.
 *
 * This file holds the operator and the one piece of state it needs: WHICH
 * frame is being renamed. The field itself is drawn by the frame action row
 * (mixie_draw_moodboard_frame_actions.cc) through #ui::button_active_only.
 *
 * Runtime-only and keyed on the scene's session uid, like the media rename
 * and the link-drag preview: a rename in flight is not scene data, must never
 * be saved, and must not leak across a scene switch.
 */

#include "mixie_moodboard_ops_common.hh"

namespace blender::ed::mixie {

struct FrameRenameState {
  uint32_t scene_uid = 0;
  char frame_id[MIXIE_GRAPH_ID_BUF] = "";
};

static FrameRenameState g_frame_rename;

static uint32_t rename_scene_uid(const Scene *scene)
{
  return scene ? scene->id.session_uid : 0;
}

bool moodboard_frame_rename_is_active(const Scene *scene, const char *frame_id)
{
  return g_frame_rename.frame_id[0] != '\0' &&
         g_frame_rename.scene_uid == rename_scene_uid(scene) && frame_id &&
         STREQ(g_frame_rename.frame_id, frame_id);
}

void moodboard_frame_rename_end()
{
  g_frame_rename.scene_uid = 0;
  g_frame_rename.frame_id[0] = '\0';
}

/* The one selected frame's id, or empty when that is ambiguous. F2 arrives
 * with nothing set; the pencil and Ctrl+G always pass an id. */
static bool single_selected_frame_id(PointerRNA *scene_ptr,
                                     char r_frame_id[MIXIE_GRAPH_ID_BUF])
{
  r_frame_id[0] = '\0';
  PropertyRNA *frames = RNA_struct_find_property(scene_ptr, "mixie_moodboard_frames");
  if (!frames) {
    return false;
  }
  int found = 0;
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(scene_ptr, frames, &iter);
  while (iter.valid) {
    if (RNA_boolean_get(&iter.ptr, "selected")) {
      if (++found > 1) {
        break;
      }
      mixie_rna_string_get_clamped(&iter.ptr, "frame_id", r_frame_id, MIXIE_GRAPH_ID_BUF);
    }
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
  if (found != 1) {
    r_frame_id[0] = '\0';
  }
  return r_frame_id[0] != '\0';
}

static bool frame_id_exists(PointerRNA *scene_ptr, const char *frame_id)
{
  PropertyRNA *frames = RNA_struct_find_property(scene_ptr, "mixie_moodboard_frames");
  if (!frames || !frame_id || !frame_id[0]) {
    return false;
  }
  bool found = false;
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(scene_ptr, frames, &iter);
  while (iter.valid && !found) {
    char candidate[MIXIE_GRAPH_ID_BUF];
    mixie_rna_string_get_clamped(&iter.ptr, "frame_id", candidate, sizeof(candidate));
    found = STREQ(candidate, frame_id);
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
  return found;
}

static wmOperatorStatus moodboard_rename_frame_exec(bContext *C, wmOperator *op)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return OPERATOR_CANCELLED;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);

  char frame_id[MIXIE_GRAPH_ID_BUF];
  RNA_string_get(op->ptr, "frame_id", frame_id);
  if (frame_id[0] ? !frame_id_exists(&scene_ptr, frame_id) :
                    !single_selected_frame_id(&scene_ptr, frame_id))
  {
    BKE_report(op->reports, RPT_WARNING, "Select one frame to rename");
    return OPERATOR_CANCELLED;
  }

  /* The field appears on the next redraw and takes focus by itself, so there
   * is nothing to open here -- and no dialog, which is the point: a frame's
   * name is one word and it is already on screen. */
  g_frame_rename.scene_uid = rename_scene_uid(scene);
  BLI_strncpy(g_frame_rename.frame_id, frame_id, sizeof(g_frame_rename.frame_id));
  if (ScrArea *area = CTX_wm_area(C)) {
    ED_area_tag_redraw(area);
  }
  return OPERATOR_FINISHED;
}

}  // namespace blender::ed::mixie

namespace blender {
void MIXIE_OT_moodboard_rename_frame(wmOperatorType *ot)
{
  ot->name = "Rename Frame";
  ot->idname = "MIXIE_OT_moodboard_rename_frame";
  ot->description =
      "Rename this frame in place. Enter applies the new name, Escape keeps the old one";
  ot->exec = blender::ed::mixie::moodboard_rename_frame_exec;
  ot->poll = blender::ed::mixie::moodboard_poll;

  /* No UNDO: the rename is applied by the text field's own RNA write, which
   * pushes its own step. Starting to rename is not an edit. */
  ot->flag = OPTYPE_REGISTER;

  /* PROP_SKIP_SAVE: a remembered id would put the field on a different frame
   * than the one whose pencil was pressed, and F2 -- which sets nothing --
   * would never reach the selected-frame fallback. */
  PropertyRNA *prop = RNA_def_string(ot->srna,
                                     "frame_id",
                                     nullptr,
                                     MIXIE_GRAPH_ID_BUF,
                                     "Frame ID",
                                     "Frame to rename; empty renames the one selected frame");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
}
}  // namespace blender
