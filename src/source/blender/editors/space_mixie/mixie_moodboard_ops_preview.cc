/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Runtime-only inline playback for moodboard movies.
 *
 * A movie plays ONCE, start to finish, at its native frame rate and with its
 * sound, then rests on its first frame. Only its own play/pause affordance (or
 * a double-click) stops it early: where the pointer goes meanwhile is
 * irrelevant, so a user can watch a clip while working elsewhere on the board.
 * The clock and the audio track live in the shared session store.
 */

#include "mixie_moodboard_ops_common.hh"

#include "BKE_callbacks.hh"
#include "BKE_global.hh"

#include "BLI_timer.h"

#include "mixie_moodboard_video_session.hh"

namespace blender::ed::mixie {

static constexpr double MOODBOARD_VIDEO_REDRAW_SECONDS = 1.0 / 30.0;

/* Board playback state lives in the shared session store
 * (mixie_moodboard_video_session.cc) under owner nullptr; preview players own
 * their own sessions, so a clip can play on the board and in a preview
 * independently. */
static constexpr const void *BOARD_OWNER = nullptr;
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

/**
 * The one clock behind every playing board movie. A BLI timer rather than a
 * window timer: it needs no context, so the tick that sees the last movie play
 * through is also the one that retires the redraw -- without waiting for an
 * event to reach the canvas, which may never come once the pointer is gone.
 */
static double video_redraw_tick(uintptr_t /*uuid*/, void * /*user_data*/)
{
  video_sessions_prune(G_MAIN);
  video_sessions_advance(BOARD_OWNER);
  const bool any_playing = video_sessions_any_playing(BOARD_OWNER);
  /* Sent on the final tick too: that redraw puts the poster frame and the
   * play glyph back once a movie has finished. */
  WM_main_add_notifier(NC_SPACE | ND_SPACE_MIXIE, nullptr);
  return any_playing ? MOODBOARD_VIDEO_REDRAW_SECONDS : -1.0;
}

static void video_redraw_tick_ensure()
{
  const uintptr_t tick_id = uintptr_t(&g_video_tick_identity);
  if (!BLI_timer_is_registered(tick_id)) {
    /* Persistent (BLI timers otherwise end on a file load); a load retires it
     * explicitly, with the old file's sessions (board_sessions_load_pre). */
    BLI_timer_register(
        tick_id, video_redraw_tick, nullptr, nullptr, MOODBOARD_VIDEO_REDRAW_SECONDS, true);
  }
}

bool moodboard_item_is_video(PointerRNA *scene_ptr, const int index)
{
  const Image *image = moodboard_item_image(scene_ptr, index);
  return image && image->source == IMA_SRC_MOVIE;
}

/* A file load (Open, Revert, File > New) frees every Image, and the next file
 * may allocate one at a freed address. Board sessions belong to the file, so
 * their sound stops and they are forgotten before its data goes. Zen hosts the
 * board in a View3D drawer, so the Mixie region's exit (which also releases
 * them) never runs there. Preview players need nothing: the load cancels every
 * modal handler, and the player's cancel releases its own sessions. */
static void board_sessions_load_pre(Main * /*bmain*/,
                                    PointerRNA ** /*pointers*/,
                                    int /*pointers_num*/,
                                    void * /*arg*/)
{
  mixie_moodboard_video_playback_shutdown();
}

static void board_sessions_load_pre_register()
{
  static bCallbackFuncStore store = {};
  if (store.func != nullptr) {
    return;
  }
  store.func = board_sessions_load_pre;
  store.alloc = false;
  BKE_callback_add(&store, BKE_CB_EVT_LOAD_PRE);
}

static MoodboardVideoSession *board_session(bContext *C,
                                            PointerRNA *scene_ptr,
                                            const int index,
                                            ReportList *reports)
{
  Image *image = moodboard_item_image(scene_ptr, index);
  if (!image || image->source != IMA_SRC_MOVIE) {
    BKE_report(reports, RPT_WARNING, "Selected moodboard item is not a video");
    return nullptr;
  }
  Main *bmain = CTX_data_main(C);
  board_sessions_load_pre_register();
  video_sessions_prune(bmain);
  MoodboardVideoSession *session = video_session_ensure(bmain, image, BOARD_OWNER);
  if (!session) {
    BKE_reportf(reports, RPT_ERROR, "Cannot decode video: %s", image->filepath);
  }
  return session;
}

bool moodboard_toggle_video_playback(bContext *C,
                                     PointerRNA *scene_ptr,
                                     const int index,
                                     ReportList *reports)
{
  MoodboardVideoSession *session = board_session(C, scene_ptr, index, reports);
  if (!session) {
    return false;
  }
  /* A movie plays ONCE, start to finish, then rests on its first frame. Only
   * its own play/pause affordance (or a double-click) stops it early: where
   * the pointer goes meanwhile is irrelevant. */
  video_session_toggle(CTX_data_main(C), *session);
  if (session->playing) {
    video_redraw_tick_ensure();
  }
  WM_event_add_notifier(C, NC_SPACE | ND_SPACE_MIXIE, nullptr);
  return true;
}

bool moodboard_toggle_video_mute(bContext *C,
                                 PointerRNA *scene_ptr,
                                 const int index,
                                 ReportList *reports)
{
  MoodboardVideoSession *session = board_session(C, scene_ptr, index, reports);
  if (!session) {
    return false;
  }
  video_session_set_muted(*session, !session->muted);
  WM_event_add_notifier(C, NC_SPACE | ND_SPACE_MIXIE, nullptr);
  return true;
}

int moodboard_video_playback_frame(Image *image, bool *r_is_playing)
{
  MoodboardVideoSession *session = video_session_find(image, BOARD_OWNER);
  if (!session) {
    if (r_is_playing) {
      *r_is_playing = false;
    }
    return 1;
  }
  /* Advance before reporting: the frame that ends playback must draw with
   * the play glyph, not a pause glyph over the poster. */
  const int frame = video_session_frame(*session);
  if (r_is_playing) {
    *r_is_playing = session->playing;
  }
  return frame;
}

bool moodboard_video_is_muted(const Image *image)
{
  const MoodboardVideoSession *session = video_session_find(image, BOARD_OWNER);
  return session && session->muted;
}

const char *moodboard_video_audio_state(const Image *image)
{
  const MoodboardVideoSession *session = video_session_find(image, BOARD_OWNER);
  return session ? video_session_audio_state(*session) : "stopped";
}

void mixie_moodboard_video_playback_shutdown()
{
  BLI_timer_unregister(uintptr_t(&g_video_tick_identity));
  /* Board playback only: an open preview player keeps its own session. */
  video_sessions_release_owner(BOARD_OWNER);
}

}  // namespace blender::ed::mixie
