/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief Playback sessions: wall-clock movie position plus its audio track.
 *
 * A session is runtime-only state keyed on (owner, Image). The picture is
 * derived from the wall clock; the audio track (audaspace, on the device in
 * mixie_moodboard_video_audio_device.cc) is started at the same position on
 * play, stopped on pause and moved on seek. Audio is best-effort: no device,
 * no audio stream or a decode error leaves the movie playing silently, and
 * `has_audio` turns false so the UI can say so. Never touches the scene or its
 * sound.
 *
 * Keys are addresses, so every lookup and prune also compares the image's
 * `ID::session_uid`: a datablock allocated where a freed one lived (a file
 * load, a deleted node) never inherits its session.
 */

#include "mixie_moodboard_video_session.hh"

#include <algorithm>
#include <map>
#include <utility>

#include "BKE_image.hh"
#include "BKE_main.hh"

#include "BLI_listbase.h"
#include "BLI_path_utils.hh"
#include "BLI_string.h"
#include "BLI_time.h"
#include "BLI_utildefines.h"

#include "DNA_image_types.h"

#include "IMB_imbuf_types.hh"

#include "MOV_read.hh"

#ifdef WITH_AUDASPACE
#  include <Exception.h>
#  include <IReader.h>
#  include <devices/IDevice.h>
#  include <devices/IHandle.h>
#  include <file/File.h>
#endif

#include "mixie_moodboard_video_audio_device.hh"

