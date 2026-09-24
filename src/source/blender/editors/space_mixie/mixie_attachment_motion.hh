/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once

#include <algorithm>
#include <array>
#include <cmath>

namespace blender::ed::mixie {
constexpr double ATTACHMENT_FLIGHT_SECONDS = 0.68;
constexpr double ATTACHMENT_FLIGHT_STAGGER = 0.055;
using FlightPoint = std::array<float, 2>;
using FlightQuad = std::array<FlightPoint, 4>; /* bottom-left, bottom-right,
                                                  top-right, top-left */

inline float flight_ease(float t)
{
  t = std::clamp(t, 0.0f, 1.0f);
  return t * t * (3.0f - 2.0f * t);
}

/* The leading edge arrives first. Delayed rows form the narrowing, curved
 * ribbon of a Dock-style minimize, with exact source and destination poses. */
inline FlightPoint attachment_flight_vertex(
    const FlightQuad &source, const FlightQuad &target, float x, float y, float progress)
{
  const float t = flight_ease((progress - 0.20f * y) / (1.0f - 0.20f * y));
  const float lift = 72.0f * std::sin(3.14159265f * t);
  FlightPoint p{};
  for (int axis = 0; axis < 2; axis++) {
    const float a = (1 - y) * ((1 - x) * source[0][axis] + x * source[1][axis]) +
                    y * ((1 - x) * source[3][axis] + x * source[2][axis]);
    const float b = (1 - y) * ((1 - x) * target[0][axis] + x * target[1][axis]) +
                    y * ((1 - x) * target[3][axis] + x * target[2][axis]);
    p[axis] = t >= 1 ? b : a + (b - a) * t + (axis == 1 ? lift : 0.0f);
  }
  return p;
}
inline float attachment_flight_alpha(float progress)
{
  return 1.0f - flight_ease((progress - 0.86f) / 0.14f);
}
}  // namespace blender::ed::mixie
