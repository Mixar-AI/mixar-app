/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** Compile against the shipped pose header only — no Mixar binary.
 *
 *   c++ -std=c++17 -I src/source/blender/editors/space_agent_bubble \
 *       tests/pill_cat_pose_harness.cc -o pose_harness
 */

#include "agent_ui_pill_cat_pose.hh"

#include <cstdio>

using blender::mixie_cat_eval_pose;
using blender::MIXIE_BLINK_CLOSE;
using blender::MIXIE_BLINK_HOLD;
using blender::MIXIE_BLINK_SPAN;
using blender::MIXIE_GAZE_HOLD_END;
using blender::MIXIE_GAZE_OUT_END;
using blender::MIXIE_GAZE_PERIOD;
using blender::MIXIE_GAZE_REST_END;

static void emit(const char *label, const blender::MixieCatPose &p)
{
  std::printf("%s openness=%.6f look_x=%.6f look_y=%.6f bounce=%.6f breathe=%.6f tilt=%.6f\n",
              label,
              double(p.openness),
              double(p.look_x),
              double(p.look_y),
              double(p.bounce),
              double(p.breathe),
              double(p.tilt));
}

int main()
{
  const double hold_a = MIXIE_BLINK_CLOSE + 0.20 * MIXIE_BLINK_HOLD;
  const double hold_b = MIXIE_BLINK_CLOSE + 0.80 * MIXIE_BLINK_HOLD;
  const double open_t = MIXIE_BLINK_SPAN + 0.90;
  const double glance_t = 0.5 * (MIXIE_GAZE_OUT_END + MIXIE_GAZE_HOLD_END) * MIXIE_GAZE_PERIOD;
  const double home_t = 0.5 * MIXIE_GAZE_REST_END * MIXIE_GAZE_PERIOD;

  emit("idle_hold_a", mixie_cat_eval_pose(hold_a, false));
  emit("idle_hold_b", mixie_cat_eval_pose(hold_b, false));
  emit("idle_open", mixie_cat_eval_pose(open_t, false));
  emit("idle_glance", mixie_cat_eval_pose(glance_t, false));
  emit("idle_home", mixie_cat_eval_pose(home_t, false));
  emit("working_open", mixie_cat_eval_pose(open_t, true));
  emit("working_hold", mixie_cat_eval_pose(hold_a, true));
  emit("working_glance_clock", mixie_cat_eval_pose(glance_t, true));

  return 0;
}
