# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stroke smoothing for the viewport ink overlay.

Pointer samples arrive at the event rate and are distance-decimated on
capture, so a fast stroke is a handful of points joined by straight
segments — every corner of the polyline shows. This turns a sampled stroke
into a Catmull-Rom spline through the SAME points (the ink still passes
through every sample the user made, nothing is moved or dropped) and emits
extra points along it for drawing. Draw-time only: what is stored, resolved
against the scene, and sent as a sketch is still the raw sample.

Pure Python, no ``bpy``: pinned by the standalone suite.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

Point = Sequence[float]

# Subdivisions per segment. Four is smooth at ink widths up to ~4 px; more
# only adds vertices the anti-aliased polyline shader cannot show.
DEFAULT_SUBDIVISIONS = 4

# Segments shorter than this (px) are already sub-pixel curves; splitting
# them further would only multiply the vertex count.
MIN_SEGMENT_PX = 2.5

# Hard cap on the emitted point count per stroke, whatever the input.
MAX_OUTPUT_POINTS = 4096


def catmull_rom(points: Sequence[Point],
                subdivisions: int = DEFAULT_SUBDIVISIONS,
                min_segment_px: float = MIN_SEGMENT_PX) -> List[Tuple[float, ...]]:
    """Return the stroke resampled along a centripetal-ish Catmull-Rom spline.

    Every input point is emitted (in order), with ``subdivisions - 1``
    interpolated points inserted between neighbours whose distance exceeds
    ``min_segment_px``. Components beyond x/y (pressure, time) are carried
    by linear interpolation. Fewer than three points come back unchanged.
    """
    pts = [tuple(float(c) for c in p) for p in points]
    n = len(pts)
    if n < 3 or subdivisions <= 1:
        return pts

    out: List[Tuple[float, ...]] = [pts[0]]
    steps = max(1, int(subdivisions))
    for i in range(n - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[i + 2] if i + 2 < n else pts[i + 1]

        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        if dx * dx + dy * dy < min_segment_px * min_segment_px:
            out.append(p2)
            if len(out) >= MAX_OUTPUT_POINTS:
                break
            continue

        for k in range(1, steps + 1):
            t = k / steps
            if k == steps:
                out.append(p2)
            else:
                out.append(_evaluate(p0, p1, p2, p3, t))
            if len(out) >= MAX_OUTPUT_POINTS:
                return out
    return out


def _evaluate(p0: Tuple[float, ...], p1: Tuple[float, ...],
              p2: Tuple[float, ...], p3: Tuple[float, ...], t: float) -> Tuple[float, ...]:
    """Uniform Catmull-Rom for x/y; linear for every further component."""
    t2 = t * t
    t3 = t2 * t
    x = 0.5 * ((2.0 * p1[0]) + (-p0[0] + p2[0]) * t
               + (2.0 * p0[0] - 5.0 * p1[0] + 4.0 * p2[0] - p3[0]) * t2
               + (-p0[0] + 3.0 * p1[0] - 3.0 * p2[0] + p3[0]) * t3)
    y = 0.5 * ((2.0 * p1[1]) + (-p0[1] + p2[1]) * t
               + (2.0 * p0[1] - 5.0 * p1[1] + 4.0 * p2[1] - p3[1]) * t2
               + (-p0[1] + 3.0 * p1[1] - 3.0 * p2[1] + p3[1]) * t3)
    rest = tuple(p1[c] + (p2[c] - p1[c]) * t for c in range(2, min(len(p1), len(p2))))
    return (x, y) + rest
