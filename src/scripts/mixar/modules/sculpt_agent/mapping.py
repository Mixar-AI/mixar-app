# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure coordinate math for sculpt stroke replay (no bpy import).

The backend expresses stroke points as normalized coordinates in a specific
camera's rendered image: ``u`` in [0, 1] left→right, ``v`` in [0, 1]
bottom→top (matching Blender's camera ``view_frame`` corner order). The
stroke engine turns each (u, v) into a world-space ray from that camera,
raycasts the scene, and projects the hit back into the live viewport region
to obtain the operator's mouse coordinates.

Everything here is plain-tuple math so it can be unit-tested outside
Blender (see ``modules/testing/test_sculpt_mapping.py``).
"""

from __future__ import annotations


def _lerp3(a, b, t):
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


def frame_point(corners, u: float, v: float):
    """Bilinear point on a camera frame for normalized image coords.

    ``corners`` are the 4 world-space corners of the camera frame in
    Blender's ``Camera.view_frame`` order: [right-top, right-bottom,
    left-bottom, left-top]. ``u`` runs left→right, ``v`` bottom→top.
    """
    rt, rb, lb, lt = corners
    bottom = _lerp3(lb, rb, u)
    top = _lerp3(lt, rt, u)
    return _lerp3(bottom, top, v)


def ray_through(origin, target):
    """(origin, normalized direction) of the ray from origin through target."""
    d = (target[0] - origin[0], target[1] - origin[1], target[2] - origin[2])
    length = (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]) ** 0.5
    if length <= 1e-12:
        return origin, (0.0, 0.0, -1.0)
    return origin, (d[0] / length, d[1] / length, d[2] / length)


def ray_plane_intersect(origin, direction, plane_point, plane_normal):
    """Intersection of a ray with a plane, or None when (near-)parallel.

    Used as the off-surface fallback: a drag stroke's tail can leave the
    mesh silhouette, and the sculpt operator still needs a plausible mouse
    position — we intersect the view ray with the plane through the last
    on-surface hit, facing the camera.
    """
    denom = (
        direction[0] * plane_normal[0]
        + direction[1] * plane_normal[1]
        + direction[2] * plane_normal[2]
    )
    if abs(denom) < 1e-9:
        return None
    diff = (
        plane_point[0] - origin[0],
        plane_point[1] - origin[1],
        plane_point[2] - origin[2],
    )
    t = (
        diff[0] * plane_normal[0]
        + diff[1] * plane_normal[1]
        + diff[2] * plane_normal[2]
    ) / denom
    if t < 0.0:
        return None
    return (
        origin[0] + direction[0] * t,
        origin[1] + direction[1] * t,
        origin[2] + direction[2] * t,
    )


def resample_polyline(points, max_gap: float):
    """Resample a 2D polyline so consecutive points are at most ``max_gap``
    apart (same units as the input). Keeps original vertices; inserts evenly
    spaced intermediates on long segments. A sculpt stroke needs dense
    samples — the operator applies the brush once per stroke element, so a
    sparse polyline reads as dabs instead of a continuous stroke.
    """
    if not points or max_gap <= 0.0:
        return list(points)
    out = [points[0]]
    for b in points[1:]:
        a = out[-1]
        dx, dy = b[0] - a[0], b[1] - a[1]
        dist = (dx * dx + dy * dy) ** 0.5
        if dist > max_gap:
            steps = int(dist / max_gap)
            for i in range(1, steps + 1):
                t = i / (steps + 1)
                out.append((a[0] + dx * t, a[1] + dy * t))
        out.append(b)
    return out


def pressure_profile(n: int, profile: str = "flat"):
    """Per-point pressure for an ``n``-point stroke.

    ``flat`` — constant full pressure (Smear coverage, Draw engraving).
    ``ease`` — ramp in/out over the first/last 20% (Drag deformations,
    avoids a hard crater at the anchor and a snapped tail).
    """
    if n <= 0:
        return []
    if profile != "ease" or n == 1:
        return [1.0] * n
    ramp = max(1, int(n * 0.2))
    out = []
    for i in range(n):
        head = min(1.0, (i + 1) / ramp)
        tail = min(1.0, (n - i) / ramp)
        out.append(max(0.05, min(head, tail)))
    return out
