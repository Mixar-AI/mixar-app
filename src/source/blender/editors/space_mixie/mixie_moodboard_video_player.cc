/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief The video preview player: a movie in its own window, with real controls.
 *
 * Opened by a movie card's Preview control (and the media row's Preview
 * button) through #MIXIE_OT_moodboard_preview_media, which creates the window
 * with an Image Editor in it. That editor is only the frame renderer here: its
 * header, toolbar, sidebar and footer are hidden, and the image is always
 * fitted to the window. This operator then runs modal in that window and owns
 * everything else:
 *
 * - its own playback session (sound on), independent of the board card;
 * - the controls, painted by a window draw callback over the picture:
 *   play/pause, a scrubbable timeline, mute and a volume bar;
 * - all pointer and key input, so Image Editor gestures (sampling, zoom,
 *   N/T panels) never reach the hidden editor. Space toggles play, Esc closes.
 *
 * Closing from Esc cannot free the window from inside its own modal
 * handler, so the player finishes and a context-free timer closes the window
 * at the top of the event loop. The OS close button goes through
 * wm_window_close() and cancels the player, which releases the session.
 */

#include "mixie_moodboard_ops_common.hh"

#include <algorithm>
#include <string>
#include <vector>

#include "BKE_image.hh"
#include "BKE_lib_id.hh"
#include "BKE_screen.hh"
#include "BKE_wm_runtime.hh"

#include "BLI_listbase.h"
#include "BLI_listbase_iterator.hh"
#include "BLI_rect.h"
#include "BLI_timer.h"

#include "DNA_space_types.h"

#include "ED_mixar_area_chrome.hh"

#include "../interface/interface_qa_inspect.hh"

#include "mixie_moodboard_video_player.hh"
#include "mixie_moodboard_video_session.hh"

namespace blender {
/* wm_window.cc: not in a public header (see space_agent_bubble.cc). */
void wm_window_close(bContext *C, wmWindowManager *wm, wmWindow *win);
}  // namespace blender

