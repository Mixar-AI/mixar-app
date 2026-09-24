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
 * drifts then returns to centre, a slow breath. Working keeps the eyes
 * open and rolls the pupils in a paused circular phrase — not a squint.
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

constexpr double MIXIE_ROLL_PERIOD = 2.6;
constexpr float MIXIE_ROLL_START = 0.12f;
constexpr float MIXIE_ROLL_SPAN = 0.50f;
constexpr float MIXIE_ROLL_RX = 0.80f;
constexpr float MIXIE_ROLL_RY = 0.58f;

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

/** One counterclockwise pupil orbit with eased fade in/out, then a rest.
 * Distinct from Generating's continuous slit-pupil orbit. */
struct MixieCatRoll {
  float look_x;
  float look_y;
  float amount;
};

inline MixieCatRoll mixie_cat_eye_roll(const double now)
{
  const double wrapped = std::fmod(now / MIXIE_ROLL_PERIOD, 1.0);
  const double phase = wrapped < 0.0 ? wrapped + 1.0 : wrapped;
  const float u = float((phase - MIXIE_ROLL_START) / MIXIE_ROLL_SPAN);
  MixieCatRoll roll{0.0f, 0.08f, 0.0f};
  if (u <= 0.0f || u >= 1.0f) {
    return roll;
  }
  const float fade = (u < 0.16f) ? mixie_cat_smooth01(u / 0.16f) :
                     (u > 0.84f) ? 1.0f - mixie_cat_smooth01((u - 0.84f) / 0.16f) :
                     1.0f;
  constexpr float k_tau = 6.283185307f;
  const float angle = u * k_tau;
  roll.amount = fade;
  roll.look_x = fade * MIXIE_ROLL_RX * std::cos(angle);
  /* Blend back to the resting gaze as well as the orbit, so neither end of
   * the phrase jumps vertically when the eyes settle. */
  roll.look_y += fade * (MIXIE_ROLL_RY * std::sin(angle) - roll.look_y);
  return roll;
}

inline MixieCatPose mixie_cat_eval_pose(const double now, const bool working)
{
  MixieCatPose p;
  p.openness = mixie_cat_blink_openness(now, MIXIE_IDLE_OPEN);
  p.breathe = working ? (1.0f + 0.012f * float(std::sin(now * 1.55))) :
                        (1.0f + 0.009f * float(std::sin(now * 1.25)));
  /* Working energy is the eye roll + a slightly livelier breath — not a
   * bounce or a squint. Idle has none. */
  p.bounce = 0.0f;
  if (working) {
    const MixieCatRoll roll = mixie_cat_eye_roll(now);
    p.look_x = roll.look_x;
    p.look_y = roll.look_y;
    p.tilt = 5.0f * roll.look_x;
    p.eye_scale = 1.0f + 0.08f * roll.amount;
    p.pupil_scale = 1.0f + 0.07f * float(std::sin(now * 1.7)) - 0.04f * roll.amount;
  }
  else {
    /* Look, hold, return. Different vertical targets avoid a pendulum loop. */
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
  }
  p.ear_l = mixie_cat_ear_twitch(now, -1.0f);
  p.ear_r = mixie_cat_ear_twitch(now, 1.0f);
  return p;
}

}  // namespace blender
