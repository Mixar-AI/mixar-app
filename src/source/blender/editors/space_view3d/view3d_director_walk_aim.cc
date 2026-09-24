/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup spview3d
 *
 * The Cinema walk's mouse-look: how a left-button drag turns the camera.
 *
 * Pure math on the walk's running WORLD matrix — no context, no writes — so
 * it lives beside `view3d_director_walk.cc` rather than in it (500-line
 * rule); the walk commits the result through its one writer.
 */

#include <cmath>

#include "BLI_math_matrix_types.hh"
#include "BLI_math_vector.hh"

#include "view3d_director_camera_move.hh"

/* Mixar 5.2 port: namespace wrap. */
namespace blender {

namespace {

/** Radians of turn per pixel of drag. ~0.11 degrees: a full turn is a
 * comfortable sweep of the arm rather than a flick of the wrist. */
constexpr float WALK_LOOK_PER_PIXEL = 0.002f;
/** How close to straight up or down the aim may come, as |forward . Z|.
 * Past this the basis degenerates and the frame rolls. */
constexpr float WALK_PITCH_LIMIT = 0.995f;

/* -------------------------------------------------------------------- */
/** \name Vector helpers
 *
 * Spelled out rather than reached for: `math::cross` and `math::dot` are not
 * used anywhere else in this overlay, and a name that does not resolve costs
 * a build rather than a review comment.
 * \{ */

float3 cross3(const float3 &a, const float3 &b)
{
  return float3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x);
}

float dot3(const float3 &a, const float3 &b)
{
  return a.x * b.x + a.y * b.y + a.z * b.z;
}

float length3(const float3 &v)
{
  return std::sqrt(math::length_squared(v));
}

/** Rodrigues: \a v turned \a angle radians about \a axis (already unit). */
float3 rotate_about(const float3 &v, const float3 &axis, const float angle)
{
  const float c = std::cos(angle);
  const float s = std::sin(angle);
  return v * c + cross3(axis, v) * s + axis * (dot3(axis, v) * (1.0f - c));
}

/** \} */

}  // namespace

/**
 * Aim the camera by \a dx / \a dy pixels of drag: yaw about WORLD Z so the
 * horizon never tilts, pitch about the camera's own right axis.
 *
 * The basis is written through the axis accessors, the same shape as the
 * `location()` the walk's move assigns through. Each axis keeps its
 * original length, so a scaled camera is aimed rather than reset.
 */
bool director_walk_aim(float4x4 &matrix, const float dx, const float dy)
{
  if (dx == 0.0f && dy == 0.0f) {
    return false;
  }
  const float3 x_axis = matrix.x_axis();
  const float3 y_axis = matrix.y_axis();
  const float3 z_axis = matrix.z_axis();
  const float sx = length3(x_axis);
  const float sy = length3(y_axis);
  const float sz = length3(z_axis);
  if (sx <= 0.0f || sy <= 0.0f || sz <= 0.0f) {
    return false;
  }

  const float3 world_z(0.0f, 0.0f, 1.0f);
  /* Multiplied by the reciprocal rather than divided: scalar multiplication
   * is the form this overlay already uses on a `float3`. */
  float3 right = x_axis * (1.0f / sx);
  float3 forward = -(z_axis * (1.0f / sz));

  const float yaw = -dx * WALK_LOOK_PER_PIXEL;
  right = math::normalize(rotate_about(right, world_z, yaw));
  forward = math::normalize(rotate_about(forward, world_z, yaw));

  const float pitch = dy * WALK_LOOK_PER_PIXEL;
  const float3 pitched = math::normalize(rotate_about(forward, right, pitch));
  /* Refuse the last few degrees rather than clamping into them: a clamp that
   * lands exactly on the pole leaves the basis degenerate and the frame
   * rolls when the drag continues. */
  if (std::abs(dot3(pitched, world_z)) < WALK_PITCH_LIMIT) {
    forward = pitched;
  }

  const float3 back = -forward;
  const float3 up = math::normalize(cross3(back, right));
  /* Through the axis accessors, the way `location()` is already written to
   * here. `ptr()` is NOT the way: it yields `float[4][4]`, so binding it to
   * a `float *` and indexing flat does not compile — and the one API that
   * wants it (`BKE_object_apply_mat4`) takes the 2D form. */
  matrix.x_axis() = right * sx;
  matrix.y_axis() = up * sy;
  matrix.z_axis() = back * sz;
  return true;
}

}  // namespace blender
