/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Renaming a reference image or movie IN PLACE on the canvas.
 *
 * The pencil above a selected reference (and F2 with one selected) does not
 * open a dialog. It turns the name already painted above the tile into a text
 * field, exactly where the name is, so the user edits the thing they are
 * looking at: Enter applies, Esc puts the old name back, a click elsewhere
 * applies -- the outliner's rename, on the board.
 *
 * This file holds the operator and the one piece of state it needs: WHICH
 * media is being renamed. The field itself is drawn by the media action row
 * (mixie_draw_moodboard_media_actions.cc) through #UI_but_active_only, the
 * mechanism Blender's own temporary rename buttons use -- the button has to be
 * re-created on every redraw while it is active, and the draw learns the edit
 * has ended when that call returns false and hands back here to clear the
 * state.
 *
 * Runtime-only and keyed on the scene's session uid, like the link-drag
 * preview: a rename in flight is not scene data, must never be saved, and must
 * not leak across a scene switch.
 */

#include "mixie_moodboard_ops_common.hh"

namespace blender::ed::mixie {

struct MediaRenameState {
  uint32_t scene_uid = 0;
  char media_id[MIXIE_GRAPH_ID_BUF] = "";
};

static MediaRenameState g_media_rename;

static uint32_t scene_uid(const Scene *scene)
{
  return scene ? scene->id.session_uid : 0;
}

bool moodboard_media_rename_is_active(const Scene *scene, const char *media_id)
{
  return g_media_rename.media_id[0] != '\0' && g_media_rename.scene_uid == scene_uid(scene) &&
         media_id && STREQ(g_media_rename.media_id, media_id);
}

void moodboard_media_rename_end()
{
  g_media_rename.scene_uid = 0;
  g_media_rename.media_id[0] = '\0';
}

static void moodboard_media_rename_begin(const Scene *scene, const char *media_id)
{
  g_media_rename.scene_uid = scene_uid(scene);
  BLI_strncpy(g_media_rename.media_id, media_id, sizeof(g_media_rename.media_id));
}

/* The one selected reference with a graph id, or empty when there is not
 * exactly one. F2 reaches this with no id; the pencil always passes one. */
static bool single_selected_media_id(PointerRNA *scene_ptr, char r_media_id[MIXIE_GRAPH_ID_BUF])
{
  r_media_id[0] = '\0';
  PropertyRNA *items = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  if (!items) {
    return false;
  }
  int found = 0;
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(scene_ptr, items, &iter);
  while (iter.valid) {
    PointerRNA item = iter.ptr;
    PropertyRNA *embedded = RNA_struct_find_property(&item, "embedded_node_id");
    const bool standalone = !embedded || RNA_property_string_length(&item, embedded) == 0;
    if (standalone && RNA_boolean_get(&item, "selected")) {
      if (++found > 1) {
        break;
      }
      mixie_rna_string_get_clamped(&item, "node_id", r_media_id, MIXIE_GRAPH_ID_BUF);
    }
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
  if (found != 1) {
    r_media_id[0] = '\0';
  }
  return r_media_id[0] != '\0';
}

static bool media_id_exists(PointerRNA *scene_ptr, const char *media_id)
{
  PropertyRNA *items = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  if (!items || !media_id || !media_id[0]) {
    return false;
  }
  bool found = false;
  CollectionPropertyIterator iter{};
  RNA_property_collection_begin(scene_ptr, items, &iter);
  while (iter.valid && !found) {
    char item_id[MIXIE_GRAPH_ID_BUF];
    mixie_rna_string_get_clamped(&iter.ptr, "node_id", item_id, sizeof(item_id));
    PointerRNA image_ptr = RNA_pointer_get(&iter.ptr, "image");
    found = image_ptr.data && STREQ(item_id, media_id);
    RNA_property_collection_next(&iter);
  }
  RNA_property_collection_end(&iter);
  return found;
}

static wmOperatorStatus moodboard_rename_media_exec(bContext *C, wmOperator *op)
{
  Scene *scene = CTX_data_scene(C);
  if (!scene) {
    return OPERATOR_CANCELLED;
  }
  PointerRNA scene_ptr = RNA_id_pointer_create(&scene->id);

  char media_id[MIXIE_GRAPH_ID_BUF];
  RNA_string_get(op->ptr, "media_id", media_id);
  if (media_id[0] ? !media_id_exists(&scene_ptr, media_id) :
                    !single_selected_media_id(&scene_ptr, media_id))
  {
    BKE_report(op->reports, RPT_WARNING, "Select one reference image or video to rename");
    return OPERATOR_CANCELLED;
  }

  /* The field appears on the next redraw and takes focus by itself; nothing
   * to open here. A rename already in flight on another tile is simply
   * abandoned -- its text button loses the active state when it is no longer
   * drawn, which applies what was typed (the outliner does the same). */
  moodboard_media_rename_begin(scene, media_id);
  if (ScrArea *area = CTX_wm_area(C)) {
    ED_area_tag_redraw(area);
  }
  return OPERATOR_FINISHED;
}

}  // namespace blender::ed::mixie

void MIXIE_OT_moodboard_rename_media(wmOperatorType *ot)
{
  ot->name = "Rename Media";
  ot->idname = "MIXIE_OT_moodboard_rename_media";
  ot->description =
      "Rename this image or video in place. Enter applies the new name, Escape keeps the old "
      "one";

  ot->exec = blender::ed::mixie::moodboard_rename_media_exec;
  ot->poll = blender::ed::mixie::moodboard_poll;

  /* No UNDO here: the rename itself is applied by the text field's own RNA
   * write on the Image name, which pushes its own undo step. Starting to
   * rename is not an edit. */
  ot->flag = OPTYPE_REGISTER;

  /* PROP_SKIP_SAVE: a REGISTER operator refills unset properties from the last
   * run, so a remembered id would put the field on a different tile than the
   * one whose pencil was pressed -- and F2, which sets nothing, would never
   * reach the selected-media fallback. */
  PropertyRNA *prop = RNA_def_string(ot->srna,
                                     "media_id",
                                     nullptr,
                                     MIXIE_GRAPH_ID_BUF,
                                     "Media ID",
                                     "Board image or video (by its own graph id) to rename; "
                                     "empty renames the one selected reference");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
}
