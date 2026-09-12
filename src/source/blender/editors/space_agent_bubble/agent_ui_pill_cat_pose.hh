/* SPDX-FileCopyrightText: 2026 Mixar Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spagentbubble
 *
 * Mixie's face pose — a pure function of (time, working). The GPU painter
 * only consumes this; tests compile the same header. No GPU, no bpy.
 *
 * Idle motion uses close–hold–open blink, gaze that
 * drifts then returns to centre, a slow breath. Working reuses that
 * envelope with a lower rest openness (a squint), not a second clip.
 */

#pragma once

#include <algorithm>
#include <cmath>

namespace blender {

struct MixieCatPose {
  float breathe;
  float bounce;
  float tilt;
  float openness;
  float look_x;
  float look_y;
  float ear_l;
  float ear_r;
  float eye_scale;
  float pupil_scale;
  /* Neutral defaults preserve the six parallel-card faces. The main cat can
   * change its silhouette of the eyes, not just move small pupils around. */
  float eye_width = 1.0f;
  float lid_l = 1.0f, lid_r = 1.0f;
  float pupil_width = 1.0f;
  float smile = 0.0f;
  float ear_height_l = 1.0f, ear_height_r = 1.0f;
};

constexpr double MIXIE_BLINK_PERIOD = 3.55;
constexpr double MIXIE_BLINK_CLOSE = 0.058;
constexpr double MIXIE_BLINK_HOLD = 0.048;
constexpr double MIXIE_BLINK_OPEN = 0.092;
constexpr double MIXIE_BLINK_SPAN = MIXIE_BLINK_CLOSE + MIXIE_BLINK_HOLD + MIXIE_BLINK_OPEN;
constexpr float MIXIE_BLINK_CLOSED = 0.08f;
constexpr float MIXIE_IDLE_OPEN = 1.0f;
constexpr float MIXIE_WORK_OPEN = 0.78f;

constexpr double MIXIE_GAZE_PERIOD = 4.6;
constexpr double MIXIE_GAZE_REST_END = 0.30;
constexpr double MIXIE_GAZE_OUT_END = 0.48;
constexpr double MIXIE_GAZE_HOLD_END = 0.70;
constexpr double MIXIE_GAZE_BACK_END = 0.94;

inline float mixie_cat_smooth01(const float t)
{
  const float x = std::clamp(t, 0.0f, 1.0f);
  return x * x * x * (x * (x * 6.0f - 15.0f) + 10.0f);
}

inline float mixie_cat_blink_openness(const double now, const float rest_open)
{
  const double wrapped = std::fmod(now, MIXIE_BLINK_PERIOD);
  const double t = wrapped < 0.0 ? wrapped + MIXIE_BLINK_PERIOD : wrapped;
  auto envelope = [&](const double local) -> float {
    if (local < 0.0 || local >= MIXIE_BLINK_SPAN) {
      return rest_open;
    }
    if (local < MIXIE_BLINK_CLOSE) {
      const float u = mixie_cat_smooth01(float(local / MIXIE_BLINK_CLOSE));
      return rest_open + (MIXIE_BLINK_CLOSED - rest_open) * u;
    }
    if (local < MIXIE_BLINK_CLOSE + MIXIE_BLINK_HOLD) {
      return MIXIE_BLINK_CLOSED;
    }
    const float u = mixie_cat_smooth01(
        float((local - MIXIE_BLINK_CLOSE - MIXIE_BLINK_HOLD) / MIXIE_BLINK_OPEN));
    return MIXIE_BLINK_CLOSED + (rest_open - MIXIE_BLINK_CLOSED) * u;
  };
  float open = envelope(t);
  const int cycle = int(std::floor(now / MIXIE_BLINK_PERIOD));
  if (cycle % 6 == 5) {
    open = std::min(open, envelope(t - (MIXIE_BLINK_SPAN + 0.14)));
  }
  return open;
}

inline float mixie_cat_gaze_amount(const double now)
{
  const double wrapped = std::fmod(now / MIXIE_GAZE_PERIOD, 1.0);
  const double g = wrapped < 0.0 ? wrapped + 1.0 : wrapped;
  if (g < MIXIE_GAZE_REST_END) {
    return 0.0f;
  }
  if (g < MIXIE_GAZE_OUT_END) {
    return mixie_cat_smooth01(
        float((g - MIXIE_GAZE_REST_END) / (MIXIE_GAZE_OUT_END - MIXIE_GAZE_REST_END)));
  }
  if (g < MIXIE_GAZE_HOLD_END) {
    return 1.0f;
  }
  if (g < MIXIE_GAZE_BACK_END) {
    return 1.0f - mixie_cat_smooth01(float((g - MIXIE_GAZE_HOLD_END) /
                                           (MIXIE_GAZE_BACK_END - MIXIE_GAZE_HOLD_END)));
  }
  return 0.0f;
}

inline float mixie_cat_ear_twitch(const double now, const float side)
{
  const double t = std::fmod(now + double(side) * 1.9, 6.2);
  const double local = t < 0.0 ? t + 6.2 : t;
  if (local >= 0.48) {
    return 0.0f;
  }
  constexpr float k_pi = 3.14159265f;
  const float wave = std::sin(float(local / 0.48) * k_pi);
  return 4.0f * side * wave * wave;
}

inline MixieCatPose mixie_cat_eval_pose(const double now, const bool working)
{
  MixieCatPose p;
  const float rest_open = working ? MIXIE_WORK_OPEN : MIXIE_IDLE_OPEN;
  p.openness = mixie_cat_blink_openness(now, rest_open);
  p.breathe = working ? (1.0f + 0.012f * float(std::sin(now * 1.55))) :
                        (1.0f + 0.009f * float(std::sin(now * 1.25)));
  /* Working energy is the squint + a slightly livelier breath — not a
   * bounce. Idle has none. */
  p.bounce = 0.0f;
  /* Look, hold, return. Different vertical targets avoid a pendulum loop;
   * working cats stay curious instead of locking their pupils in place. */
  const float gaze = mixie_cat_gaze_amount(now);
  constexpr float targets[8][2] = {
      {-0.85f, 0.30f},
      {0.75f, 0.55f},
      {-0.45f, -0.55f},
      {0.85f, 0.05f},
      {0.15f, 0.65f},
      {-0.80f, -0.20f},
      {0.65f, -0.45f},
      {-0.55f, 0.50f},
  };
  const int cycle = int(std::floor(now / MIXIE_GAZE_PERIOD));
  const int target = (cycle % 8 + 8) % 8;
  p.look_x = targets[target][0] * gaze;
  p.look_y = targets[target][1] * gaze;
  p.tilt = 5.0f * p.look_x;
  p.eye_scale = 1.0f + 0.10f * gaze;
  p.pupil_scale = 1.0f + 0.07f * float(std::sin(now * 1.7)) - 0.08f * gaze;
  p.ear_l = mixie_cat_ear_twitch(now, -1.0f);
  p.ear_r = mixie_cat_ear_twitch(now, 1.0f);
  return p;
}

}  // namespace blender
