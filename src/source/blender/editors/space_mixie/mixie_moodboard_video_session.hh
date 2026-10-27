/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spmixie
 * \brief One playback clock per (owner, movie): picture frame and audio track.
 *
 * Board cards (owner nullptr) and every preview player window (owner = the
 * player) each get their own session for the same movie, so a clip can play on
 * the board and in a preview independently. The wall clock is the master: the
 * picture frame is derived from it and the audio track is started, paused and
 * seeked alongside it, so a movie without sound (or a build without audio)
 * plays exactly as before.
 */

#pragma once

#include "BKE_sound_types.hh"

namespace blender {
struct Image;
struct Main;
}  // namespace blender

namespace blender::ed::mixie {

/** Where a movie rests once it has played through. */
enum class VideoEndRest {
  /** The board card: back to the poster frame, ready to play again. */
  FirstFrame,
  /** A preview player: on the last frame, with the timeline full. */
  LastFrame,
};

struct MoodboardVideoSession {
  Image *image = nullptr;
  /**
   * `ID::session_uid` of #image when the session began. Sessions are keyed on
   * the Image ADDRESS, and a later datablock can be allocated there (after a
   * file load, or once a node frees its movie): it has another uid, so a
   * mismatch marks the session stale.
   */
  unsigned int image_session_uid = 0;
  const void *owner = nullptr;
  VideoEndRest end_rest = VideoEndRest::FirstFrame;

  bool playing = false;
  /** Seconds into the movie at `started_at` (or now, while paused). */
  double anchor_seconds = 0.0;
  double started_at = 0.0;

  int frame_count = 1;
  float fps = 24.0f;
  int width = 0;
  int height = 0;

  /** Sound is on by default; mute and volume survive pause and replay. */
  bool muted = false;
  float volume = 1.0f;
  /** False once the file proved to have no audio stream (or none could play). */
  bool has_audio = true;

  AUD_Sound audio_sound;
  AUD_Handle audio_handle;
};

/**
 * The session for \a image owned by \a owner, created on first use by decoding
 * the first frame (which validates the file and exposes its length and rate).
 * Returns nullptr when the movie cannot be decoded.
 */
MoodboardVideoSession *video_session_ensure(Main *bmain, Image *image, const void *owner);
/**
 * The existing session, or nullptr. Never decodes. A session whose address now
 * holds another datablock (#MoodboardVideoSession::image_session_uid mismatch)
 * is stale: its sound stops and it is dropped. \a image must be live.
 */
MoodboardVideoSession *video_session_find(const Image *image, const void *owner);

/** Seconds in the movie now; settles a session that has played through. */
double video_session_position(MoodboardVideoSession &session);
/** The 1-based movie frame for the current position. */
int video_session_frame(MoodboardVideoSession &session);
double video_session_duration(const MoodboardVideoSession &session);

void video_session_play(Main *bmain, MoodboardVideoSession &session);
void video_session_pause(MoodboardVideoSession &session);
void video_session_toggle(Main *bmain, MoodboardVideoSession &session);
/** Jump to \a seconds (clamped); keeps playing if it was. */
void video_session_seek(Main *bmain, MoodboardVideoSession &session, double seconds);
void video_session_set_muted(MoodboardVideoSession &session, bool muted);
void video_session_set_volume(MoodboardVideoSession &session, float volume);
/**
 * The audio track for QA and diagnostics: "playing" while a device handle is
 * sounding, "none" once the file proved to have no playable audio, else
 * "stopped".
 */
const char *video_session_audio_state(const MoodboardVideoSession &session);

/** Whether any session of \a owner is playing (the board tick uses owner nullptr). */
bool video_sessions_any_playing(const void *owner);
/** Advance every session of \a owner (settles the ones that ended). */
void video_sessions_advance(const void *owner);
/** Stop audio and forget every session of \a owner. */
void video_sessions_release_owner(const void *owner);
/**
 * Forget sessions whose image is no longer in \a bmain, or whose address now
 * holds another datablock (all of them when \a bmain is null).
 */
void video_sessions_prune(Main *bmain);
void video_sessions_clear();

}  // namespace blender::ed::mixie
