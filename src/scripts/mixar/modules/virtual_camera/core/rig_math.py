# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure math for the virtual camera rig — no bpy/mathutils, fully unit-testable.

Quaternions are (w, x, y, z) tuples in Blender's convention (Z-up world,
camera looking down local -Z with +Y up). The phone app sends quaternions
already converted to this convention.
"""

from __future__ import annotations

import math

Quat = tuple[float, float, float, float]
Vec3 = tuple[float, float, float]

IDENTITY: Quat = (1.0, 0.0, 0.0, 0.0)


def q_normalize(q: Quat) -> Quat:
    n = math.sqrt(sum(c * c for c in q))
    if n < 1e-12:
        return IDENTITY
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def q_multiply(a: Quat, b: Quat) -> Quat:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def q_conjugate(q: Quat) -> Quat:
    return (q[0], -q[1], -q[2], -q[3])


def q_slerp(a: Quat, b: Quat, t: float) -> Quat:
    """Spherical interpolation, shortest arc."""
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0.0:
        b = tuple(-c for c in b)  # type: ignore[assignment]
        dot = -dot
    dot = min(dot, 1.0)
    if dot > 0.9995:
        mixed = tuple(x + t * (y - x) for x, y in zip(a, b))
        return q_normalize(mixed)  # type: ignore[arg-type]
    theta = math.acos(dot)
    s = math.sin(theta)
    wa = math.sin((1.0 - t) * theta) / s
    wb = math.sin(t * theta) / s
    return q_normalize(tuple(wa * x + wb * y for x, y in zip(a, b)))  # type: ignore[arg-type]


def q_rotate_vec(q: Quat, v: Vec3) -> Vec3:
    """Rotate vector v by quaternion q."""
    qv: Quat = (0.0, v[0], v[1], v[2])
    w, x, y, z = q_multiply(q_multiply(q, qv), q_conjugate(q))
    return (x, y, z)


def q_from_axis_angle(axis: Vec3, angle: float) -> Quat:
    h = angle / 2.0
    s = math.sin(h)
    return (math.cos(h), axis[0] * s, axis[1] * s, axis[2] * s)


def smoothing_alpha(smoothing: float, dt: float) -> float:
    """Frame-rate-independent smoothing factor.

    `smoothing` in [0, 0.95] is the per-1/60s retained fraction; converting
    through a time constant keeps the feel identical at any apply cadence.
    """
    smoothing = min(max(smoothing, 0.0), 0.95)
    if smoothing <= 0.0:
        return 1.0
    base_dt = 1.0 / 60.0
    return 1.0 - smoothing ** (dt / base_dt)


def recenter_offset(camera_q: Quat, phone_q: Quat) -> Quat:
    """World-space offset O such that O ⊗ phone_q == camera_q at this instant.

    Applying O to later phone readings maps relative phone motion onto the
    camera while preserving the framing it had when the user hit Recenter.
    """
    return q_normalize(q_multiply(camera_q, q_conjugate(phone_q)))


def apply_offset(offset: Quat, phone_q: Quat) -> Quat:
    return q_normalize(q_multiply(offset, phone_q))


def joystick_velocity(j1: tuple[float, float], j2: tuple[float, float],
                      camera_q: Quat, speed: float) -> tuple[Vec3, float]:
    """Map joystick state to (world-space velocity m/s, yaw rate rad/s).

    Left stick: truck (x) / dolly (y) on the camera's ground-plane heading.
    Right stick: boom up-down (y, world Z) / additional yaw pan (x).
    """
    fwd = q_rotate_vec(camera_q, (0.0, 0.0, -1.0))
    right = q_rotate_vec(camera_q, (1.0, 0.0, 0.0))

    # Project heading onto the ground plane so dolly doesn't dive when the
    # camera pitches; fall back to raw axes when looking straight down.
    fx, fy = fwd[0], fwd[1]
    fn = math.hypot(fx, fy)
    if fn > 1e-6:
        fx, fy = fx / fn, fy / fn
    else:
        ux, uy, _ = q_rotate_vec(camera_q, (0.0, 1.0, 0.0))
        un = math.hypot(ux, uy) or 1.0
        fx, fy = ux / un, uy / un
    rx, ry = right[0], right[1]
    rn = math.hypot(rx, ry) or 1.0
    rx, ry = rx / rn, ry / rn

    vx = (rx * j1[0] + fx * j1[1]) * speed
    vy = (ry * j1[0] + fy * j1[1]) * speed
    vz = j2[1] * speed
    yaw_rate = -j2[0]
    return (vx, vy, vz), yaw_rate


def vertigo_dolly(distance0: float, lens0: float, lens1: float) -> float:
    """Dolly-zoom distance: keep subject size constant as lens changes.

    Field width at distance d is proportional to d / lens, so preserving the
    framing requires d1 = d0 * lens1 / lens0.
    """
    if lens0 <= 0.0:
        return distance0
    return distance0 * (lens1 / lens0)
