/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Pure timing and shape math for the island's two live input cues: the ECG
 * trace drawn while Voice is capturing, and the blinking caret in the
 * minimised Sketch pill. No Blender headers, so
 * `tests/voice_motion_harness.cc` samples exactly the shipped functions.
 */

#pragma once

#include <algorithm>
#include <cmath>
#include <limits>

namespace blender {

/** Caret on/off half-period — the macOS text caret's 0.53 s. */
inline constexpr double AGENT_CARET_BLINK_SECONDS = 0.53;

/** One ECG frame while capturing. 30 Hz reads as smooth scrolling at chip size
 *  and costs half the mascot's working cadence. */
inline constexpr double AGENT_VOICE_WAVE_FRAME_SECONDS = 1.0 / 30.0;
/** Heartbeats visible across the trace, and how many scroll past per second. */
inline constexpr float AGENT_VOICE_WAVE_BEATS = 1.5f;
inline constexpr float AGENT_VOICE_WAVE_SPEED = 1.1f;
/** Silence still shows a heartbeat (Voice is live); speech lifts it to full height. */
inline constexpr float AGENT_VOICE_WAVE_QUIET = 0.35f;
/** Upper bound on #agent_voice_wave_points output for any time and level. */
inline constexpr int AGENT_VOICE_WAVE_MAX_POINTS = 48;

/** True while the caret is drawn. It stays solid for the first half-period
 *  after the draft changes (\a epoch), like a native text field, and never
 *  blinks under Reduce Motion. */
inline bool agent_caret_visible(const double now, const double epoch, const bool reduced)
{
  if (reduced || now <= epoch) {
    return true;
  }
  return std::fmod(now - epoch, 2.0 * AGENT_CARET_BLINK_SECONDS) < AGENT_CARET_BLINK_SECONDS;
}

/** Seconds until #agent_caret_visible next changes. A steady caret (Reduce
 *  Motion) never needs a frame, so it reports infinity for the caller's min. */
inline double agent_caret_next_change(const double now, const double epoch, const bool reduced)
{
  if (reduced) {
    return std::numeric_limits<double>::infinity();
  }
  if (now <= epoch) {
    return (epoch - now) + AGENT_CARET_BLINK_SECONDS;
  }
  const double into = std::fmod(now - epoch, AGENT_CARET_BLINK_SECONDS);
  return std::max(1e-3, AGENT_CARET_BLINK_SECONDS - into);
}

/** One heartbeat as a polyline over phase [0, 1): baseline, P bump, the sharp
 *  Q-R-S complex and the T bump. Piecewise linear so the R peak is always a
 *  vertex — a sampled curve lost its tip between samples and shimmered as it
 *  scrolled. Values are in [-1, 1] before amplitude. */
inline constexpr int AGENT_ECG_KEYS = 12;
inline constexpr float AGENT_ECG_PHASE[AGENT_ECG_KEYS] = {
    0.00f, 0.10f, 0.16f, 0.22f, 0.30f, 0.33f, 0.37f, 0.41f, 0.45f, 0.56f, 0.64f, 0.72f};
inline constexpr float AGENT_ECG_VALUE[AGENT_ECG_KEYS] = {
    0.00f, 0.00f, 0.16f, 0.00f, 0.00f, -0.22f, 1.00f, -0.42f, 0.00f, 0.00f, 0.26f, 0.00f};

/** The beat's value at \a phase in [0, 1). */
inline float agent_ecg_value(float phase)
{
  phase -= std::floor(phase);
  for (int i = AGENT_ECG_KEYS - 1; i >= 0; i--) {
    if (phase >= AGENT_ECG_PHASE[i]) {
      if (i == AGENT_ECG_KEYS - 1) {
        return AGENT_ECG_VALUE[i]; /* Flat baseline to the next beat. */
      }
      const float t = (phase - AGENT_ECG_PHASE[i]) / (AGENT_ECG_PHASE[i + 1] - AGENT_ECG_PHASE[i]);
      return AGENT_ECG_VALUE[i] + (AGENT_ECG_VALUE[i + 1] - AGENT_ECG_VALUE[i]) * t;
    }
  }
  return 0.0f;
}

/** Trace height for a microphone \a level in [0, 1]. */
inline float agent_voice_wave_amplitude(const float level)
{
  return AGENT_VOICE_WAVE_QUIET + (1.0f - AGENT_VOICE_WAVE_QUIET) * std::clamp(level, 0.0f, 1.0f);
}

/**
 * The visible ECG trace at \a now as points in a unit box: x runs 0 → 1 left
 * to right, y is in [-1, 1] (already scaled by #agent_voice_wave_amplitude).
 * The trace scrolls left, new beats entering on the right; Reduce Motion
 * freezes it. Returns the point count (≤ #AGENT_VOICE_WAVE_MAX_POINTS).
 */
inline int agent_voice_wave_points(const double now,
                                   const float level,
                                   const bool reduced,
                                   float (*r_points)[2])
{
  const float amp = agent_voice_wave_amplitude(level);
  /* Scroll in beats, wrapped so float precision holds over a long session. */
  const double scroll_beats = reduced ? 0.0 : now * double(AGENT_VOICE_WAVE_SPEED);
  const float scroll = float(scroll_beats - std::floor(scroll_beats));
  const float end = scroll + AGENT_VOICE_WAVE_BEATS;
  int count = 0;
  auto emit = [&](const float beat_u, const float value) {
    if (count < AGENT_VOICE_WAVE_MAX_POINTS) {
      r_points[count][0] = (beat_u - scroll) / AGENT_VOICE_WAVE_BEATS;
      r_points[count][1] = value * amp;
      count++;
    }
  };
  emit(scroll, agent_ecg_value(scroll));
  for (int beat = 0; float(beat) < end; beat++) {
    for (int k = 0; k < AGENT_ECG_KEYS; k++) {
      const float u = float(beat) + AGENT_ECG_PHASE[k];
      if (u > scroll && u < end) {
        emit(u, AGENT_ECG_VALUE[k]);
      }
    }
  }
  emit(end, agent_ecg_value(end));
  return count;
}

}  // namespace blender
