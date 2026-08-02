/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Native moodboard movie preview window.
 */

#include "mixie_moodboard_ops_common.hh"

#include "DNA_sequence_types.h"
#include "DNA_workspace_types.h"

#include "BLI_listbase.h"
#include "BLI_string_utf8.h"

#include "BKE_scene.hh"

#include "SEQ_add.hh"
#include "SEQ_sequencer.hh"
#include "SEQ_time.hh"

namespace blender::ed::mixie {

struct MoodboardVideoPreviewSession {
  Main *bmain;
  wmWindow *window;
  WorkSpace *workspace;
  Scene *workspace_scene;
  Scene *scene;
};

static int moodboard_video_preview_handler(bContext * /*C*/,
                                           const wmEvent * /*event*/,
                                           void * /*user_data*/)
{
  return WM_UI_HANDLER_CONTINUE;
}

static Scene *moodboard_video_preview_fallback_scene(Main *bmain,
                                                     Scene *preview_scene,
                                                     Scene *preferred_scene)
{
  if (preferred_scene && BLI_findindex(&bmain->scenes, preferred_scene) != -1) {
    return preferred_scene;
  }

  LISTBASE_FOREACH (Scene *, scene, &bmain->scenes) {
    if (scene != preview_scene) {
      return scene;
    }
  }
  return nullptr;
}

static void moodboard_video_preview_session_remove(bContext *C, void *user_data)
{
  MoodboardVideoPreviewSession *session = static_cast<MoodboardVideoPreviewSession *>(user_data);
  Main *bmain = session->bmain;
  Scene *preview_scene = session->scene;

  if (bmain && preview_scene && BLI_findindex(&bmain->scenes, preview_scene) != -1) {
    if (C && ED_screen_animation_playing(CTX_wm_manager(C)) == CTX_wm_screen(C)) {
      ED_screen_animation_play(C, 0, 0);
    }

    Scene *fallback_scene = moodboard_video_preview_fallback_scene(
        bmain, preview_scene, session->workspace_scene);
    if (session->workspace && BLI_findindex(&bmain->workspaces, session->workspace) != -1 &&
        session->workspace->sequencer_scene == preview_scene)
    {
      session->workspace->sequencer_scene = fallback_scene;
    }

    /* A Sequencer strip needs a scene, but a preview must never modify or be
     * saved with the user's scene. Restore any window that still points at
     * the isolated preview scene before deleting it. */
    if (session->window && WM_window_get_active_scene(session->window) == preview_scene) {
      if (fallback_scene) {
        if (C) {
          ED_screen_scene_change(C, session->window, fallback_scene, false);
        }
        else {
          session->window->scene = fallback_scene;
        }
      }
    }

    BKE_id_delete(bmain, preview_scene);
  }

  MEM_delete(session);
}

static void moodboard_video_preview_session_replace(bContext *C,
                                                     wmWindow *window,
                                                     Main *bmain,
                                                     Scene *preview_scene)
{
  /* WM_window_open_temp reuses an existing temporary Sequencer window. Free
   * its old scene and strip before attaching the new preview. */
  WM_event_free_ui_handler_all(C,
                               &window->handlers,
                               moodboard_video_preview_handler,
                               moodboard_video_preview_session_remove);

  MoodboardVideoPreviewSession *session = MEM_new<MoodboardVideoPreviewSession>(__func__);
  session->bmain = bmain;
  session->window = window;
  session->workspace = WM_window_get_active_workspace(window);
  session->workspace_scene = session->workspace ? session->workspace->sequencer_scene : nullptr;
  session->scene = preview_scene;
  if (session->workspace) {
    /* Blender 5 stores the Video Sequencer's active scene on the workspace,
     * separately from win->scene. Point it at this window's private scene for
     * the lifetime of the preview, then restore it in the remove callback. */
    session->workspace->sequencer_scene = preview_scene;
  }
  WM_event_add_ui_handler(C,
                          &window->handlers,
                          moodboard_video_preview_handler,
                          moodboard_video_preview_session_remove,
                          session,
                          eWM_EventHandlerFlag(0));
}

static Image *moodboard_item_image(PointerRNA *scene_ptr, const int index)
{
  PropertyRNA *items_prop = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  if (!items_prop || index < 0 ||
      index >= RNA_property_collection_length(scene_ptr, items_prop)) {
    return nullptr;
  }

  PointerRNA item_ptr;
  RNA_property_collection_lookup_int(scene_ptr, items_prop, index, &item_ptr);
  PropertyRNA *image_prop = RNA_struct_find_property(&item_ptr, "image");
  if (!image_prop) {
    return nullptr;
  }

  PointerRNA image_ptr = RNA_property_pointer_get(&item_ptr, image_prop);
  return static_cast<Image *>(image_ptr.data);
}

bool moodboard_item_is_video(PointerRNA *scene_ptr, const int index)
{
  const Image *image = moodboard_item_image(scene_ptr, index);
  return image && image->source == IMA_SRC_MOVIE;
}

bool moodboard_open_video_preview(bContext *C, PointerRNA *scene_ptr,
                                  const int index, ReportList *reports)
{
  Main *bmain = CTX_data_main(C);
  Image *image = moodboard_item_image(scene_ptr, index);
  if (!image || image->source != IMA_SRC_MOVIE) {
    BKE_report(reports, RPT_WARNING, "Selected moodboard item is not a video");
    return false;
  }

  /* Decode frame one before creating a window. Besides validating the source,
   * this discovers the dimensions used to fit the preview. */
  ImageUser preview_user{};
  BKE_imageuser_default(&preview_user);
  preview_user.frames = 0;
  preview_user.framenr = 1;

  void *lock = nullptr;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, &preview_user, &lock);
  if (!ibuf || ibuf->x <= 0 || ibuf->y <= 0) {
    BKE_image_release_ibuf(image, ibuf, lock);
    BKE_reportf(reports, RPT_ERROR, "Cannot decode video: %s", image->filepath);
    return false;
  }
  const int video_width = ibuf->x;
  const int video_height = ibuf->y;
  BKE_image_release_ibuf(image, ibuf, lock);

