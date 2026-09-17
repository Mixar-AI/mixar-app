/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup editors
 *
 * Microphone capture for Mixar voice dictation.
 *
 * Blender's bundled `aud` (audaspace) is playback-only and the app ships no
 * ffmpeg binary, so capture has no existing home — this is it. One process-wide
 * recorder: there is one microphone and one place the transcript is going, so a
 * second concurrent recording would only ever be a bug.
 *
 * THREADING. `ED_mixar_audio_record_start` / `_stop` / `_cancel` are
 * MAIN-THREAD ONLY (they start and tear down the device). The three readers
 * below — `_is_recording`, `_level`, `_duration`, `_levels` — are safe from a
 * draw callback: they read atomics and a fixed ring, never allocate, and never
 * block on the audio thread. The audio callback itself touches nothing outside
 * this module — no `bpy`, no Blender data, no allocation.
 *
 * FORMAT. 16 kHz mono 16-bit PCM, which is exactly what Whisper resamples to
 * anyway; capturing at 48 kHz stereo would be six times the bytes for
 * identical transcription. `_stop` writes a plain WAV (the backend's audio
 * probe reads its duration to the sample) and hands back the path.
 */

#pragma once

/** Capture format. The backend bills on measured duration, so these are the
 * numbers the WAV header must describe — see `mixar_audio_wav.cc`. */
#define MIXAR_AUDIO_SAMPLE_RATE 16000
#define MIXAR_AUDIO_CHANNELS 1

/** Hard ceiling on one recording, in seconds.
 *
 * The whole buffer is allocated up front at start (about 9.6 MB here) so the
 * audio callback never allocates and can never outgrow its bounds; a longer
 * cap costs that memory for every two-second voice note. The backend accepts
 * up to 600 s — being stricter here is deliberate, and the client auto-stops
 * at this mark rather than silently dropping the tail. */
#define MIXAR_AUDIO_MAX_SECONDS 300

/** Peak-level samples kept for the UI's waveform. Written by the audio thread
 * into a fixed ring, read by draw passes; never resized. */
#define MIXAR_AUDIO_LEVEL_HISTORY 64

/** Whether this build has a capture backend at all.
 *
 * False on a platform we did not compile miniaudio for. The mic button hides
 * itself on that build rather than offering an action that can only fail —
 * the same allowlist discipline the Agent Bubble's window controls use. */
bool ED_mixar_audio_is_available();

/** Open the default input device and start recording.
 *
 * Returns false and fills `r_error` (user-facing: "No microphone was found",
 * "Microphone access was denied") when the device cannot be opened. A start
 * while already recording is a no-op that returns true. MAIN THREAD ONLY. */
bool ED_mixar_audio_record_start(char *r_error, int error_maxlen);

/** Stop, write the captured audio to a temp WAV, and return its path.
 *
 * `r_filepath` receives a path under the session temp dir on success. Returns
 * false with `r_error` filled when nothing was captured or the file could not
 * be written; either way the recorder ends up idle and its buffer freed.
 * MAIN THREAD ONLY. */
bool ED_mixar_audio_record_stop(char *r_filepath,
                                int filepath_maxlen,
                                char *r_error,
                                int error_maxlen);

/** Stop and discard. Writes no file. Safe to call when idle. MAIN THREAD ONLY. */
void ED_mixar_audio_record_cancel();

bool ED_mixar_audio_is_recording();

/** Smoothed peak level of the last block, 0..1. Zero when idle. */
float ED_mixar_audio_level();

/** Seconds captured so far. Zero when idle. */
float ED_mixar_audio_duration();

/** Copy up to `count` recent peak levels into `r_levels`, oldest first.
 *
 * Returns how many were written. This is what a waveform draws; it is a
 * snapshot of a ring the audio thread keeps writing, so a torn read costs one
 * slightly stale bar and nothing else. */
int ED_mixar_audio_levels(float *r_levels, int count);

/** Release the device on app shutdown. Safe when idle; never blocks. */
void ED_mixar_audio_shutdown();
