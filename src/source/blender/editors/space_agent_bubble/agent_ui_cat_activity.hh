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
  bool finishing = false;
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
  if (s.finishing)
    return MixieCatActivity::Responding;
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

/** A gesture has anticipation, a readable hold and an eased return. */
inline float mixie_cat_gesture(double now, double period, float start, float span)
{
  const float phase = float(now / period - std::floor(now / period));
  const float t = (phase - start) / span;
  if (t < 0.0f || t > 1.0f) {
    return 0.0f;
  }
  return t < 0.4f ? mixie_cat_smooth01(t / 0.4f) : 1.0f - mixie_cat_smooth01((t - 0.4f) / 0.6f);
}

/** Distinct eye silhouettes stay legible at the actual 44px pill height.
 * Motion phrases have pauses; parallel avatars keep their quieter sampler. */
inline MixieCatPose mixie_cat_activity_pose(const double now, const MixieCatActivity activity)
{
  MixieCatPose p = mixie_cat_eval_pose(now, false);
  const auto wave = [now](double speed) { return float(std::sin(now * speed)); };
  float open = 1.0f;
  double blink_time = now;
  switch (activity) {
    case MixieCatActivity::Thinking: {
      const float glance = mixie_cat_gesture(now, 3.6, 0.35f, 0.50f);
      p.look_x = -0.65f + 1.3f * glance;
      p.look_y = 0.65f;
      p.tilt = -27.0f + 9.0f * glance;
      p.lid_l = 0.48f;
      p.lid_r = 1.08f;
      p.ear_height_l = 0.82f;
      p.ear_height_r = 1.10f;
      p.pupil_scale = 0.78f;
      break;
    }
    case MixieCatActivity::Reading: {
      const float phase = float(now / 1.9 - std::floor(now / 1.9));
      const float scan = mixie_cat_smooth01((phase - 0.12f) / 0.16f) +
                         mixie_cat_smooth01((phase - 0.44f) / 0.16f) -
                         2.0f * mixie_cat_smooth01((phase - 0.82f) / 0.16f);
      p.look_x = -0.85f + 0.85f * scan;
      p.look_y = -0.45f;
      p.tilt = -12.0f;
      p.bounce = -0.018f * mixie_cat_gesture(now, 1.9, 0.78f, 0.20f);
      p.eye_width = 1.20f;
      p.pupil_scale = 0.80f;
      p.pupil_width = 0.65f;
      open = 0.60f;
      break;
    }
    case MixieCatActivity::Working: {
      const float nod = mixie_cat_gesture(now, 1.6, 0.08f, 0.24f) +
                        mixie_cat_gesture(now, 1.6, 0.40f, 0.24f);
      p.look_x = 0.0f;
      p.look_y = -0.55f;
      p.tilt = -12.0f + 5.0f * nod;
      p.bounce = -0.040f * nod;
      p.eye_width = 1.10f;
      p.ear_height_l = p.ear_height_r = 0.86f;
      p.pupil_scale = 0.72f;
      open = 0.36f;
      break;
    }
    case MixieCatActivity::Generating:
      p.look_x = 0.85f * wave(2.3);
      p.look_y = 0.65f * float(std::cos(now * 2.3));
      p.tilt = -12.0f + 12.0f * wave(2.3);
      p.bounce = 0.025f * wave(2.3);
      p.breathe = 1.0f + 0.025f * wave(2.3);
      p.eye_scale = 1.20f;
      p.pupil_scale = 0.85f;
      p.pupil_width = 0.55f;
      break;
    case MixieCatActivity::Responding: {
      const float nod = mixie_cat_gesture(now, 2.1, 0.06f, 0.22f) +
                        mixie_cat_gesture(now, 2.1, 0.35f, 0.22f);
      p.look_x = 0.0f;
      p.look_y = 0.0f;
      p.bounce = 0.030f * nod;
      p.tilt = -8.0f + 8.0f * nod;
      p.eye_width = 1.12f;
      p.smile = 0.85f + 0.15f * nod;
      break;
    }
    case MixieCatActivity::Listening:
      p.look_x = 0.0f;
      p.look_y = 0.05f;
      p.tilt = -12.0f;
      p.eye_scale = 1.22f;
      p.pupil_scale = 1.35f;
      p.ear_height_l = p.ear_height_r = 1.15f;
      p.bounce = -0.012f * mixie_cat_gesture(now, 3.8, 0.5f, 0.18f);
      blink_time *= 0.7;
      break;
    case MixieCatActivity::Waiting:
      p.look_x = 0.0f;
      p.look_y = 0.10f;
      p.tilt = 14.0f;
      p.eye_scale = 1.10f;
      p.lid_l = 1.05f;
      p.lid_r = 0.70f;
      p.pupil_scale = 1.22f;
      p.ear_height_r = 0.80f;
      blink_time *= 0.7;
      break;
    case MixieCatActivity::Offline:
      p.look_x = 0.0f;
      p.look_y = -0.28f;
      p.tilt = -12.0f;
      p.ear_height_l = p.ear_height_r = 0.65f;
      p.eye_width = 1.05f;
      open = 0.22f;
      blink_time *= 0.6;
      break;
    case MixieCatActivity::Connecting: {
      const float glance = mixie_cat_gesture(now, 2.4, 0.15f, 0.70f);
      p.look_x = -0.85f + 1.70f * glance;
      p.look_y = 0.0f;
      p.tilt = -12.0f + p.look_x * 14.0f;
      p.eye_scale = 1.05f;
      p.lid_l = 0.80f;
      p.lid_r = 0.80f;
      break;
    }
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
          lerp(a.pupil_scale, b.pupil_scale),
          lerp(a.eye_width, b.eye_width),
          lerp(a.lid_l, b.lid_l),
          lerp(a.lid_r, b.lid_r),
          lerp(a.pupil_width, b.pupil_width),
          lerp(a.smile, b.smile),
          lerp(a.ear_height_l, b.ear_height_l),
          lerp(a.ear_height_r, b.ear_height_r)};
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