  /* The Video Sequencer is scene-backed. Build a private scene containing
   * only this movie strip so previewing cannot touch the user's timeline. */
  Scene *preview_scene = BKE_scene_add(bmain, "Mixar Video Preview");
  preview_scene->id.tag |= ID_TAG_RUNTIME;
  preview_scene->r.xsch = video_width;
  preview_scene->r.ysch = video_height;
  preview_scene->r.size = 100;
  preview_scene->r.sfra = 1;
  preview_scene->r.cfra = 1;

  Editing *editing = seq::editing_ensure(preview_scene);
  seq::LoadData load_data{};
  seq::add_load_data_init(&load_data, image->id.name + 2, image->filepath, 1, 1);
  load_data.flags = seq::SEQ_LOAD_MOVIE_SYNC_FPS | seq::SEQ_LOAD_SET_VIEW_TRANSFORM;
  load_data.fit_method = SEQ_SCALE_TO_FIT;

  Strip *movie_strip = seq::add_movie_strip(
      bmain, preview_scene, editing->current_strips(), &load_data);
  if (!movie_strip) {
    BKE_id_delete(bmain, preview_scene);
    BKE_reportf(reports, RPT_ERROR, "Cannot open video in Sequencer: %s", image->filepath);
    return false;
  }
  preview_scene->r.efra = std::max(seq::time_right_handle_frame_get(preview_scene, movie_strip) - 1,
                                  1);

  char title[MAX_ID_NAME + 64];
  SNPRINTF_UTF8(title, "Video Preview - %s", image->id.name + 2);
  wmWindow *window = WM_window_open_temp(C, title, SPACE_SEQ, false);
  if (!window) {
    BKE_id_delete(bmain, preview_scene);
    BKE_report(reports, RPT_ERROR, "Failed to open video preview window");
    return false;
  }

  SpaceSeq *sequencer = CTX_wm_space_seq(C);
  ScrArea *area = CTX_wm_area(C);
  if (!sequencer || !area) {
    BKE_id_delete(bmain, preview_scene);
    BKE_report(reports, RPT_ERROR, "Video Sequencer preview is unavailable");
    return false;
  }

  moodboard_video_preview_session_replace(C, window, bmain, preview_scene);
  ED_screen_scene_change(C, window, preview_scene, false);

  sequencer->view = SEQ_VIEW_PREVIEW;
  sequencer->mainb = SEQ_DRAW_IMG_IMBUF;
  sequencer->render_size = SEQ_RENDER_SIZE_SCENE;
  sequencer->flag |= SEQ_ZOOM_TO_FIT;
  ED_area_tag_refresh(area);
  ED_area_tag_redraw(area);
  WM_event_add_notifier(C, NC_SCENE | ND_FRAME, preview_scene);

  /* Start immediately, while respecting Blender's single global playback
   * session if another editor is already playing. Spacebar remains the
   * standard pause/resume control inside the preview. */
  if (!ED_screen_animation_playing(CTX_wm_manager(C))) {
    ED_screen_animation_play(C, -1, 1);
  }
  return true;
}

}  // namespace blender::ed::mixie
