/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once

#include <algorithm>
#include <array>
#include <cmath>

namespace blender::ed::mixie {
constexpr double ATTACHMENT_FLIGHT_SECONDS = 0.68;
constexpr double ATTACHMENT_FLIGHT_STAGGER = 0.055;
/* Share of the clock separating the leading and trailing edges. Every point
 * travels for the remaining share, so the edge facing the destination lands
 * first and the rest pours in behind it. */
constexpr float ATTACHMENT_FLIGHT_LAG = 0.16f;
/* Sideways bow of the path, as a share of the travel distance, capped in
 * desktop points. Vertical travel stays straight, like a Dock minimize. */
constexpr float ATTACHMENT_FLIGHT_BOW = 0.12f;
constexpr float ATTACHMENT_FLIGHT_BOW_MAX = 96.0f;
/* Tessellation per axis: the lag runs diagonally, so both axes bend. */
constexpr int ATTACHMENT_FLIGHT_GRID = 24;
using FlightPoint = std::array<float, 2>;
using FlightQuad = std::array<FlightPoint, 4>; /* bottom-left, bottom-right,
                                                  top-right, top-left */

/** A painted thumbnail takes over from the exact final pose, or the image
 * dissolves into a point target (the resting pill). */
enum class FlightLanding { Handoff, Dissolve };

/** Everything a frame needs, fixed when the flight starts. */
struct FlightPath {
  FlightQuad source{}, target{};
  /* Lag weight over the unit square: 0 at the corner facing the destination,
   * 1 at the opposite one. Bottom-first until a direction is known. */
  float lag_origin = 0.0f, lag_u = 0.0f, lag_v = 1.0f;
  FlightPoint bow{};
  FlightLanding landing = FlightLanding::Dissolve;
};

/** Ease-in-out with a longer settle: cubic-bezier(0.45, 0, 0.2, 1). The
 * gentle start reads as lifting the card; zero arrival velocity lets the
 * landed pose hand off to the static thumbnail without a visible stop. */
inline float flight_ease(float t)
{
  t = std::clamp(t, 0.0f, 1.0f);
  constexpr float x1 = 0.45f, x2 = 0.2f;
  auto bezier = [](float a, float b, float s) {
    const float r = 1.0f - s;
    return 3.0f * r * r * s * a + 3.0f * r * s * s * b + s * s * s;
  };
  float s = t;
  for (int i = 0; i < 6; i++) {
    const float r = 1.0f - s;
    const float slope = 3.0f * r * r * x1 + 6.0f * r * s * (x2 - x1) + 3.0f * s * s * (1.0f - x2);
    if (slope < 1e-4f) {
      break;
    }
    s = std::clamp(s - (bezier(x1, x2, s) - t) / slope, 0.0f, 1.0f);
  }
  return bezier(0.0f, 1.0f, s);
}

inline FlightPoint flight_quad_point(const FlightQuad &q, float x, float y)
{
  FlightPoint p{};
  for (int axis = 0; axis < 2; axis++) {
    p[axis] = (1 - y) * ((1 - x) * q[0][axis] + x * q[1][axis]) +
              y * ((1 - x) * q[3][axis] + x * q[2][axis]);
  }
  return p;
}

/** Height over width of a (possibly rotated) card. */
inline float flight_quad_aspect(const FlightQuad &q)
{
  const float w = std::hypot(q[1][0] - q[0][0], q[1][1] - q[0][1]);
  const float h = std::hypot(q[3][0] - q[0][0], q[3][1] - q[0][1]);
  return w > 1e-3f && h > 1e-3f ? h / w : 1.0f;
}

/** Aspect-fit a picture into a box, centred: the thumbnail painter's rule, so
 * the landed ribbon is the thumbnail rather than a squashed square. */
inline FlightQuad flight_fit_quad(float aspect, float xmin, float xmax, float ymin, float ymax)
{
  const float box_w = std::max(0.0f, xmax - xmin), box_h = std::max(0.0f, ymax - ymin);
  float w = box_w, h = box_w * aspect;
  if (h > box_h) {
    h = box_h;
    w = aspect > 1e-6f ? box_h / aspect : box_w;
  }
  const float cx = (xmin + xmax) * 0.5f, cy = (ymin + ymax) * 0.5f;
  return {{{cx - w / 2, cy - h / 2}, {cx + w / 2, cy - h / 2}, {cx + w / 2, cy + h / 2},
           {cx - w / 2, cy + h / 2}}};
}

/** Lead with the corner facing the destination, so the sheet stretches along
 * its travel instead of shearing sideways or folding through itself, and bow
 * the path upward like a toss. */
inline FlightPath attachment_flight_path(const FlightQuad &source,
                                         const FlightQuad &target,
                                         FlightLanding landing)
{
  FlightPath path;
  path.source = source;
  path.target = target;
  path.landing = landing;
  const FlightPoint from = flight_quad_point(source, 0.5f, 0.5f);
  const FlightPoint to = flight_quad_point(target, 0.5f, 0.5f);
  const float dx = to[0] - from[0], dy = to[1] - from[1];
  const float distance = std::hypot(dx, dy);
  if (distance < 1.0f) {
    return path;
  }
  /* The card's own axes: a rotated or flipped card leads in texture space. */
  float lead[2] = {0.0f, 0.0f};
  for (int axis = 0; axis < 2; axis++) {
    const FlightPoint &end = source[axis == 0 ? 1 : 3];
    const float ex = end[0] - source[0][0], ey = end[1] - source[0][1];
    const float length = std::hypot(ex, ey);
    lead[axis] = length > 1e-3f ? (dx * ex + dy * ey) / (length * distance) : 0.0f;
  }
  const float spread = std::abs(lead[0]) + std::abs(lead[1]);
  if (spread > 1e-3f) {
    path.lag_u = -lead[0] / spread;
    path.lag_v = -lead[1] / spread;
    path.lag_origin = (std::max(lead[0], 0.0f) + std::max(lead[1], 0.0f)) / spread;
  }
  float side[2] = {-dy / distance, dx / distance};
  if (side[1] < 0.0f) {
    side[0] = -side[0];
    side[1] = -side[1];
  }
  const float bow = std::min(ATTACHMENT_FLIGHT_BOW_MAX, ATTACHMENT_FLIGHT_BOW * distance) *
                    std::abs(dx) / distance;
  path.bow = {side[0] * bow, side[1] * bow};
  return path;
}

/** Eased travel of one point of the sheet, 0 at the source, 1 landed. */
inline float attachment_flight_point_progress(const FlightPath &path,
                                              float x,
                                              float y,
                                              float progress)
{
  const float weight = std::clamp(path.lag_origin + path.lag_u * x + path.lag_v * y, 0.0f, 1.0f);
  return flight_ease((progress - ATTACHMENT_FLIGHT_LAG * weight) /
                     (1.0f - ATTACHMENT_FLIGHT_LAG));
}

/* Exact source and destination poses; missed frames clamp to the landing. */
inline FlightPoint attachment_flight_vertex(const FlightPath &path,
                                            float x,
                                            float y,
                                            float progress)
{
  const FlightPoint b = flight_quad_point(path.target, x, y);
  if (progress >= 1.0f) {
    return b;
  }
  const FlightPoint a = flight_quad_point(path.source, x, y);
  const float t = attachment_flight_point_progress(path, x, y, progress);
  const float arc = std::sin(3.14159265f * t);
  return {a[0] + (b[0] - a[0]) * t + path.bow[0] * arc,
          a[1] + (b[1] - a[1]) * t + path.bow[1] * arc};
}

/** A handoff stays opaque and holds the landed pose until the painter shows
 * the thumbnail in the same redraw. A dissolve fades while the tail pours into
 * the pill. */
inline float attachment_flight_alpha(const FlightPath &path, float progress)
{
  if (path.landing == FlightLanding::Handoff) {
    return 1.0f;
  }
  const float t = std::clamp((progress - 0.78f) / 0.22f, 0.0f, 1.0f);
  return 1.0f - t * t * (3.0f - 2.0f * t);
}
}  // namespace blender::ed::mixie
