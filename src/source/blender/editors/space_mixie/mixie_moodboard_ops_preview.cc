/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Runtime-only inline playback for moodboard movies.
 *
 * A movie plays ONCE, start to finish, at its native frame rate, then rests on
 * its first frame. Only its own play/pause affordance (or a double-click) stops
 * it early: where the pointer goes meanwhile is irrelevant, so a user can watch
 * a clip while working elsewhere on the board.
 */

#include "mixie_moodboard_ops_common.hh"

#include <unordered_map>

#include "BKE_global.hh"

#include "BLI_listbase.h"
#include "BLI_timer.h"

#include "MOV_read.hh"

namespace blender::ed::mixie {

static constexpr double MOODBOARD_VIDEO_REDRAW_SECONDS = 1.0 / 30.0;
static constexpr float MOODBOARD_VIDEO_FALLBACK_FPS = 24.0f;

struct MoodboardVideoPlayback {
  bool playing = false;
  int current_frame = 1;
  int start_frame = 1;
  int frame_count = 1;
  float fps = MOODBOARD_VIDEO_FALLBACK_FPS;
  double started_at = 0.0;
};

static std::unordered_map<Image *, MoodboardVideoPlayback> g_video_playback;
/** Only its address is used: the BLI timer id of the playback redraw tick. */
static char g_video_tick_identity;

Image *moodboard_item_image(PointerRNA *scene_ptr, const int index)
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
  if (!playback.playing) {
    return playback.current_frame;
  }

  const double elapsed_seconds = std::max(now - playback.started_at, 0.0);
  const int frame = playback.start_frame + int(elapsed_seconds * playback.fps);
  if (frame > playback.frame_count) {
    /* Played through. Rest on the first frame -- the poster the tile showed
     * before it was started -- so the next press plays the movie again. */
    playback.playing = false;
    playback.current_frame = 1;
    return playback.current_frame;
  }
  playback.current_frame = frame;
  return playback.current_frame;
}

static void prune_dead_playback_entries(Main *bmain)
{
  /* Playback state is keyed on `Image *`. Generated movies are owned by their
   * inference node and freed with it, so deleting a node mid-playback would
   * otherwise leave an entry keyed on a dangling pointer — which a later
   * datablock allocated at the same address would inherit, appearing to start
   * mid-playback. Validate against Main instead of trusting the key. */
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

/**
 * The one clock behind every playing movie. A BLI timer rather than a window
 * timer: it needs no context, so the tick that sees the last movie play
 * through is also the one that retires the redraw -- without waiting for an
 * event to reach the canvas, which may never come once the pointer is gone.
 */
static double video_redraw_tick(uintptr_t /*uuid*/, void * /*user_data*/)
{
  prune_dead_playback_entries(G_MAIN);
  const double now = BLI_time_now_seconds();
  bool any_playing = false;
  for (auto &entry : g_video_playback) {
    playback_frame_at(entry.second, now);
    any_playing |= entry.second.playing;
  }
  /* Sent on the final tick too: that redraw puts the poster frame and the
   * play glyph back once a movie has finished. */
  WM_main_add_notifier(NC_SPACE | ND_SPACE_MIXIE, nullptr);
  return any_playing ? MOODBOARD_VIDEO_REDRAW_SECONDS : -1.0;
}

static void video_redraw_tick_ensure()
{
  const uintptr_t tick_id = uintptr_t(&g_video_tick_identity);
  if (!BLI_timer_is_registered(tick_id)) {
    /* Persistent: across a file load the tick prunes the old file's entries
     * against the new Main and then retires itself. */
    BLI_timer_register(
        tick_id, video_redraw_tick, nullptr, nullptr, MOODBOARD_VIDEO_REDRAW_SECONDS, true);
  }
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

  prune_dead_playback_entries(CTX_data_main(C));
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
            MOV_get_duration_frames(image_anim->anim), 1);
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
  /* Settle first: a movie that played through since the last tick is
   * finished, and this press must start it again rather than "pause" it. */
  playback_frame_at(playback, now);
  if (playback.playing) {
    playback.playing = false;
  }
  else {
    playback.start_frame = playback.current_frame;
    playback.started_at = now;
    playback.playing = true;
    video_redraw_tick_ensure();
  }

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
  /* Advance before reporting: the frame that ends playback must draw with
   * the play glyph, not a pause glyph over the poster. */
  const int frame = playback_frame_at(playback, BLI_time_now_seconds());
  if (r_is_playing) {
    *r_is_playing = playback.playing;
  }
  return frame;
}

void mixie_moodboard_video_playback_shutdown()
{
  BLI_timer_unregister(uintptr_t(&g_video_tick_identity));
  g_video_playback.clear();
}

}  // namespace blender::ed::mixie
