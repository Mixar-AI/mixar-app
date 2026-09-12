/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include <algorithm>
#include <cstdint>

namespace blender {
struct ARegion;
namespace ui {
struct Button;

/** Seconds, independent of display scale and frame cadence. */
namespace mixar_motion {
constexpr double hover_seconds = 0.14;
constexpr double press_seconds = 0.08;
constexpr double selection_seconds = 0.20;
constexpr double enter_seconds = 0.26;
constexpr double exit_seconds = 0.20;
constexpr double stagger_seconds = 0.05;
constexpr double frame_seconds = 1.0 / 60.0;

inline float ease_out(const float progress)
{
  const float remaining = 1.0f - std::clamp(progress, 0.0f, 1.0f);
  return 1.0f - remaining * remaining * remaining;
}
}  // namespace mixar_motion

/** Presentation only. First sighting is settled; a changed target starts from
 * the current time-sampled pose, even between frames or after an interruption.
 * Hosts own this value; no global control IDs, RNA writes or serialized state. */
struct MixarMotionValue {
  float value = 0.0f;
  float from = 0.0f;
  float target = 0.0f;
  double started = 0.0;
  double duration = 0.0;
  bool initialized = false;

  void settle(const float next)
  {
    value = from = target = next;
    duration = 0.0;
    initialized = true;
  }

  float at(const double now) const
  {
    if (duration <= 0.0 || now >= started + duration) {
      return target;
    }
    const float progress = mixar_motion::ease_out(float((now - started) / duration));
    return from + (target - from) * progress;
  }

  float sample(const float next, const double now, const double seconds)
  {
    if (!initialized || seconds <= 0.0) {
      settle(next);
      return value;
    }
    value = at(now);
    if (next != target) {
      from = value;
      target = next;
      started = now;
      duration = seconds;
    }
    return value;
  }

  bool active(const double now) const
  {
    return initialized && from != target && now < started + duration;
  }
};

struct MixarInteraction {
  float hover = 0.0f;
  float press = 0.0f;
  float selected = 0.0f;
};

struct MixarButtonMotion {
  MixarMotionValue hover, press, selected;
  /** Borrowed identity only: never dereferenced. Native execution consumes
   * Button::optype before the next layout rebuild. */
  const void *operator_identity = nullptr;
};

/** An on-demand timer wakes only live regions until their final settled frame.
 * No retained window/context ownership and no idle or scene redraw loop. */
void mixar_motion_request(ARegion *region, double deadline);
float mixar_motion_step(MixarMotionValue &motion, float target, double seconds, ARegion *region);
void mixar_button_motion_update(Button &button, ARegion *region);
MixarInteraction mixar_button_motion(const Button &button);

/** Read-only QA diagnostics. Counts are session-local, never telemetry. */
struct MixarMotionStats {
  uint64_t pending_regions, ticks, redraws;
};
MixarMotionStats mixar_motion_stats();

}  // namespace ui
}  // namespace blender
