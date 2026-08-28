# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Solved-placement math (paper Eq. 1) — pure Python, no bpy."""
import math

from mixar.modules.procedural_assembly import frames


def _almost(a, b, tol=1e-9):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_frame_matrix_orthonormal_and_deterministic():
    m = frames.frame_matrix((1, 2, 3), (0, 0, 1))
    x = (m[0][0], m[1][0], m[2][0])
    y = (m[0][1], m[1][1], m[2][1])
    z = (m[0][2], m[1][2], m[2][2])
    for v in (x, y, z):
        assert abs(math.sqrt(sum(c * c for c in v)) - 1.0) < 1e-9
    assert abs(sum(a * b for a, b in zip(x, y))) < 1e-9
    assert abs(sum(a * b for a, b in zip(x, z))) < 1e-9
    # right-handed: x cross y == z
    cx = (
        x[1] * y[2] - x[2] * y[1],
        x[2] * y[0] - x[0] * y[2],
        x[0] * y[1] - x[1] * y[0],
    )
    assert _almost(cx, z)
    assert _almost((m[0][3], m[1][3], m[2][3]), (1, 2, 3))
    # same inputs -> identical matrix (no hidden state)
    assert frames.frame_matrix((1, 2, 3), (0, 0, 1)) == m


def test_invert_rigid_roundtrip():
    m = frames.frame_matrix((0.3, -1.2, 2.0), (0, 1, 0), x_hint=(1, 0, 0))
    ident = frames.mat_mul(m, frames.mat_invert_rigid(m))
    for i in range(4):
        for j in range(4):
            assert abs(ident[i][j] - (1.0 if i == j else 0.0)) < 1e-9


def test_solve_placement_aligns_frames_face_to_face():
    # Partner frame at world (1,0,0), +Z pointing +X (out of the partner).
    f_i = frames.frame_matrix((1, 0, 0), (1, 0, 0), x_hint=(0, 0, 1))
    # New part's local frame at its own (0,0,0.5), +Z up (out of the part).
    f_j = frames.frame_matrix((0, 0, 0.5), (0, 0, 1))
    t = frames.solve_placement(f_i, f_j, fit_offset_m=0.0)
    # The part's frame origin must land on the partner frame origin...
    world = frames.transform_point(t, (0, 0, 0.5))
    assert _almost(world, (1, 0, 0), tol=1e-9)
    # ...and the part's +Z (local frame z) must map to -partner z (-X world).
    zj_world = frames.transform_dir(t, (0, 0, 1))
    assert _almost(zj_world, (-1, 0, 0), tol=1e-9)


def test_solve_placement_fit_offset_backs_off_along_partner_z():
    f_i = frames.frame_matrix((0, 0, 1), (0, 0, 1))
    f_j = frames.frame_matrix((0, 0, 0), (0, 0, 1))
    t = frames.solve_placement(f_i, f_j, fit_offset_m=0.002)
    world = frames.transform_point(t, (0, 0, 0))
    assert _almost(world, (0, 0, 1.002), tol=1e-9)


def test_frame_residual_reports_distance_and_misalignment():
    a = frames.frame_matrix((0, 0, 0), (0, 0, 1))
    b = frames.frame_matrix((0.01, 0, 0), (0, 0, -1))   # perfect anti-align
    r = frames.frame_residual(a, b)
    assert abs(r["origin_dist_m"] - 0.01) < 1e-9
    assert r["axis_misalign_deg"] < 1e-6
    c = frames.frame_matrix((0, 0, 0), (1, 0, 0))
    r2 = frames.frame_residual(a, c)
    assert abs(r2["axis_misalign_deg"] - 90.0) < 1e-6
