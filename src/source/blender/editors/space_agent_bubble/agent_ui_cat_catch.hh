/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */

#pragma once

#include "agent_ui_pill_cat_pose.hh"

#include <algorithm>
#include <cmath>

namespace blender {

/** Flight-driven catch. Progress is the live attachment clock
 * (`(now - start) / ATTACHMENT_FLIGHT_SECONDS`); 1 is the landing frame.
 * Look is already in cat space. Defaults are a held near-catch so pose-only
 * tests stay distinct without inventing a second timer. */
struct MixieCatCatch {
  float progress = 0.84f;
  float look_x = -0.70f;
  float look_y = 0.42f;
};

/** Map a desktop image/cat pair onto the 44px look range. */
inline MixieCatCatch mixie_cat_catch_aim(
    const float progress, const float image_x, const float image_y, const float cat_x, const float cat_y)
{
  const float dx = image_x - cat_x;
  const float dy = image_y - cat_y;
  const float len = std::max(1.0f, std::sqrt(dx * dx + dy * dy));
  return {progress,
          std::clamp(dx / len, -0.85f, 0.85f),
          std::clamp(dy / len, -0.65f, 0.65f)};
}

/** One locked target: the soonest landing that is still in flight. */
inline int mixie_cat_catch_pick(const float *progress, const double *arrival, const int count)
{
  int best = -1;
  for (int i = 0; i < count; i++) {
    if (progress[i] > 1.0f) {
      continue;
    }
    if (best < 0 || arrival[i] < arrival[best]) {
      best = i;
    }
  }
  return best;
}

/** Chip centre in native window pixels — same elongated-pill slot the painter
 * uses (right-inset 10.5, 85×68 at the 85-unit design height). */
inline void mixie_cat_pill_chip_center(const float native_w, const float native_h, float &x, float &y)
{
  const float u = native_h / 85.0f;
  x = native_w - 10.5f * u - 42.5f * u;
  y = native_h * 0.5f;
}

/** Painter ear-tip extent after the 12° style tilt, breath, bounce and the
 * -0.025 face offset — the same vertices the chip-containment tests use. */
inline float mixie_cat_catch_ear_extent(const MixieCatPose &p)
{
  constexpr float k_pi = 3.14159265f;
  const float angle = (12.0f + p.tilt) * k_pi / 180.0f;
  const float c = std::cos(angle);
  const float s = std::sin(angle);
  float extent = 0.0f;
  for (const float side : {-1.0f, 1.0f}) {
    const float x = side * 0.285f;
    const float y = 0.375f * (side < 0.0f ? p.ear_height_l : p.ear_height_r);
    const float tx = p.breathe * (x * c - y * s);
    const float ty = p.breathe * (x * s + y * c) + p.bounce - 0.025f;
    extent = std::max(extent, std::max(std::abs(tx), std::abs(ty)));
  }
  return extent;
}

/** Scale look-driven extras toward the catch lean so a corner reach stays
 * inside the chip. Direction is kept; only the stacked amplitude shrinks. */
inline void mixie_cat_catch_keep_in_chip(MixieCatPose &p)
{
  constexpr float k_limit = 0.487f;
  constexpr float k_lean = -8.0f;
  const float tilt_extra = p.tilt - k_lean;
  const float el_extra = p.ear_height_l - 1.0f;
  const float er_extra = p.ear_height_r - 1.0f;
  const float bounce0 = p.bounce;
  const float breathe_extra = p.breathe - 1.0f;
  MixieCatPose rest = p;
  rest.tilt = k_lean;
  rest.ear_height_l = rest.ear_height_r = 1.0f;
  rest.bounce = 0.0f;
  rest.breathe = 1.0f;
  const float base = mixie_cat_catch_ear_extent(rest);
  float scale = 1.0f;
  for (int i = 0; i < 6; i++) {
    p.tilt = k_lean + tilt_extra * scale;
    p.ear_height_l = 1.0f + el_extra * scale;
    p.ear_height_r = 1.0f + er_extra * scale;
    p.bounce = bounce0 * scale;
    p.breathe = 1.0f + breathe_extra * scale;
    const float extent = mixie_cat_catch_ear_extent(p);
    if (extent <= k_limit) {
      return;
    }
    scale *= std::clamp((k_limit - base) / std::max(1e-5f, extent - base), 0.0f, 1.0f);
  }
}

/** Track, anticipate, then reach. The snap is the reach at progress 1, not a
 * blink; openness still uses the shared blink so the face stays alive. */
inline MixieCatPose mixie_cat_catch_pose(const double now, const MixieCatCatch &c)
{
  MixieCatPose p = mixie_cat_eval_pose(now, false);
  const float t = std::clamp(c.progress, 0.0f, 1.0f);
  const float anticipate = mixie_cat_smooth01((t - 0.35f) / 0.30f);
  const float reach = mixie_cat_smooth01((t - 0.82f) / 0.18f);
  p.look_x = c.look_x;
  p.look_y = c.look_y;
  p.tilt = -8.0f + c.look_x * 14.0f;
  p.eye_scale = 1.06f + 0.10f * anticipate;
  p.eye_width = 1.06f + 0.06f * anticipate;
  p.pupil_scale = 1.16f - 0.22f * reach;
  p.ear_height_l = 1.0f + 0.08f * anticipate + 0.06f * reach * std::max(0.0f, -c.look_x);
  p.ear_height_r = 1.0f + 0.08f * anticipate + 0.06f * reach * std::max(0.0f, c.look_x);
  p.bounce = 0.036f * reach * (0.40f + 0.60f * std::max(0.0f, c.look_y));
  p.breathe = 1.0f + 0.010f * reach;
  p.lid_l = 1.02f - 0.10f * reach;
  p.lid_r = 1.02f - 0.10f * reach;
  p.openness = mixie_cat_blink_openness(now, 1.0f);
  if (reach > 0.2f) {
    p.openness = std::max(p.openness, 0.72f);
  }
  mixie_cat_catch_keep_in_chip(p);
  return p;
}

}  // namespace blender
