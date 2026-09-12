/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include "agent_ui_pill_cat_pose.hh"

namespace blender {

enum class MixieCatActivity {
  Idle,
  Thinking,
  Reading,
  Working,
  Generating,
  Responding,
  Listening,
  Waiting,
  Offline,
  Connecting,
};

struct MixieCatSignals {
  bool busy = false, waiting = false, listening = false;
  bool offline = false, connecting = false;
  bool thinking = false, reading = false, working = false, responding = false;
  bool generating = false;
};

inline bool mixie_cat_is_working(const MixieCatActivity activity)
{
  return activity == MixieCatActivity::Thinking || activity == MixieCatActivity::Reading ||
         activity == MixieCatActivity::Working || activity == MixieCatActivity::Generating ||
         activity == MixieCatActivity::Responding;
}

/** Live semantic state wins over historical message/queue decoration. */
inline MixieCatActivity mixie_cat_activity(const MixieCatSignals &s)
{
  if (s.listening)
    return MixieCatActivity::Listening;
  if (s.waiting)
    return MixieCatActivity::Waiting;
  if (s.offline)
    return MixieCatActivity::Offline;
  if (s.connecting)
    return MixieCatActivity::Connecting;
  if (s.busy) {
    if (s.working)
      return MixieCatActivity::Working;
    if (s.reading)
      return MixieCatActivity::Reading;
    if (s.thinking)
      return MixieCatActivity::Thinking;
    if (s.responding)
      return MixieCatActivity::Responding;
    return s.generating ? MixieCatActivity::Generating : MixieCatActivity::Thinking;
  }
  return s.generating ? MixieCatActivity::Generating : MixieCatActivity::Idle;
}

inline const char *mixie_cat_activity_name(const MixieCatActivity activity)
{
  switch (activity) {
    case MixieCatActivity::Thinking:
      return "Thinking";
    case MixieCatActivity::Reading:
      return "Reading";
    case MixieCatActivity::Working:
      return "Working";
    case MixieCatActivity::Generating:
      return "Generating";
    case MixieCatActivity::Responding:
      return "Responding";
    case MixieCatActivity::Listening:
      return "Listening";
    case MixieCatActivity::Waiting:
      return "Waiting for you";
    case MixieCatActivity::Offline:
      return "Offline";
    case MixieCatActivity::Connecting:
      return "Connecting";
    default:
      return "Idle";
  }
}

/** All motion stays inside the chip. The main cat has stronger gestures than
 * small parallel avatars, whose existing idle/working sampler stays intact. */
inline MixieCatPose mixie_cat_activity_pose(const double now, const MixieCatActivity activity)
{
  MixieCatPose p = mixie_cat_eval_pose(now, false);
  const auto wave = [now](double speed) { return float(std::sin(now * speed)); };
  float open = 1.0f;
  double blink_time = now;
  switch (activity) {
    case MixieCatActivity::Thinking:
      p.look_x = 0.78f * wave(1.8);
      p.look_y = 0.48f + 0.12f * wave(2.5);
      p.tilt = 8.0f * wave(1.8);
      p.ear_l = -8.0f;
      p.ear_r = 5.0f + 3.0f * wave(2.5);
      p.pupil_scale = 0.88f;
      open = 0.86f;
      break;
    case MixieCatActivity::Reading: {
      const float phase = float(now / 1.65 - std::floor(now / 1.65));
      const float scan = phase < 0.8f ? mixie_cat_smooth01(phase / 0.8f) :
                                        1.0f - mixie_cat_smooth01((phase - 0.8f) / 0.2f);
      p.look_x = -0.82f + 1.64f * scan;
      p.look_y = -0.30f;
      p.tilt = p.look_x * 3.5f;
      p.pupil_scale = 0.82f;
      open = 0.82f;
      break;
    }
    case MixieCatActivity::Working:
      p.look_x = 0.68f * wave(3.8);
      p.look_y = -0.36f + 0.12f * wave(5.0);
      p.tilt = 5.0f * wave(3.8);
      p.bounce = 0.013f * wave(5.0);
      p.ear_l = -6.0f + 4.0f * wave(3.8);
      p.ear_r = 6.0f + 4.0f * wave(3.8);
      p.pupil_scale = 0.80f;
      open = 0.72f;
      break;
    case MixieCatActivity::Generating:
      p.look_x = 0.68f * wave(2.3);
      p.look_y = 0.48f * float(std::cos(now * 2.3));
      p.tilt = 6.5f * wave(2.3);
      p.bounce = 0.018f * wave(3.3);
      p.eye_scale = 1.08f;
      p.pupil_scale = 1.02f + 0.12f * wave(2.3);
      break;
    case MixieCatActivity::Responding:
      p.look_x = 0.18f * wave(1.9);
      p.look_y = 0.18f + 0.16f * wave(4.2);
      p.bounce = 0.010f * wave(4.2);
      p.tilt = 3.0f * wave(1.9);
      p.eye_scale = 1.08f;
      break;
    case MixieCatActivity::Listening:
      p.look_x = 0.22f * wave(1.5);
      p.look_y = 0.22f;
      p.tilt = 4.0f + 3.0f * wave(1.5);
      p.eye_scale = 1.14f;
      p.pupil_scale = 1.16f;
      p.ear_l = -14.0f;
      p.ear_r = -14.0f;
      blink_time *= 0.7;
      break;
    case MixieCatActivity::Waiting:
      p.look_x = 0.08f * wave(1.0);
      p.look_y = 0.14f;
      p.tilt = 10.0f + 2.0f * wave(1.2);
      p.eye_scale = 1.10f;
      p.pupil_scale = 1.13f;
      p.ear_l = -9.0f;
      p.ear_r = 10.0f;
      blink_time *= 0.7;
      break;
    case MixieCatActivity::Offline:
      p.look_x = 0.10f * wave(0.7);
      p.look_y = -0.28f;
      p.tilt = -4.0f;
      p.ear_l = 16.0f;
      p.ear_r = 16.0f;
      open = 0.58f;
      blink_time *= 0.6;
      break;
    case MixieCatActivity::Connecting:
      p.look_x = 0.85f * wave(1.7);
      p.look_y = 0.30f;
      p.tilt = 7.0f * wave(1.7);
      p.eye_scale = 1.06f;
      break;
    case MixieCatActivity::Idle:
      return p;
  }
  p.openness = mixie_cat_blink_openness(blink_time, open);
  return p;
}

inline MixieCatPose mixie_cat_blend(const MixieCatPose &a, const MixieCatPose &b, float t)
{
  const auto lerp = [t](float x, float y) { return x + (y - x) * t; };
  return {lerp(a.breathe, b.breathe),
          lerp(a.bounce, b.bounce),
          lerp(a.tilt, b.tilt),
          lerp(a.openness, b.openness),
          lerp(a.look_x, b.look_x),
          lerp(a.look_y, b.look_y),
          lerp(a.ear_l, b.ear_l),
          lerp(a.ear_r, b.ear_r),
          lerp(a.eye_scale, b.eye_scale),
          lerp(a.pupil_scale, b.pupil_scale)};
}

/** Region-owned, frame-independent expression changes. Reversing a transition
 * starts at its exact sampled pose; hidden windows resume without stale jumps. */
struct MixieCatMotion {
  MixieCatActivity activity = MixieCatActivity::Idle;
  MixieCatPose from{};
  double started = 0.0;
  bool initialized = false;

  MixieCatPose at(double now) const
  {
    const float t = mixie_cat_smooth01(float((now - started) / 0.26));
    return mixie_cat_blend(from, mixie_cat_activity_pose(now, activity), t);
  }

  MixieCatPose sample(double now, MixieCatActivity next)
  {
    if (!initialized) {
      initialized = true;
      activity = next;
      started = now - 0.26;
      from = mixie_cat_activity_pose(now, next);
    }
    else if (next != activity) {
      from = at(now);
      activity = next;
      started = now;
    }
    return at(now);
  }
};
}  // namespace blender
