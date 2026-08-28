# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Rigid-transform math for mate frames and solved placement (no bpy import).

A *frame* is a right-handed orthonormal basis + origin, stored as a 4x4
row-major matrix (tuple of 4 tuples). Frames are published by parts in
PART-LOCAL space; the compiler turns them into world frames via the part's
placement and solves each new part's placement from its primary mate:

    T_j = F_i_world @ FLIP @ DELTA(fit) @ inv(F_j_local)          (paper Eq. 1)

Mate convention: each frame's +Z points OUT of its own part toward the
partner, +X is the tangential alignment reference. Mating aligns z_j to
-z_i and x_j to +x_i, with the fit offset applied along +z_i.

Pure Python (no mathutils) so it unit-tests under the repo's mocked bpy.
"""

from __future__ import annotations

import math

Mat4 = tuple  # 4x4 row-major nested tuple

IDENTITY: Mat4 = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)

# 180-degree rotation about X: maps +Z to -Z (and +Y to -Y) while keeping +X.
# This is the "face each other" flip between the two halves of a mate.
FLIP_Z: Mat4 = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, -1.0, 0.0, 0.0),
    (0.0, 0.0, -1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def _norm(v):
    l = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if l < 1e-12:
        raise ValueError("zero-length axis vector")
    return (v[0] / l, v[1] / l, v[2] / l)


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def frame_matrix(origin, z_axis, x_hint=None) -> Mat4:
    """Frame from an origin + outward Z axis (+ optional X hint).

    X is the hint re-orthogonalized against Z; without a hint the least-
    aligned world axis is used, so the basis is always deterministic.
    """
    z = _norm(z_axis)
    if x_hint is None:
        # Pick the world axis least aligned with z as the X seed.
        seeds = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        x_hint = min(seeds, key=lambda s: abs(_dot(s, z)))
    xh = _norm(x_hint)
    # Remove the Z component, guard near-parallel hints.
    d = _dot(xh, z)
    xr = (xh[0] - d * z[0], xh[1] - d * z[1], xh[2] - d * z[2])
    try:
        x = _norm(xr)
    except ValueError:
        return frame_matrix(origin, z_axis, None)
    y = _cross(z, x)
    o = origin
    return (
        (x[0], y[0], z[0], float(o[0])),
        (x[1], y[1], z[1], float(o[1])),
        (x[2], y[2], z[2], float(o[2])),
        (0.0, 0.0, 0.0, 1.0),
    )


def mat_mul(a: Mat4, b: Mat4) -> Mat4:
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4))
        for i in range(4)
    )


def mat_invert_rigid(m: Mat4) -> Mat4:
    """Inverse of a rigid (rotation + translation) transform: R^T, -R^T t."""
    r = [[m[i][j] for j in range(3)] for i in range(3)]
    t = (m[0][3], m[1][3], m[2][3])
    rt = [[r[j][i] for j in range(3)] for i in range(3)]
    nt = tuple(-(rt[i][0] * t[0] + rt[i][1] * t[1] + rt[i][2] * t[2]) for i in range(3))
    return (
        (rt[0][0], rt[0][1], rt[0][2], nt[0]),
        (rt[1][0], rt[1][1], rt[1][2], nt[1]),
        (rt[2][0], rt[2][1], rt[2][2], nt[2]),
        (0.0, 0.0, 0.0, 1.0),
    )


def translation(x: float, y: float, z: float) -> Mat4:
    return (
        (1.0, 0.0, 0.0, float(x)),
        (0.0, 1.0, 0.0, float(y)),
        (0.0, 0.0, 1.0, float(z)),
        (0.0, 0.0, 0.0, 1.0),
    )


def transform_point(m: Mat4, p) -> tuple:
    return tuple(
        m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3]
        for i in range(3)
    )


def transform_dir(m: Mat4, v) -> tuple:
    return tuple(
        m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] for i in range(3)
    )


def solve_placement(
    partner_frame_world: Mat4,
    new_part_frame_local: Mat4,
    fit_offset_m: float = 0.0,
) -> Mat4:
    """Solved rigid placement for the new part (paper Eq. 1).

    Aligns the new part's local mate frame onto the partner's world mate
    frame face-to-face (z_j -> -z_i, x_j -> +x_i), backed off/pressed in by
    ``fit_offset_m`` along the partner frame's +Z.
    """
    delta = translation(0.0, 0.0, float(fit_offset_m))
    return mat_mul(
        mat_mul(mat_mul(partner_frame_world, delta), FLIP_Z),
        mat_invert_rigid(new_part_frame_local),
    )


def frame_residual(f_world_a: Mat4, f_world_b: Mat4) -> dict:
    """How far two world frames are from a perfect face-to-face mate:
    origin distance (m) and axis misalignment (deg, z_b vs -z_a).
    Used to check a part's SECONDARY mates after its primary placed it."""
    oa = (f_world_a[0][3], f_world_a[1][3], f_world_a[2][3])
    ob = (f_world_b[0][3], f_world_b[1][3], f_world_b[2][3])
    dist = math.sqrt(sum((oa[i] - ob[i]) ** 2 for i in range(3)))
    za = (f_world_a[0][2], f_world_a[1][2], f_world_a[2][2])
    zb = (f_world_b[0][2], f_world_b[1][2], f_world_b[2][2])
    c = max(-1.0, min(1.0, -_dot(za, zb)))
    return {"origin_dist_m": dist, "axis_misalign_deg": math.degrees(math.acos(c))}
