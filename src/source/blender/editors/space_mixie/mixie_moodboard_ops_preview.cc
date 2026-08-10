/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Runtime-only inline playback for moodboard movies.
 */

#include "mixie_moodboard_ops_common.hh"

#include <unordered_map>

#include "BLI_listbase.h"

#include "MOV_read.hh"

namespace blender::ed::mixie {

static constexpr double MOODBOARD_VIDEO_REDRAW_FPS = 30.0;
static constexpr float MOODBOARD_VIDEO_FALLBACK_FPS = 24.0f;

struct MoodboardVideoPlayback {
  bool playing = false;
  int current_frame = 1;
  int start_frame = 1;
  int frame_count = 1;
  float fps = MOODBOARD_VIDEO_FALLBACK_FPS;
  double started_at = 0.0;
  Scene *owner_scene = nullptr;
  int item_index = -1;
};

static std::unordered_map<Image *, MoodboardVideoPlayback> g_video_playback;
static wmTimer *g_video_redraw_timer = nullptr;

static Image *moodboard_item_image(PointerRNA *scene_ptr, const int index)
{
  PropertyRNA *items_prop = RNA_struct_find_property(scene_ptr, "mixie_moodboard_images");
  if (!items_prop || index < 0 ||
      index >= RNA_property_collection_length(scene_ptr, items_prop))
  {
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

static int playback_frame_at(MoodboardVideoPlayback &playback, const double now)
{
  if (!playback.playing || playback.frame_count <= 1) {
    return playback.current_frame;
  }

  const double elapsed_seconds = std::max(now - playback.started_at, 0.0);
  const int elapsed_frames = int(elapsed_seconds * playback.fps);
  const int zero_based_frame = (playback.start_frame - 1 + elapsed_frames) %
                               playback.frame_count;
  playback.current_frame = zero_based_frame + 1;
  return playback.current_frame;
}

static bool any_video_playing()
{
  for (const auto &entry : g_video_playback) {
    if (entry.second.playing) {
      return true;
    }
  }
  return false;
}

static void prune_dead_playback_entries(bContext *C)
{
  /* Playback state is keyed on `Image *`. Generated movies are owned by their
   * inference node and freed with it, so deleting a node mid-playback would
   * otherwise leave an entry keyed on a dangling pointer — which a later
   * datablock allocated at the same address would inherit, appearing to start
   * mid-playback. Validate against Main instead of trusting the key. */
  Main *bmain = CTX_data_main(C);
  if (!bmain) {
    return;
  }
  for (auto it = g_video_playback.begin(); it != g_video_playback.end();) {
    if (BLI_findindex(&bmain->images, it->first) == -1) {
      it = g_video_playback.erase(it);
    }
    else {
      ++it;
    }
  }
}

static void video_redraw_timer_update(bContext *C)
{
  prune_dead_playback_entries(C);
  wmWindowManager *wm = CTX_wm_manager(C);
  if (!wm) {
    return;
  }

  if (any_video_playing()) {
    if (!g_video_redraw_timer) {
      wmWindow *window = CTX_wm_window(C);
      if (window) {
        g_video_redraw_timer = WM_event_timer_add_notifier(
            wm, window, NC_SPACE | ND_SPACE_MIXIE, 1.0 / MOODBOARD_VIDEO_REDRAW_FPS);
      }
    }
  }
  else if (g_video_redraw_timer) {
    WM_event_timer_remove(wm, nullptr, g_video_redraw_timer);
    g_video_redraw_timer = nullptr;
  }
}

static bool stop_video_playback_outside_tile(bContext *C,
                                             Scene *hovered_scene,
                                             const int hovered_index)
{
  const double now = BLI_time_now_seconds();
  bool stopped = false;
  for (auto &entry : g_video_playback) {
    MoodboardVideoPlayback &playback = entry.second;
    if (playback.playing &&
        (playback.owner_scene != hovered_scene || playback.item_index != hovered_index))
    {
      playback_frame_at(playback, now);
      playback.playing = false;
      stopped = true;
    }
  }

  if (stopped) {
    video_redraw_timer_update(C);
    WM_event_add_notifier(C, NC_SPACE | ND_SPACE_MIXIE, nullptr);
  }
  return stopped;
}

static int hovered_video_index_from_event(bContext *C,
                                          PointerRNA *scene_ptr,
                                          const wmEvent *event)
{
  ARegion *region = CTX_wm_region(C);
  if (!region || event->xy[0] < region->winrct.xmin || event->xy[0] > region->winrct.xmax ||
      event->xy[1] < region->winrct.ymin || event->xy[1] > region->winrct.ymax)
  {
    return -1;
  }

  const int region_x = event->xy[0] - region->winrct.xmin;
  const int region_y = event->xy[1] - region->winrct.ymin;
  float mouse_x, mouse_y;
  UI_view2d_region_to_view(&region->v2d, region_x, region_y, &mouse_x, &mouse_y);

  float pos_x, pos_y, scale, width, height;
  const int index = moodboard_find_image_under_mouse(
      scene_ptr, mouse_x, mouse_y, &pos_x, &pos_y, &scale, &width, &height);
  if (index >= 0 && moodboard_item_is_video(scene_ptr, index)) {
    return index;
  }
  /* Node-owned movies are skipped by the standalone-tile hit-test above, so
   * without this the pointer would read as "outside every video tile" the
   * moment it moves and stop the playback it just started. */
  return moodboard_find_node_preview_video_under_mouse(
      scene_ptr, mouse_x, mouse_y, nullptr);
}

static wmOperatorStatus moodboard_video_hover_invoke(bContext *C,
                                                     wmOperator * /*op*/,
                                                     const wmEvent *event)
{
  if (!any_video_playing()) {
    return OPERATOR_PASS_THROUGH;
  }

  Scene *scene = CTX_data_scene(C);
  PointerRNA scene_ptr = scene ? RNA_id_pointer_create(&scene->id) : PointerRNA_NULL;
  ARegion *region = CTX_wm_region(C);
  const int hovered_index = scene && region && region->regiontype == RGN_TYPE_WINDOW ?
                                hovered_video_index_from_event(C, &scene_ptr, event) :
                                -1;
  stop_video_playback_outside_tile(C, scene, hovered_index);
  return OPERATOR_PASS_THROUGH;
}

bool moodboard_item_is_video(PointerRNA *scene_ptr, const int index)
{
  const Image *image = moodboard_item_image(scene_ptr, index);
  return image && image->source == IMA_SRC_MOVIE;
}

bool moodboard_toggle_video_playback(bContext *C,
                                     PointerRNA *scene_ptr,
                                     const int index,
                                     ReportList *reports)
{
  Image *image = moodboard_item_image(scene_ptr, index);
  if (!image || image->source != IMA_SRC_MOVIE) {
    BKE_report(reports, RPT_WARNING, "Selected moodboard item is not a video");
    return false;
  }

  auto playback_it = g_video_playback.find(image);
  if (playback_it == g_video_playback.end()) {
    /* Decoding the first frame validates the source and initializes Image::anims,
     * which exposes the movie's native duration and frame rate. */
    ImageUser image_user{};
    BKE_imageuser_default(&image_user);
    image_user.frames = 0;
    image_user.framenr = 1;

    void *lock = nullptr;
    ImBuf *ibuf = BKE_image_acquire_ibuf(image, &image_user, &lock);
    if (!ibuf || ibuf->x <= 0 || ibuf->y <= 0) {
      BKE_image_release_ibuf(image, ibuf, lock);
      BKE_reportf(reports, RPT_ERROR, "Cannot decode video: %s", image->filepath);
      return false;
    }
    BKE_image_release_ibuf(image, ibuf, lock);

    MoodboardVideoPlayback playback;
    playback.frame_count = std::max(image_user.frames, 1);
    if (ImageAnim *image_anim = static_cast<ImageAnim *>(image->anims.first)) {
      if (image_anim->anim) {
        playback.frame_count = std::max(
            MOV_get_duration_frames(image_anim->anim, IMB_TC_RECORD_RUN), 1);
        const float native_fps = MOV_get_fps(image_anim->anim);
        if (native_fps > 0.0f) {
          playback.fps = native_fps;
        }
      }
    }
    playback_it = g_video_playback.emplace(image, playback).first;
  }

  MoodboardVideoPlayback &playback = playback_it->second;
  const double now = BLI_time_now_seconds();
  if (playback.playing) {
    playback_frame_at(playback, now);
    playback.playing = false;
  }
  else {
    playback.start_frame = playback.current_frame;
    playback.started_at = now;
    playback.owner_scene = static_cast<Scene *>(scene_ptr->data);
    playback.item_index = index;
    playback.playing = true;
  }

  video_redraw_timer_update(C);
  WM_event_add_notifier(C, NC_SPACE | ND_SPACE_MIXIE, nullptr);
  return true;
}

int moodboard_video_playback_frame(Image *image, bool *r_is_playing)
{
  const auto playback_it = g_video_playback.find(image);
  if (playback_it == g_video_playback.end()) {
    if (r_is_playing) {
      *r_is_playing = false;
    }
    return 1;
  }

  MoodboardVideoPlayback &playback = playback_it->second;
  if (r_is_playing) {
    *r_is_playing = playback.playing;
  }
  return playback_frame_at(playback, BLI_time_now_seconds());
}

void mixie_moodboard_video_playback_shutdown(wmWindowManager *wm)
{
  if (wm && g_video_redraw_timer) {
    WM_event_timer_remove(wm, nullptr, g_video_redraw_timer);
  }
  g_video_redraw_timer = nullptr;
  g_video_playback.clear();
}

}  // namespace blender::ed::mixie

void MIXIE_OT_moodboard_video_hover(wmOperatorType *ot)
{
  ot->name = "Moodboard Video Hover Monitor";
  ot->idname = "MIXIE_OT_moodboard_video_hover";
  ot->description = "Stop inline moodboard video playback when the pointer leaves its tile";

  ot->invoke = blender::ed::mixie::moodboard_video_hover_invoke;
  ot->poll = blender::ed::mixie::moodboard_poll;
  ot->flag = OPTYPE_INTERNAL;
}