namespace blender::ed::mixie {

static constexpr double PLAYER_TICK_SECONDS = 1.0 / 30.0;
/** Live players, for the QA target provider (which only has the area). */
static std::vector<VideoPlayer *> g_players;

/* -------------------------------------------------------------------- */
/** \name Deferred window close
 * \{ */

static std::vector<wmWindow *> g_windows_to_close;
/* The one application context (created once in main()); the close tick runs
 * outside any handler, where the WM's own BLI timers run with it. */
static bContext *g_player_context = nullptr;
static char g_close_tick_identity;

static double close_windows_tick(uintptr_t /*uuid*/, void * /*user_data*/)
{
  std::vector<wmWindow *> windows;
  windows.swap(g_windows_to_close);
  wmWindowManager *wm = g_player_context ? CTX_wm_manager(g_player_context) : nullptr;
  if (!wm) {
    return -1.0;
  }
  for (wmWindow *win : windows) {
    /* Only a window that still exists: the user may have closed it already. */
    if (BLI_findindex(&wm->windows, win) != -1) {
      wm_window_close(g_player_context, wm, win);
    }
  }
  return -1.0;
}

static void request_window_close(wmWindow *win)
{
  g_windows_to_close.push_back(win);
  const uintptr_t tick_id = uintptr_t(&g_close_tick_identity);
  if (!BLI_timer_is_registered(tick_id)) {
    BLI_timer_register(tick_id, close_windows_tick, nullptr, nullptr, 0.0, false);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Session and frame
 * \{ */

static MoodboardVideoSession *player_session(bContext *C, VideoPlayer &player)
{
  /* Re-resolved every time: a file load or a cleared board can drop sessions,
   * and the movie itself may be gone. */
  Main *bmain = CTX_data_main(C);
  if (!bmain || BLI_findindex(&bmain->images, player.image) == -1) {
    return nullptr;
  }
  return video_session_ensure(bmain, player.image, &player);
}

static void player_sync_frame(const Scene *scene,
                              VideoPlayer &player,
                              MoodboardVideoSession &session)
{
  SpaceImage *sima = static_cast<SpaceImage *>(player.area->spacedata.first);
  if (!sima || sima->spacetype != SPACE_IMAGE) {
    return;
  }
  /* The picture follows the session, never the scene frame. The editor's
   * own refresh recomputes `framenr` from the scene frame, so a frame written
   * directly would snap back: instead the start frame is shifted until the
   * scene frame lands on the session frame, which every recompute agrees
   * with. frame_calc also tags the GPU texture when the frame changes. */
  const int cfra = scene ? scene->r.cfra : 1;
  sima->iuser.flag &= ~IMA_ANIM_ALWAYS;
  sima->iuser.cycl = false;
  sima->iuser.frames = session.frame_count;
  sima->iuser.offset = 0;
  sima->iuser.sfra = cfra - video_session_frame(session) + 1;
  BKE_image_user_frame_calc(player.image, &sima->iuser, cfra);

  /* Always fit the whole movie to the window, also after a resize. */
  if (ARegion *region = BKE_area_find_region_type(player.area, RGN_TYPE_WINDOW)) {
    const float winx = float(BLI_rcti_size_x(&region->winrct) + 1);
    const float winy = float(BLI_rcti_size_y(&region->winrct) + 1);
    if (session.width > 0 && session.height > 0) {
      sima->zoom = std::min(winx / session.width, winy / session.height);
      sima->xof = 0.0f;
      sima->yof = 0.0f;
    }
  }
  ED_area_tag_redraw(player.area);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Operator
 * \{ */

static void player_release(bContext *C, wmOperator *op)
{
  VideoPlayer *player = static_cast<VideoPlayer *>(op->customdata);
  if (!player) {
    return;
  }
  if (player->draw_handle) {
    WM_draw_cb_exit(player->win, player->draw_handle);
  }
  if (player->timer) {
    WM_event_timer_remove(CTX_wm_manager(C), player->win, player->timer);
  }
  video_sessions_release_owner(player);
  g_players.erase(std::remove(g_players.begin(), g_players.end(), player), g_players.end());
  MEM_delete(player);
  op->customdata = nullptr;
}

static bool area_is_player(const ScrArea *area)
{
  return std::any_of(
      g_players.begin(), g_players.end(), [&](const VideoPlayer *p) { return p->area == area; });
}

static void hide_editor_chrome(ScrArea *area)
{
  /* No edge arrows or reveal tabs for the hidden regions, no navigation
   * gizmos over the picture: the window shows the movie and our controls. */
  ED_area_mixar_chromeless_set(area_is_player);
  if (SpaceImage *sima = static_cast<SpaceImage *>(area->spacedata.first)) {
    sima->gizmo_flag |= SI_GIZMO_HIDE;
  }
  area->flag |= AREA_FLAG_ACTIONZONES_UPDATE;
  for (ARegion &region : area->regionbase) {
    if (region.regiontype != RGN_TYPE_WINDOW) {
      region.flag |= RGN_FLAG_HIDDEN;
    }
  }
  if (ARegion *main_region = BKE_area_find_region_type(area, RGN_TYPE_WINDOW)) {
    ED_area_tag_region_size_update(area, main_region);
  }
}

static wmOperatorStatus video_player_invoke(bContext *C, wmOperator *op, const wmEvent * /*event*/)
{
  Main *bmain = CTX_data_main(C);
  wmWindow *win = CTX_wm_window(C);
  ScrArea *area = CTX_wm_area(C);
  if (!bmain || !win || !area || area->spacetype != SPACE_IMAGE) {
    return OPERATOR_CANCELLED;
  }
  char name[MAX_ID_NAME - 2];
  RNA_string_get(op->ptr, "image", name);
  Image *image = reinterpret_cast<Image *>(BKE_libblock_find_name(bmain, ID_IM, name));
  if (!image || image->source != IMA_SRC_MOVIE) {
    BKE_report(op->reports, RPT_WARNING, "Nothing to play: not a video");
    return OPERATOR_CANCELLED;
  }

  VideoPlayer *player = MEM_new<VideoPlayer>(__func__);
  player->win = win;
  player->area = area;
  player->image = image;
  op->customdata = player;
  MoodboardVideoSession *session = player_session(C, *player);
  if (!session) {
    BKE_reportf(op->reports, RPT_ERROR, "Cannot decode video: %s", image->filepath);
    player_release(C, op);
    return OPERATOR_CANCELLED;
  }

  g_player_context = C;
  g_players.push_back(player);
  hide_editor_chrome(area);
  player->draw_handle = WM_draw_cb_activate(win, video_player_draw, player);
  player->timer = WM_event_timer_add(CTX_wm_manager(C), win, TIMER, PLAYER_TICK_SECONDS);
  /* A preview is opened to be watched: it starts at once, with sound. */
  video_session_play(bmain, *session);
  player_sync_frame(CTX_data_scene(C), *player, *session);
  WM_event_add_modal_handler(C, op);
  return OPERATOR_RUNNING_MODAL;
}

static void player_drag_update(bContext *C, VideoPlayer &player, const int xy[2])
{
  MoodboardVideoSession *session = player_session(C, player);
  if (!session) {
    return;
  }
  const PlayerLayout l = video_player_layout(player.area);
  if (player.drag == PlayerDrag::Timeline) {
    video_session_seek(CTX_data_main(C),
                       *session,
                       video_player_bar_fraction(l.timeline, xy[0]) * video_session_duration(*session));
  }
  else if (player.drag == PlayerDrag::Volume) {
    video_session_set_volume(*session, video_player_bar_fraction(l.volume, xy[0]));
    video_session_set_muted(*session, session->volume <= 0.0f);
  }
  player_sync_frame(CTX_data_scene(C), player, *session);
}

static wmOperatorStatus player_press(bContext *C, wmOperator *op, const wmEvent *event)
{
  VideoPlayer &player = *static_cast<VideoPlayer *>(op->customdata);
  MoodboardVideoSession *session = player_session(C, player);
  if (!session) {
    return OPERATOR_RUNNING_MODAL;
  }
  Main *bmain = CTX_data_main(C);
  switch (video_player_control_at(player.area, event->xy)) {
    case PLAYER_SOUND:
      video_session_set_muted(*session, !session->muted);
      if (!session->muted && session->volume <= 0.0f) {
        video_session_set_volume(*session, 1.0f);
      }
      break;
    case PLAYER_TIMELINE:
      player.drag = PlayerDrag::Timeline;
      /* Scrubbing holds the picture still under the pointer, then resumes. */
      player.resume_after_scrub = session->playing;
      video_session_pause(*session);
      player_drag_update(C, player, event->xy);
      break;
    case PLAYER_VOLUME:
      player.drag = PlayerDrag::Volume;
      player_drag_update(C, player, event->xy);
      break;
    default:
      /* The play button, or anywhere on the picture. */
      video_session_toggle(bmain, *session);
      break;
  }
  player_sync_frame(CTX_data_scene(C), player, *session);
  return OPERATOR_RUNNING_MODAL;
}

static wmOperatorStatus video_player_modal(bContext *C, wmOperator *op, const wmEvent *event)
{
  VideoPlayer &player = *static_cast<VideoPlayer *>(op->customdata);
  MoodboardVideoSession *session = player_session(C, player);
  if (!session) {
    /* The movie was removed from the file: nothing left to show. */
    wmWindow *win = player.win;
    player_release(C, op);
    request_window_close(win);
    return OPERATOR_FINISHED;
  }

  switch (event->type) {
    case TIMER:
      if (event->customdata == player.timer) {
        player_sync_frame(CTX_data_scene(C), player, *session);
        return OPERATOR_RUNNING_MODAL;
      }
      return OPERATOR_PASS_THROUGH;
    case MOUSEMOVE: {
      if (player.drag != PlayerDrag::None) {
        player_drag_update(C, player, event->xy);
      }
      const int hovered = video_player_control_at(player.area, event->xy);
      if (hovered != player.hovered) {
        player.hovered = hovered;
        ED_area_tag_redraw(player.area);
      }
      return OPERATOR_RUNNING_MODAL | OPERATOR_PASS_THROUGH;
    }
    case LEFTMOUSE:
      if (event->val == KM_PRESS) {
        return player_press(C, op, event);
      }
      if (event->val == KM_RELEASE && player.drag != PlayerDrag::None) {
        if (player.drag == PlayerDrag::Timeline && player.resume_after_scrub) {
          video_session_play(CTX_data_main(C), *session);
        }
        player.drag = PlayerDrag::None;
        player.resume_after_scrub = false;
      }
      return OPERATOR_RUNNING_MODAL;
    case EVT_SPACEKEY:
      if (event->val == KM_PRESS) {
        video_session_toggle(CTX_data_main(C), *session);
        player_sync_frame(CTX_data_scene(C), player, *session);
      }
      return OPERATOR_RUNNING_MODAL;
    case EVT_ESCKEY:
      if (event->val == KM_PRESS) {
        wmWindow *win = player.win;
        player_release(C, op);
        request_window_close(win);
        return OPERATOR_FINISHED;
      }
      return OPERATOR_RUNNING_MODAL;
    case WINDEACTIVATE:
    case EVT_DROP:
      return OPERATOR_PASS_THROUGH;
    default:
      break;
  }

  /* Keep window-level shortcuts (Ctrl/Cmd chords) working; swallow the rest so
   * the hidden Image Editor never samples, zooms or opens its panels. */
  if (ISKEYBOARD(event->type) && (event->modifier & (KM_CTRL | KM_OSKEY))) {
    return OPERATOR_PASS_THROUGH;
  }
  if (ISMOUSE_BUTTON(event->type) || ISMOUSE_WHEEL(event->type) || ISKEYBOARD(event->type) ||
      ISNDOF(event->type))
  {
    return OPERATOR_RUNNING_MODAL;
  }
  return OPERATOR_PASS_THROUGH;
}

static void video_player_cancel(bContext *C, wmOperator *op)
{
  /* The window is closing (OS close button, file load, quit). */
  player_release(C, op);
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name QA targets
 * \{ */

void video_player_qa_targets(const wmWindow * /*win*/,
                             const ScrArea *area,
                             const ARegion *region,
                             std::vector<MixarQATarget> &r_targets)
{
  if (region->regiontype != RGN_TYPE_WINDOW) {
    return;
  }
  const auto it = std::find_if(g_players.begin(), g_players.end(), [&](VideoPlayer *p) {
    return p->area == area;
  });
  if (it == g_players.end()) {
    return;
  }
  VideoPlayer &player = **it;
  MoodboardVideoSession *session = video_session_find(player.image, &player);
  if (!session) {
    return;
  }
  const std::string movie = player.image->id.name + 2;
  auto add = [&](const char *surface, const rctf &rect) -> MixarQATarget & {
    MixarQATarget t;
    t.surface = surface;
    t.text = movie;
    BLI_rcti_rctf_copy_round(&t.rect_win, &rect);
    r_targets.push_back(std::move(t));
    return r_targets.back();
  };
  const PlayerLayout l = video_player_layout(area);
  rctf whole;
  BLI_rctf_rcti_copy(&whole, &area->totrct);
  MixarQATarget &picture = add("video_player", whole);
  picture.value = std::to_string(video_session_frame(*session));
  picture.sel = session->playing;
  picture.detail = video_session_audio_state(*session);
  picture.index = session->frame_count;
  add("video_player_play", l.play).sel = session->playing;
  add("video_player_timeline", l.timeline);
  add("video_player_sound", l.sound).sel = session->muted;
  add("video_player_volume", l.volume).value = std::to_string(
      int(session->volume * 100.0f + 0.5f));
}

/** \} */

}  // namespace blender::ed::mixie

namespace blender {
void MIXIE_OT_moodboard_video_player(wmOperatorType *ot)
{
  ot->name = "Video Player";
  ot->idname = "MIXIE_OT_moodboard_video_player";
  ot->description = "Play a moodboard video in this preview window";

  ot->invoke = ed::mixie::video_player_invoke;
  ot->modal = ed::mixie::video_player_modal;
  ot->cancel = ed::mixie::video_player_cancel;

  ot->flag = OPTYPE_INTERNAL;

  PropertyRNA *prop = RNA_def_string(
      ot->srna, "image", nullptr, MAX_ID_NAME - 2, "Image", "Movie datablock to play");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE);
}
}  // namespace blender