namespace blender::ed::mixie {

static constexpr float VIDEO_FALLBACK_FPS = 24.0f;

using SessionKey = std::pair<const void *, const Image *>;
static std::map<SessionKey, MoodboardVideoSession> g_sessions;

#ifdef WITH_AUDASPACE
bool video_sessions_any_audio_handle()
{
  for (const auto &entry : g_sessions) {
    if (entry.second.audio_handle) {
      return true;
    }
  }
  return false;
}
#endif

/* -------------------------------------------------------------------- */
/** \name Audio track
 * \{ */

static void audio_stop(MoodboardVideoSession &session)
{
#ifdef WITH_AUDASPACE
  if (session.audio_handle) {
    try {
      session.audio_handle->stop();
    }
    catch (aud::Exception &) {
    }
    session.audio_handle.reset();
    audio_device_schedule_close();
  }
#endif
  session.audio_handle.reset();
}

static void audio_apply_volume(MoodboardVideoSession &session)
{
#ifdef WITH_AUDASPACE
  if (session.audio_handle) {
    try {
      session.audio_handle->setVolume(session.muted ? 0.0f : session.volume);
    }
    catch (aud::Exception &) {
    }
  }
#else
  UNUSED_VARS(session);
#endif
}

static void audio_start(Main *bmain, MoodboardVideoSession &session, const double seconds)
{
  audio_stop(session);
#ifdef WITH_AUDASPACE
  if (!session.has_audio || !session.image) {
    return;
  }
  /* Read the file BEFORE touching the device: a movie without an audio stream
   * throws here, and must never open a device it will not play on (an open
   * device keeps the machine from idle-sleeping). This is the reader the track
   * plays from, so the probe costs no extra file open. */
  std::shared_ptr<aud::IReader> reader;
  try {
    if (!session.audio_sound) {
      char path[FILE_MAX];
      STRNCPY(path, session.image->filepath);
      if (bmain) {
        BLI_path_abs(path, ID_BLEND_PATH(bmain, &session.image->id));
      }
      session.audio_sound = AUD_Sound(new aud::File(path));
    }
    reader = session.audio_sound->createReader();
  }
  catch (aud::Exception &) {
    session.audio_sound.reset();
    session.has_audio = false;
    return;
  }
  std::shared_ptr<aud::IDevice> device = audio_device_ensure();
  if (!device) {
    return;
  }
  bool locked = false;
  try {
    device->lock();
    locked = true;
    /* keep=true: the handle outlives the end of the track, so stop() above is
     * always the one place it is released. */
    session.audio_handle = device->play(reader, true);
    if (session.audio_handle) {
      session.audio_handle->seek(seconds);
      session.audio_handle->setVolume(session.muted ? 0.0f : session.volume);
    }
    device->unlock();
    locked = false;
  }
  catch (aud::Exception &) {
    /* The device refused the track: the movie plays on silently. */
    if (locked) {
      device->unlock();
    }
    session.audio_handle.reset();
    session.audio_sound.reset();
    session.has_audio = false;
  }
  if (!session.audio_handle) {
    /* The device is open but this track is not sounding: arm the idle close,
     * which audio_stop() would otherwise only arm for a handle. */
    audio_device_schedule_close();
  }
#else
  UNUSED_VARS(bmain, seconds);
  session.has_audio = false;
#endif
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Sessions
 * \{ */

double video_session_duration(const MoodboardVideoSession &session)
{
  return double(std::max(session.frame_count, 1)) / double(std::max(session.fps, 1.0f));
}

static void session_settle_end(MoodboardVideoSession &session)
{
  session.playing = false;
  audio_stop(session);
  session.anchor_seconds = session.end_rest == VideoEndRest::FirstFrame ?
                               0.0 :
                               video_session_duration(session);
}

double video_session_position(MoodboardVideoSession &session)
{
  if (!session.playing) {
    return session.anchor_seconds;
  }
  const double elapsed = std::max(BLI_time_now_seconds() - session.started_at, 0.0);
  const double position = session.anchor_seconds + elapsed;
  if (position >= video_session_duration(session)) {
    /* Played through: once, never looping. */
    session_settle_end(session);
    return session.anchor_seconds;
  }
  return position;
}

int video_session_frame(MoodboardVideoSession &session)
{
  const double position = video_session_position(session);
  const int frame = 1 + int(position * double(session.fps));
  return std::clamp(frame, 1, std::max(session.frame_count, 1));
}

void video_session_play(Main *bmain, MoodboardVideoSession &session)
{
  if (session.playing) {
    return;
  }
  /* Pressing play on a finished preview starts it again from the top. */
  if (session.anchor_seconds >= video_session_duration(session) - 1e-6) {
    session.anchor_seconds = 0.0;
  }
  session.started_at = BLI_time_now_seconds();
  session.playing = true;
  audio_start(bmain, session, session.anchor_seconds);
}

void video_session_pause(MoodboardVideoSession &session)
{
  if (!session.playing) {
    return;
  }
  session.anchor_seconds = video_session_position(session);
  session.playing = false;
  audio_stop(session);
}

void video_session_toggle(Main *bmain, MoodboardVideoSession &session)
{
  /* Settle first: a movie that played through since the last tick is
   * finished, and this press must start it again rather than "pause" it. */
  video_session_position(session);
  if (session.playing) {
    video_session_pause(session);
  }
  else {
    video_session_play(bmain, session);
  }
}

void video_session_seek(Main *bmain, MoodboardVideoSession &session, const double seconds)
{
  const double target = std::clamp(seconds, 0.0, video_session_duration(session));
  session.anchor_seconds = target;
  if (session.playing) {
    session.started_at = BLI_time_now_seconds();
    audio_start(bmain, session, target);
  }
}

void video_session_set_muted(MoodboardVideoSession &session, const bool muted)
{
  session.muted = muted;
  audio_apply_volume(session);
}

void video_session_set_volume(MoodboardVideoSession &session, const float volume)
{
  session.volume = std::clamp(volume, 0.0f, 1.0f);
  audio_apply_volume(session);
}

const char *video_session_audio_state(const MoodboardVideoSession &session)
{
  if (!session.has_audio) {
    return "none";
  }
#ifdef WITH_AUDASPACE
  if (session.audio_handle) {
    try {
      if (session.audio_handle->getStatus() == aud::STATUS_PLAYING) {
        return "playing";
      }
    }
    catch (aud::Exception &) {
    }
  }
#endif
  return "stopped";
}

MoodboardVideoSession *video_session_find(const Image *image, const void *owner)
{
  const auto it = g_sessions.find(SessionKey(owner, image));
  if (it == g_sessions.end()) {
    return nullptr;
  }
  if (it->second.image_session_uid != image->id.session_uid) {
    /* Another datablock now lives at the address this session was keyed on:
     * its frame, mute state and sound belong to a movie that is gone. */
    audio_stop(it->second);
    g_sessions.erase(it);
    return nullptr;
  }
  return &it->second;
}

MoodboardVideoSession *video_session_ensure(Main *bmain, Image *image, const void *owner)
{
  if (!image || image->source != IMA_SRC_MOVIE) {
    return nullptr;
  }
  if (MoodboardVideoSession *existing = video_session_find(image, owner)) {
    return existing;
  }

  /* Decoding the first frame validates the source and initializes
   * Image::anims, which exposes the movie's native duration and frame rate. */
  ImageUser image_user{};
  BKE_imageuser_default(&image_user);
  image_user.frames = 0;
  image_user.framenr = 1;
  void *lock = nullptr;
  ImBuf *ibuf = BKE_image_acquire_ibuf(image, &image_user, &lock);
  if (!ibuf || ibuf->x <= 0 || ibuf->y <= 0) {
    BKE_image_release_ibuf(image, ibuf, lock);
    return nullptr;
  }
  MoodboardVideoSession session;
  session.width = ibuf->x;
  session.height = ibuf->y;
  BKE_image_release_ibuf(image, ibuf, lock);

  session.image = image;
  session.image_session_uid = image->id.session_uid;
  session.owner = owner;
  session.end_rest = owner ? VideoEndRest::LastFrame : VideoEndRest::FirstFrame;
  session.fps = VIDEO_FALLBACK_FPS;
  session.frame_count = std::max(image_user.frames, 1);
  if (ImageAnim *image_anim = static_cast<ImageAnim *>(image->anims.first)) {
    if (image_anim->anim) {
      session.frame_count = std::max(MOV_get_duration_frames(image_anim->anim), 1);
      const float native_fps = MOV_get_fps(image_anim->anim);
      if (native_fps > 0.0f) {
        session.fps = native_fps;
      }
    }
  }
  UNUSED_VARS(bmain);
  return &g_sessions.emplace(SessionKey(owner, image), std::move(session)).first->second;
}

bool video_sessions_any_playing(const void *owner)
{
  for (const auto &entry : g_sessions) {
    if (entry.first.first == owner && entry.second.playing) {
      return true;
    }
  }
  return false;
}

void video_sessions_advance(const void *owner)
{
  for (auto &entry : g_sessions) {
    if (entry.first.first == owner) {
      video_session_position(entry.second);
    }
  }
}

void video_sessions_release_owner(const void *owner)
{
  for (auto it = g_sessions.begin(); it != g_sessions.end();) {
    if (it->first.first == owner) {
      audio_stop(it->second);
      it = g_sessions.erase(it);
    }
    else {
      ++it;
    }
  }
}

void video_sessions_prune(Main *bmain)
{
  /* Sessions are keyed on `Image *`. A generated movie is freed with its node,
   * and a file load frees them all, so a stale key would be inherited by a
   * later datablock allocated at the same address -- appearing to start
   * mid-playback, muted, with the old movie's sound. Validate against Main
   * first (only a live image may be read), then against its session uid. */
  for (auto it = g_sessions.begin(); it != g_sessions.end();) {
    const MoodboardVideoSession &session = it->second;
    const bool live = bmain && BLI_findindex(&bmain->images, session.image) != -1 &&
                      session.image->id.session_uid == session.image_session_uid;
    if (!live) {
      audio_stop(it->second);
      it = g_sessions.erase(it);
    }
    else {
      ++it;
    }
  }
}

void video_sessions_clear()
{
  for (auto &entry : g_sessions) {
    audio_stop(entry.second);
  }
  g_sessions.clear();
#ifdef WITH_AUDASPACE
  audio_device_close();
#endif
}

/** \} */

}  // namespace blender::ed::mixie
