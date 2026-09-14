/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include "agent_ui_cat_activity.hh"

namespace blender {

constexpr double MIXIE_CAT_FRAME_SECONDS = 1.0 / 60.0;
constexpr double MIXIE_CAT_MAX_SLEEP_SECONDS = 0.5;

/** Conservative displacement estimate in normalized chip coordinates. Includes
 * silhouette, eye shape and pupil movement; ignoring only subpixel changes
 * preserves the existing poses instead of freezing the idle cat. */
inline float mixie_cat_pose_displacement(const MixieCatPose &a, const MixieCatPose &b)
{
  const auto delta = [](float x, float y) { return std::abs(x - y); };
  return delta(a.bounce, b.bounce) + 0.5f * delta(a.breathe, b.breathe) +
         0.009f * delta(a.tilt, b.tilt) + 0.09f * delta(a.look_x, b.look_x) +
         0.08f * delta(a.look_y, b.look_y) + 0.20f * delta(a.openness, b.openness) +
         0.20f * delta(a.eye_scale, b.eye_scale) + 0.14f * delta(a.eye_width, b.eye_width) +
         0.08f * delta(a.pupil_scale, b.pupil_scale) +
         0.06f * delta(a.pupil_width, b.pupil_width) + 0.20f * delta(a.smile, b.smile) +
         0.18f * std::max(delta(a.lid_l, b.lid_l), delta(a.lid_r, b.lid_r)) +
         0.4f * std::max(delta(a.ear_height_l, b.ear_height_l),
                         delta(a.ear_height_r, b.ear_height_r)) +
         0.002f * std::max(delta(a.ear_l, b.ear_l), delta(a.ear_r, b.ear_r));
}

/** Predict the next useful frame from the same time-based pose as the painter.
 * Fast activity/glow and expression changes get display cadence. Quiet faces
 * sleep until their accumulated displacement approaches a quarter pixel;
 * lookahead includes the blink so a short close/open cannot be skipped. */
inline double mixie_cat_next_frame(const MixieCatMotion &motion,
                                   const double now,
                                   const float chip_pixels)
{
  if (now < motion.started + 0.26 || mixie_cat_is_working(motion.activity) ||
      motion.activity == MixieCatActivity::Connecting)
  {
    return MIXIE_CAT_FRAME_SECONDS;
  }
  const MixieCatPose present = motion.at(now);
  const float threshold = 0.25f / std::max(1.0f, chip_pixels);
  constexpr int steps = int(MIXIE_CAT_MAX_SLEEP_SECONDS / MIXIE_CAT_FRAME_SECONDS);
  for (int step = 1; step <= steps; step++) {
    const double interval = step * MIXIE_CAT_FRAME_SECONDS;
    if (mixie_cat_pose_displacement(present, motion.at(now + interval)) >= threshold) {
      /* Wake one sample before the threshold crossing, not after it. */
      return std::max(1, step - 1) * MIXIE_CAT_FRAME_SECONDS;
    }
  }
  return MIXIE_CAT_MAX_SLEEP_SECONDS;
}
}  // namespace blender
