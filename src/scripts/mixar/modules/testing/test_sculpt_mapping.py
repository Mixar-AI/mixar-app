# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the pure sculpt-stroke coordinate math (no bpy required)."""
import importlib.util
import os

# Load mapping.py directly by path so the test needs no package import
# machinery / bpy. Mirrors how other pure-logic tests isolate a single module.
_HERE = os.path.dirname(__file__)
_PATH = os.path.join(_HERE, "..", "sculpt_agent", "mapping.py")
_spec = importlib.util.spec_from_file_location("sculpt_mapping", _PATH)
mapping = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mapping)


# Camera frame corners in Camera.view_frame order:
# [right-top, right-bottom, left-bottom, left-top], on the z = 0 plane.
_CORNERS = [
    (1.0, 1.0, 0.0),   # right-top
    (1.0, -1.0, 0.0),  # right-bottom
    (-1.0, -1.0, 0.0), # left-bottom
    (-1.0, 1.0, 0.0),  # left-top
]


def test_frame_point_corners():
    assert mapping.frame_point(_CORNERS, 0.0, 0.0) == (-1.0, -1.0, 0.0)  # left-bottom
    assert mapping.frame_point(_CORNERS, 1.0, 1.0) == (1.0, 1.0, 0.0)    # right-top


def test_frame_point_center():
    assert mapping.frame_point(_CORNERS, 0.5, 0.5) == (0.0, 0.0, 0.0)


def test_frame_point_u_is_left_to_right():
    left = mapping.frame_point(_CORNERS, 0.25, 0.5)
    right = mapping.frame_point(_CORNERS, 0.75, 0.5)
    assert left[0] < right[0]


def test_ray_through_normalizes():
    origin, direction = mapping.ray_through((0, 0, 0), (0, 0, -10))
    assert origin == (0, 0, 0)
    assert abs(direction[2] + 1.0) < 1e-9
    length = sum(c * c for c in direction) ** 0.5
    assert abs(length - 1.0) < 1e-9


def test_ray_plane_intersect_hits():
    hit = mapping.ray_plane_intersect(
        (0, 0, 5), (0, 0, -1), plane_point=(0, 0, 0), plane_normal=(0, 0, 1)
    )
    assert hit is not None
    assert all(abs(a - b) < 1e-9 for a, b in zip(hit, (0.0, 0.0, 0.0)))


def test_ray_plane_intersect_parallel_is_none():
    assert mapping.ray_plane_intersect(
        (0, 0, 5), (1, 0, 0), plane_point=(0, 0, 0), plane_normal=(0, 0, 1)
    ) is None


def test_ray_plane_intersect_behind_is_none():
    # Plane behind the ray origin (ray points away).
    assert mapping.ray_plane_intersect(
        (0, 0, 5), (0, 0, 1), plane_point=(0, 0, 0), plane_normal=(0, 0, 1)
    ) is None


def test_resample_respects_max_gap():
    pts = mapping.resample_polyline([(0.0, 0.0), (1.0, 0.0)], max_gap=0.1)
    assert pts[0] == (0.0, 0.0) and pts[-1] == (1.0, 0.0)
    for a, b in zip(pts, pts[1:]):
        gap = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        assert gap <= 0.1 + 1e-9


def test_resample_keeps_short_segments():
    pts = [(0.0, 0.0), (0.01, 0.0), (0.02, 0.0)]
    assert mapping.resample_polyline(pts, max_gap=0.1) == pts


def test_pressure_flat():
    assert mapping.pressure_profile(4, "flat") == [1.0, 1.0, 1.0, 1.0]


def test_pressure_ease_ramps():
    p = mapping.pressure_profile(20, "ease")
    assert len(p) == 20
    assert p[0] < p[10]      # ramps in
    assert p[-1] < p[10]     # ramps out
    assert max(p) <= 1.0 and min(p) > 0.0
