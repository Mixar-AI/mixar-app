# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure 2D primitives for mark strokes — no ``bpy``, no I/O.

Everything here operates on plain ``(x, y)`` tuples so the whole gesture
pipeline can be unit tested outside Blender (the root ``conftest.py`` stubs
``bpy`` as a MagicMock, which would make any geometry that leaned on
``mathutils`` silently return mocks instead of numbers).

Two conventions, kept straight because mixing them puts edits in the wrong
half of the frame:

* **region pixels** — what the modal captures. Origin bottom-left, y UP,
  matching Blender's ``event.mouse_region_x/y``.
* **normalized (u, v)** — what goes on the wire. ``u`` 0..1 left→right,
  ``v`` 0..1 bottom→top, matching the backend sculpt localizer's stroke
  convention (``modules/agent/sculpt/localize.py``). Because region pixels
  are already y-up, converting is a divide with no flip — the flip lives on
  the backend, where the VLM's top-down answers are converted on the way out.
"""

import math

from ..constants import (
    CLOSE_GAP_FACTOR,
    CLOSE_TURN_DEG,
    UV_DECIMALS,
)


# =============================================================================
# Bounds and measures
# =============================================================================

def bbox(points):
    """``(min_x, min_y, max_x, max_y)`` of *points*, or None when empty."""
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_center_size(points):
    """``((cx, cy), (w, h))`` of the bounding box, or None when empty."""
    box = bbox(points)
    if box is None:
        return None
    min_x, min_y, max_x, max_y = box
    return (
        ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0),
        (max_x - min_x, max_y - min_y),
    )


def bbox_diagonal(points):
    """Length of the bounding box diagonal. 0.0 for empty or single points."""
    box = bbox(points)
    if box is None:
        return 0.0
    min_x, min_y, max_x, max_y = box
    return math.hypot(max_x - min_x, max_y - min_y)


def path_length(points):
    """Total travelled distance along the polyline."""
    total = 0.0
    for i in range(1, len(points)):
        total += math.hypot(
            points[i][0] - points[i - 1][0],
            points[i][1] - points[i - 1][1],
        )
    return total


def centroid(points):
    """Arithmetic mean of *points*, or None when empty.

    Deliberately the vertex mean rather than the polygon area centroid: a
    mark's points are near-uniformly spaced along the stroke, and the vertex
    mean stays sane for OPEN strokes where an area centroid is meaningless.
    """
    if not points:
        return None
    n = float(len(points))
    return (
        sum(p[0] for p in points) / n,
        sum(p[1] for p in points) / n,
    )


def polygon_area(points):
    """Absolute shoelace area of the implied closed polygon."""
    n = len(points)
    if n < 3:
        return 0.0
    total = 0.0
    for i in range(n):
        x0, y0 = points[i][0], points[i][1]
        x1, y1 = points[(i + 1) % n][0], points[(i + 1) % n][1]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


def straightness(points):
    """``bbox_diagonal / path_length`` — 1.0 for a perfect line, ~0 for a coil.

    Returns 0.0 for a path that never moved, so a tap can never be mistaken
    for a strike-through.
    """
    length = path_length(points)
    if length <= 1e-9:
        return 0.0
    return min(1.0, bbox_diagonal(points) / length)


# =============================================================================
# Shape
# =============================================================================

def convex_hull(points):
    """Convex hull in counter-clockwise order (Andrew's monotone chain).

    Used to give an OPEN mark a sensible enclosing polygon: the user's squiggle
    over a region means "this area", and the hull is the smallest honest claim
    about which area that is. Degenerate inputs (< 3 unique points, or all
    collinear) come back as the deduplicated points themselves rather than
    raising — a mark is never worth an exception.
    """
    pts = sorted(set((float(p[0]), float(p[1])) for p in points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    hull = lower[:-1] + upper[:-1]
    # All-collinear input collapses the chains; fall back to the extremes.
    return hull if len(hull) >= 3 else pts


def total_turning(points):
    """Total absolute direction change along the path, in degrees.

    A closed loop turns about 360 degrees; a straight line turns ~0; a
    half-circle swipe turns ~180. This is what separates "went round
    something" from "swept past it", and it is the reason the loop test does
    not use enclosed area (see :func:`is_closed`).
    """
    pts = dedupe_consecutive(points)
    if len(pts) < 3:
        return 0.0
    total = 0.0
    for i in range(1, len(pts) - 1):
        ax = pts[i][0] - pts[i - 1][0]
        ay = pts[i][1] - pts[i - 1][1]
        bx = pts[i + 1][0] - pts[i][0]
        by = pts[i + 1][1] - pts[i][1]
        la = math.hypot(ax, ay)
        lb = math.hypot(bx, by)
        if la <= 1e-9 or lb <= 1e-9:
            continue
        cos_a = max(-1.0, min(1.0, (ax * bx + ay * by) / (la * lb)))
        total += math.degrees(math.acos(cos_a))
    return total


def is_closed(points, gap_factor=CLOSE_GAP_FACTOR, turn_degrees=CLOSE_TURN_DEG):
    """Whether the stroke reads as a loop.

    Two independent tests, either of which is enough:

    1. **Endpoint gap** — the ends are within *gap_factor* of the bbox
       diagonal. The ordinary case, and the threshold is loose because
       circling something on screen routinely leaves a fifth of the diameter
       open.
    2. **Total turning** — the pen went at least *turn_degrees* around.
       Catches the spiral that overshoots its start point and so fails test 1
       despite plainly being a loop.

    Enclosed-area-versus-hull was the first thing tried for test 2 and is
    WRONG: joining the endpoints of any convex open arc encloses essentially
    all of that arc's hull, so a 130-degree swipe scored ~1.0 and read as a
    closed loop. Turning measures how far the pen actually travelled around,
    which is the property that makes a loop a loop.
    """
    if len(points) < 3:
        return False
    diag = bbox_diagonal(points)
    if diag <= 1e-9:
        return False

    gap = math.hypot(
        points[0][0] - points[-1][0],
        points[0][1] - points[-1][1],
    )
    if gap <= diag * gap_factor:
        return True

    return total_turning(points) >= turn_degrees


def tangent_at_end(points, span):
    """Unit direction the stroke is travelling when it ends, or None.

    Measured across the final *span* fraction of the point list rather than
    the last two samples, so one wobbly sample cannot swing the heading of an
    arrow by ninety degrees.
    """
    n = len(points)
    if n < 2:
        return None
    back = max(1, int(round(n * max(0.0, min(1.0, span)))))
    start = points[max(0, n - 1 - back)]
    end = points[-1]
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return None
    return (dx / length, dy / length)


def max_turn_in_tail(points, tail_fraction):
    """Sharpest direction change (degrees) within the final *tail_fraction*.

    Returns ``(angle_deg, index)`` for the sharpest turn, where *index* points
    into the ORIGINAL *points* list, or ``(0.0, -1)`` when the tail is too
    short to have one. Used to spot an arrowhead drawn without lifting the pen.
    """
    # Deduplicated first: a stroke assembled from two segments that share an
    # endpoint has a zero-length step exactly AT the corner, and a naive scan
    # skips that step and reports no turn at all — the arrowhead vanishes.
    # Original indices are carried along so the caller still gets an index it
    # can slice its own list with.
    pts, origin_index = _dedupe_with_indices(points)
    n = len(pts)
    if n < 5:
        return 0.0, -1
    first = max(1, int(n * (1.0 - max(0.0, min(1.0, tail_fraction)))))
    best_angle = 0.0
    best_index = -1
    for i in range(first, n - 1):
        ax = pts[i][0] - pts[i - 1][0]
        ay = pts[i][1] - pts[i - 1][1]
        bx = pts[i + 1][0] - pts[i][0]
        by = pts[i + 1][1] - pts[i][1]
        la = math.hypot(ax, ay)
        lb = math.hypot(bx, by)
        if la <= 1e-9 or lb <= 1e-9:
            continue
        cos_a = max(-1.0, min(1.0, (ax * bx + ay * by) / (la * lb)))
        angle = math.degrees(math.acos(cos_a))
        if angle > best_angle:
            best_angle = angle
            best_index = origin_index[i]
    return best_angle, best_index


def point_in_polygon(x, y, polygon):
    """Even-odd containment test. Points exactly on an edge are unspecified.

    Only ever used to decide whether to spend a raycast on a grid sample, so
    an ambiguous boundary sample costs at most one wasted ray.
    """
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        if (yi > y) != (yj > y):
            denom = yj - yi
            if abs(denom) > 1e-12 and x < xi + (y - yi) * (xj - xi) / denom:
                inside = not inside
        j = i
    return inside


# =============================================================================
# Reduction and conversion
# =============================================================================

def _dedupe_with_indices(points, epsilon=1e-9):
    """``(points, original_indices)`` with consecutive duplicates removed."""
    out = []
    indices = []
    for i, p in enumerate(points):
        if out:
            last = out[-1]
            if math.hypot(p[0] - last[0], p[1] - last[1]) <= epsilon:
                continue
        out.append(p)
        indices.append(i)
    return out, indices


def dedupe_consecutive(points, epsilon=1e-9):
    """Drop consecutive duplicate samples.

    A zero-length step carries no direction, so any angle measured across one
    is undefined — and silently skipping it (rather than removing it) makes a
    genuine corner disappear. Live capture rarely produces exact duplicates
    thanks to the minimum sample distance, but synthesized and replayed
    strokes do, and the angle helpers must not depend on their caller.
    """
    return _dedupe_with_indices(points, epsilon)[0]


def decimate(points, max_points):
    """Uniformly subsample to at most *max_points*, always keeping both ends.

    Uniform rather than Douglas-Peucker on purpose: the agent needs a
    recognisable shape, not a faithful trace, and uniform spacing keeps the
    same helper honest for both a smooth loop and a jagged one. Matches the
    decimation the sketch pipeline already uses, so two features cannot
    disagree about what "32 points" means.
    """
    n = len(points)
    if max_points < 2:
        max_points = 2
    if n <= max_points:
        return list(points)
    step = (n - 1) / (max_points - 1)
    indices = sorted({int(round(i * step)) for i in range(max_points)})
    return [points[i] for i in indices]


def to_normalized(points, width, height, decimals=UV_DECIMALS):
    """Region pixels → ``(u, v)`` in 0..1, clamped, rounded.

    No y flip: region coordinates are already bottom-up, which is the
    convention the payload declares and the backend localizer expects.
    Raises ValueError on a non-positive region, because a zero-width region
    means the caller resolved the wrong area and every coordinate after this
    point would be silently meaningless.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"Region must be positive, got {width}x{height}")
    out = []
    for p in points:
        u = min(1.0, max(0.0, float(p[0]) / float(width)))
        v = min(1.0, max(0.0, float(p[1]) / float(height)))
        out.append([round(u, decimals), round(v, decimals)])
    return out


def normalized_bbox(points, width, height, decimals=UV_DECIMALS):
    """``[u0, v0, u1, v1]`` of *points* in normalized coordinates.

    Returns the full frame for an empty input rather than None: a mark with no
    usable points still has to serialize, and "the whole view" is the honest
    reading of a bbox nobody constrained.
    """
    normalized = to_normalized(points, width, height, decimals)
    if not normalized:
        return [0.0, 0.0, 1.0, 1.0]
    us = [p[0] for p in normalized]
    vs = [p[1] for p in normalized]
    return [
        round(min(us), decimals),
        round(min(vs), decimals),
        round(max(us), decimals),
        round(max(vs), decimals),
    ]
