/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edundo
 *
 * Wrapper between `ED_undo.hh` and `BKE_undo_system.hh` API's.
 */

#include "CLG_log.h"

#include "BLI_sys_types.h"

#include "BLI_ghash.h"
#include "BLI_listbase.h"
#include "BLI_set.hh"

#include "DNA_ID.h"
#include "DNA_collection_types.h"
#include "DNA_mesh_types.h"
#include "DNA_node_types.h"
#include "DNA_object_types.h"
#include "DNA_scene_types.h"

#include "BKE_blender_undo.hh"
#include "BKE_context.hh"
#include "BKE_lib_query.hh"
#include "BKE_main.hh"
#include "BKE_node.hh"
#include "BKE_preview_image.hh"
#include "BKE_scene.hh"
#include "BKE_scene_runtime.hh"
#include "BKE_undo_system.hh"
#include "BKE_undo_tabs.hh"

#include "../depsgraph/DEG_depsgraph.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "ED_mesh.hh"
#include "ED_object.hh"
#include "ED_render.hh"
#include "ED_undo.hh"
#include "ED_util.hh"

#include "../blenloader/BLO_undofile.hh"

#include "undo_intern.hh"

namespace blender {

/* -------------------------------------------------------------------- */
/** \name Implements ED Undo System
 * \{ */

struct MemFileUndoStep {
  UndoStep step;
  MemFileUndoData *data;
};

static bool memfile_undosys_poll(bContext *C)
{
  /* other poll functions must run first, this is a catch-all. */

  if ((U.uiflag & USER_GLOBALUNDO) == 0) {
    return false;
  }

  /* Allow a single memfile undo step (the first). */
  UndoStack *ustack = ED_undo_stack_get();
  if ((ustack->step_active != nullptr) && (ED_undo_is_memfile_compatible(C) == false)) {
    return false;
  }
  return true;
}

static bool memfile_undosys_step_encode(bContext * /*C*/, Main *bmain, UndoStep *us_p)
{
  MemFileUndoStep *us = reinterpret_cast<MemFileUndoStep *>(us_p);

  /* Important we only use 'main' from the context (see: BKE_undosys_stack_init_from_main). */
  UndoStack *ustack = ED_undo_stack_get();

  if (bmain->is_memfile_undo_flush_needed) {
    ED_editors_flush_edits_ex(bmain, false, true);
  }

  /* can be null, use when set. */
  MemFileUndoStep *us_prev = reinterpret_cast<MemFileUndoStep *>(
      BKE_undosys_step_find_by_type(ustack, BKE_UNDOSYS_TYPE_MEMFILE));
  us->data = BKE_memfile_undo_encode(bmain, us_prev ? us_prev->data : nullptr);
  us->step.data_size = us->data->undo_size;

  /* Store the fact that we should not re-use old data with that undo step, and reset the Main
   * flag. */
  us->step.use_old_bmain_data = !bmain->use_memfile_full_barrier;
  bmain->use_memfile_full_barrier = false;

  return true;
}

static int memfile_undosys_step_id_reused_cb(LibraryIDLinkCallbackData *cb_data)
{
  ID *self_id = cb_data->self_id;
  ID *owner_id = cb_data->owner_id;
  ID **id_pointer = cb_data->id_pointer;
  /* Embedded IDs do not get tagged with #ID_TAG_UNDO_OLD_ID_REUSED_UNCHANGED currently (could be,
   * but would add extra processing, and by definition they always share that state with their
   * owner, as they are stored as 'regular data' in blend-files, not as independent IDs).
   *
   * NOTE: It seems that local IDs using embedded ones are never 'reused unchanged', this was
   * never caught before. However, if using `self_id` here, this assert gets triggered with
   * upcoming packed data. Probably because while packed data remains unchanged, it is handled like
   * regular local data by undo code, and like regular linked data. */
  BLI_assert((owner_id->tag & ID_TAG_UNDO_OLD_ID_REUSED_UNCHANGED) != 0);
  UNUSED_VARS_NDEBUG(owner_id);

  ID *id = *id_pointer;
  if (id != nullptr && !ID_IS_LINKED(id) && (id->tag & ID_TAG_UNDO_OLD_ID_REUSED_UNCHANGED) == 0) {
    bool do_stop_iter = true;
    if (GS(self_id->name) == ID_OB) {
      Object *ob_self = id_cast<Object *>(self_id);
      if (ob_self->type == OB_ARMATURE) {
        if (ob_self->data == id) {
          BLI_assert(GS(id->name) == ID_AR);
          if (ob_self->pose != nullptr) {
            /* We have a changed/re-read armature used by an unchanged armature object: our beloved
             * Bone pointers from the object's pose need their usual special treatment. */
            ob_self->pose->flag |= POSE_RECALC;
          }
        }
        else {
          /* Cannot stop iteration until we checked ob_self->data pointer... */
          do_stop_iter = false;
        }
      }
    }

    return do_stop_iter ? IDWALK_RET_STOP_ITER : IDWALK_RET_NOP;
  }

  return IDWALK_RET_NOP;
}

/**
 * Mixar per-tab undo (review 2026-10-02): a tab's partial restore frees the
 * edit-mode data of that tab's objects only. #ED_editors_exit frees every
 * object's, unsaved: an object another tab left in edit mode (the user modelled
 * in tab A, switched to tab B without leaving edit mode, pressed Ctrl-Z there)
 * lost every edit since the last memfile step and dropped out of edit mode. The
 * walk keeps that tab's datablocks as they are, its edit-mode data with them.
 */
static CLG_LogRef LOG_TABS = {"undo.tabs"};

static int memfile_undosys_editors_exit(Main *bmain)
{
  if (!BKE_undo_tabs_partial_active() || BKE_undo_tabs_partial_tab() == UNDO_TAB_DOCUMENT) {
    ED_editors_exit(bmain, false);
    return 0;
  }
  auto restored = [](const ID *id) {
    return id != nullptr &&
           BKE_undo_tabs_partial_decide(id->session_uid, true) == UndoPartialDecision::Restore;
  };
  int kept = 0;
  for (Object &ob : bmain->objects) {
    if (restored(&ob.id) || restored(static_cast<const ID *>(ob.data))) {
      if (ed::object::editmode_free_ex(bmain, &ob)) {
        DEG_id_tag_update(&ob.id, ID_RECALC_TRANSFORM | ID_RECALC_GEOMETRY);
      }
    }
    else if (ob.mode & (OB_MODE_EDIT | OB_MODE_SCULPT)) {
      kept++; /* kept with unflushed mode data (edit mesh, sculpt session) */
    }
  }
  ED_mesh_mirror_spatial_table_end(nullptr);
  ED_mesh_mirror_topo_table_end(nullptr);
  if (kept > 0) {
    CLOG_DEBUG(&LOG_TABS, "%d object(s) of other tabs kept in edit mode", kept);
  }
  return kept;
}

static void memfile_undosys_step_decode(
    bContext *C, Main *bmain, UndoStep *us_p, const eUndoStepDir undo_direction, bool /*is_final*/)
{
  BLI_assert(undo_direction != STEP_INVALID);

  bool use_old_bmain_data = true;

  if (USER_DEVELOPER_TOOL_TEST(&U, use_undo_legacy) || !(U.uiflag & USER_GLOBALUNDO)) {
    use_old_bmain_data = false;
  }
  else if (undo_direction == STEP_REDO) {
    /* The only time we should have to force a complete redo is when current step is tagged as a
     * redo barrier.
     * If previous step was not a memfile one should not matter here, current data in old bmain
     * should still always be valid for unchanged data-blocks. */
    if (us_p->use_old_bmain_data == false) {
      use_old_bmain_data = false;
    }
  }
  else if (undo_direction == STEP_UNDO) {
    /* Here we do not care whether current step is an undo barrier, since we are coming from
     * 'the future' we can still re-use old data. However, if *next* undo step
     * (i.e. the one immediately in the future, the one we are coming from)
     * is a barrier, then we have to force a complete undo.
     * Note that non-memfile undo steps **should** not be an issue anymore, since we handle
     * fine-grained update flags now.
     */
    UndoStep *us_next = us_p->next;
    if (us_next != nullptr) {
      if (us_next->use_old_bmain_data == false) {
        use_old_bmain_data = false;
      }
    }
  }

  /* Extract depsgraphs from current bmain (which may be freed during undo step reading),
   * and store them for re-use. */
  GHash *depsgraphs = nullptr;
  if (use_old_bmain_data) {
    depsgraphs = BKE_scene_undo_depsgraphs_extract(bmain);
  }

  const int kept_in_edit_mode = memfile_undosys_editors_exit(bmain);
  /* Ensure there's no preview job running. Unfinished previews will be scheduled for regeneration
   * via #PRV_TAG_RESTART_RENDERING in BKE_previewimg_blend_read. */
  ED_preview_kill_jobs(CTX_wm_manager(C), bmain);

  MemFileUndoStep *us = reinterpret_cast<MemFileUndoStep *>(us_p);
  BKE_memfile_undo_decode(us->data, undo_direction, use_old_bmain_data, C);

  /* Mixar per-tab undo (review 2026-10-02, Codex P1): a tab's partial restore
   * changed that tab's datablocks only, so only that tab's steps change their
   * applied state. Every other tab's sculpt / paint / text steps keep theirs: a
   * stroke another tab had undone stayed undone in its geometry, and marking it
   * applied made that tab's redo skip it (sculpt redo trusts the flag). A
   * whole-document restore (no tab) keeps the stock bookkeeping. */
  const uint32_t partial_tab = BKE_undo_tabs_partial_tab();
  auto bookkept = [&](const UndoStep *us_iter) {
    return !BKE_UNDOSYS_TYPE_IS_MEMFILE_SKIP(us_iter->type) &&
           (partial_tab == UNDO_TAB_DOCUMENT || us_iter->mixar_tab_uid == partial_tab);
  };
  for (UndoStep *us_iter = us_p->next; us_iter; us_iter = us_iter->next) {
    if (bookkept(us_iter)) {
      us_iter->is_applied = false;
    }
  }
  for (UndoStep *us_iter = us_p; us_iter; us_iter = us_iter->prev) {
    if (bookkept(us_iter)) {
      us_iter->is_applied = true;
    }
  }

  /* bmain has been freed. */
  bmain = CTX_data_main(C);
  if (kept_in_edit_mode > 0) {
    /* Mixar per-tab undo (the invariant test, 2026-10-02): another tab's object kept
     * its edit-mode data across this tab's restore, but the new Main starts with
     * no "flush needed": the next memfile step skipped the flush and was written
     * without that tab's edit-mode work, which an undo onto it then lost. */
    bmain->is_memfile_undo_flush_needed = true;
  }
  ED_editors_init_for_undo(bmain);

  if (use_old_bmain_data) {
    /* Restore previous depsgraphs into current bmain. */
    BKE_scene_undo_depsgraphs_restore(bmain, depsgraphs);

    /* We need to inform depsgraph about re-used old IDs that would be using newly read
     * data-blocks, at least evaluated copies need to be updated... */
    ID *id = nullptr;
    FOREACH_MAIN_ID_BEGIN (bmain, id) {
      if (id->tag & ID_TAG_UNDO_OLD_ID_REUSED_UNCHANGED) {
        BKE_library_foreach_ID_link(
            bmain, id, memfile_undosys_step_id_reused_cb, nullptr, IDWALK_READONLY);
      }

      if (GS(id->name) == ID_SCE) {
        Scene *scene = reinterpret_cast<Scene *>(id);
        /* TODO: We should be able to restore these depsgraphs properly as part of
         * #BKE_scene_undo_depsgraphs_restore but this is currently only done for depsgraphs in the
         * scene.depsgraph_hash map. So the safest option is to just delete the following
         * depsgraphs for now. */
        if (scene->compositing_node_group) {
          /* Ensure undo calls from the UI update the interactive compositor preview depsgraph, see
           * #compo_initjob. */
          bke::CompositorRuntime &compositor_runtime = scene->runtime->compositor;
          DEG_graph_free(compositor_runtime.preview_depsgraph);
          compositor_runtime.preview_depsgraph = nullptr;
        }

        if (scene->runtime->sequencer.depsgraph) {
          /* Ensure that the depsgraph created in #get_depsgraph_for_scene_strip are updated. */
          bke::SequencerRuntime &seq_runtime = scene->runtime->sequencer;
          DEG_graph_free(seq_runtime.depsgraph);
          seq_runtime.depsgraph = nullptr;
        }
      }

      /* NOTE: Tagging `ID_RECALC_SYNC_TO_EVAL` here should not be needed in practice, since
       * modified IDs should already have other depsgraph update tags anyway.
       * However, for the sake of consistency, it's better to effectively use it,
       * since content of that ID pointer does have been modified. */
      uint recalc_flags = id->recalc | ((id->tag & ID_TAG_UNDO_OLD_ID_REREAD_IN_PLACE) ?
                                            ID_RECALC_SYNC_TO_EVAL :
                                            IDRecalcFlag(0));
      /* Tag depsgraph to update data-block for changes that happened between the
       * current and the target state, see direct_link_id_restore_recalc(). */
      if (recalc_flags != 0) {
        DEG_id_tag_update_ex(bmain, id, recalc_flags);
      }

      bNodeTree *nodetree = bke::node_tree_from_id(id);
      if (nodetree != nullptr) {
        recalc_flags = nodetree->id.recalc;
        if (id->tag & ID_TAG_UNDO_OLD_ID_REREAD_IN_PLACE) {
          recalc_flags |= ID_RECALC_SYNC_TO_EVAL;
        }
        if (recalc_flags != 0) {
          DEG_id_tag_update_ex(bmain, &nodetree->id, recalc_flags);
        }
      }
      if (GS(id->name) == ID_SCE) {
        Scene *scene = id_cast<Scene *>(id);
        if (scene->master_collection != nullptr) {
          recalc_flags = scene->master_collection->id.recalc;
          if (id->tag & ID_TAG_UNDO_OLD_ID_REREAD_IN_PLACE) {
            recalc_flags |= ID_RECALC_SYNC_TO_EVAL;
          }
          if (recalc_flags != 0) {
            DEG_id_tag_update_ex(bmain, &scene->master_collection->id, recalc_flags);
          }
        }
      }
    }
    FOREACH_MAIN_ID_END;

    FOREACH_MAIN_ID_BEGIN (bmain, id) {
      /* Clear temporary tag. */
      id->tag &= ~(ID_TAG_UNDO_OLD_ID_REUSED_UNCHANGED | ID_TAG_UNDO_OLD_ID_REUSED_NOUNDO |
                   ID_TAG_UNDO_OLD_ID_REREAD_IN_PLACE);

      /* We only start accumulating from this point, any tags set up to here
       * are already part of the current undo state. This is done in a second
       * loop because DEG_id_tag_update may set tags on other datablocks. */
      id->recalc_after_undo_push = 0;
      bNodeTree *nodetree = bke::node_tree_from_id(id);
      if (nodetree != nullptr) {
        nodetree->id.recalc_after_undo_push = 0;
      }
      if (GS(id->name) == ID_SCE) {
        Scene *scene = id_cast<Scene *>(id);
        if (scene->master_collection != nullptr) {
          scene->master_collection->id.recalc_after_undo_push = 0;
        }
      }
      else if (GS(id->name) == ID_OB) {
        /* In some cases when using memfile undo in sculpt mode, the object but not the
         * corresponding mesh will be tagged for an update, leading to invalid data and crashes.
         *
         * This is a band-aid mitigation for the 5.1 release, not a proper fix of the underlying
         * problem.
         *
         * See #152087 for more details. */
        Object *object = reinterpret_cast<Object *>(id);
        if (object->type == OB_MESH) {
          Mesh *mesh = id_cast<Mesh *>(object->data);
          if (object->mode == OB_MODE_SCULPT && mesh) {
            DEG_id_tag_update_ex(bmain, &mesh->id, ID_RECALC_GEOMETRY);
          }
        }
      }
    }
    FOREACH_MAIN_ID_END;
  }

  WM_event_add_notifier(C, NC_SCENE | ND_LAYER_CONTENT, CTX_data_scene(C));
}

/**
 * Mixar per-tab undo (review 2026-10-01, R2): a memfile freed between two others
 * (the per-tab step limit frees steps between the tabs' reserves; upstream only
 * ever frees the oldest one or the redo branch). The previous memfile's
 * "identical in the next step" flags were written against the freed one; the
 * undo reader trusts them to keep an ID unchanged, so they are recomputed
 * against the memfile that follows now. A chunk of the next memfile that is not
 * its own (#MemFileChunk::is_identical) shares its buffer with the previous
 * memfile exactly when the bytes are the same: #BLO_memfile_merge hands a buffer
 * the freed memfile owned to the next one and clears that flag, so sharing a
 * buffer still means equal data.
 */
static void memfile_future_flags_recompute(MemFile *prev, const MemFile *next)
{
  Set<const char *> shared;
  for (const MemFileChunk &chunk : next->chunks) {
    if (chunk.is_identical) {
      shared.add(chunk.buf);
    }
  }
  for (MemFileChunk &chunk : prev->chunks) {
    chunk.is_identical_future = shared.contains(chunk.buf);
  }
}

static void memfile_undosys_step_free(UndoStep *us_p)
{
  /* To avoid unnecessary slow down, free backwards
   * (so we don't need to merge when clearing all). */
  MemFileUndoStep *us = reinterpret_cast<MemFileUndoStep *>(us_p);
  if (us_p->next != nullptr) {
    UndoStep *us_next_p = BKE_undosys_step_same_type_next(us_p);
    if (us_next_p != nullptr) {
      MemFileUndoStep *us_next = reinterpret_cast<MemFileUndoStep *>(us_next_p);
      BLO_memfile_merge(&us->data->memfile, &us_next->data->memfile);
      if (UndoStep *us_prev_p = (us_p->prev != nullptr) ? BKE_undosys_step_same_type_prev(us_p) :
                                                          nullptr)
      {
        MemFileUndoStep *us_prev = reinterpret_cast<MemFileUndoStep *>(us_prev_p);
        memfile_future_flags_recompute(&us_prev->data->memfile, &us_next->data->memfile);
      }
    }
  }

  BKE_memfile_undo_free(us->data);
}

/* Mixar per-tab undo: the conflict check reads a step's chunks (BKE_undo_tabs.hh). */
static const MemFile *memfile_undosys_step_memfile(const UndoStep *us_p)
{
  const MemFileUndoStep *us = reinterpret_cast<const MemFileUndoStep *>(us_p);
  return (us->data != nullptr) ? &us->data->memfile : nullptr;
}

void ED_memfile_undosys_type(UndoType *ut)
{
  BKE_undo_tabs_memfile_getter_set(memfile_undosys_step_memfile);
  ut->name = "Global Undo";
  ut->poll = memfile_undosys_poll;
  ut->step_encode = memfile_undosys_step_encode;
  ut->step_decode = memfile_undosys_step_decode;
  ut->step_free = memfile_undosys_step_free;

  ut->flags = 0;

  ut->step_size = sizeof(MemFileUndoStep);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Utilities
 * \{ */
bool ED_undosys_autosave_compatible(UndoStack *ustack)
{
  if (!ustack->step_active) {
    return false;
  }

  return ELEM(ustack->step_active->type, BKE_UNDOSYS_TYPE_MEMFILE, BKE_UNDOSYS_TYPE_IMAGE);
}

void ED_undosys_stack_memfile_id_changed_tag(UndoStack *ustack, ID *id)
{
  UndoStep *us = ustack->step_active;
  if (id == nullptr || us == nullptr || us->type != BKE_UNDOSYS_TYPE_MEMFILE) {
    return;
  }

  MemFile *memfile = &(reinterpret_cast<MemFileUndoStep *>(us))->data->memfile;
  for (MemFileChunk &mem_chunk : memfile->chunks) {
    if (mem_chunk.id_session_uid == id->session_uid) {
      mem_chunk.is_identical_future = false;
      break;
    }
  }
}

/** \} */

}  // namespace blender
