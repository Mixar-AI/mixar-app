# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hit-test and mutate canvas annotation strokes. bpy-free so tests exec it."""

import math


def point_segment_distance(px, py, ax, ay, bx, by):
    """Shortest distance from a point to a closed line segment."""
    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def stroke_hits(points, width, x, y, extra_radius=0.0):
    """True when (x, y) meets the stroke ribbon, including a one-point mark."""
    radius = max(float(width), 0.0) * 0.5 + max(float(extra_radius), 0.0)
    if not points:
        return False
    if len(points) == 1:
        return math.hypot(points[0][0] - x, points[0][1] - y) <= radius
    for index in range(len(points) - 1):
        ax, ay = points[index]
        bx, by = points[index + 1]
        if point_segment_distance(x, y, ax, ay, bx, by) <= radius:
            return True
    return False


def snapshot_strokes(strokes):
    return [
        {
            "points": [(point.x, point.y) for point in stroke.points],
            "color": tuple(stroke.color),
            "width": float(stroke.width),
        }
        for stroke in strokes
    ]


def restore_strokes(strokes, snapshots):
    strokes.clear()
    for snap in snapshots:
        stroke = strokes.add()
        stroke.color = snap["color"]
        stroke.width = snap["width"]
        for x, y in snap["points"]:
            point = stroke.points.add()
            point.x, point.y = x, y


def erase_hits(strokes, x, y, extra_radius=0.0):
    """Remove every stroke the eraser meets. Returns how many were removed."""
    removed = 0
    for index in range(len(strokes) - 1, -1, -1):
        stroke = strokes[index]
        points = [(point.x, point.y) for point in stroke.points]
        if stroke_hits(points, stroke.width, x, y, extra_radius):
            strokes.remove(index)
            removed += 1
    return removed
