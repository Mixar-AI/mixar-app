# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Spending a point budget on a drawn path.

``geometry.decimate`` subsamples uniformly, which is the honest reading of a
gesture POLYGON — a hull, where every vertex is already a corner. It is the
wrong reading of a drawn STROKE: a car outline keeps a point every Nth sample
and loses the corner between roof and windscreen, the one place it bends.

Two budgets, two rules, and the difference between them is the whole reason
this file exists:

- ``simplify_shape`` spends the budget on the shape and stops early when
  there is no more shape to describe. A straight run is two points, because
  that is all a straight run is. Right for anything the points already fully
  describe: the ink the annotated frame draws, a world path being thinned to
  fit a prompt budget.
- ``sample_shape`` spends the WHOLE budget. Right for choosing where to make
  a measurement the points do not yet contain — a raycast into the scene —
  because a road drawn straight across a hillside is two points of screen
  shape and a dozen of terrain, and no amount of looking at the screen path
  can tell you that.

Deviation is measured across every coordinate the points carry. Most callers
hand over screen samples, but the payload shedder hands over WORLD paths,
where a stroke drawn on a wall varies in x and z while y barely moves — and
an x/y-only metric reads that as a straight line and discards the shape.

Pure Python, no ``bpy``: pinned by the standalone suite.
"""

from __future__ import annotations

import math

#: Deviation below which a sample is ON the chord. Floating-point rejection
#: of a perfectly collinear run lands a few ulps off zero rather than at it,
#: so without a floor "no shape left" never fires and both budgets above
#: would always be spent in full — which is exactly the distinction this
#: file exists to draw. Far below a pixel, and below a micrometre in world
#: space, so nothing a hand drew is ever rounded away by it.
_MIN_DEVIATION = 1e-9


def _perpendicular_distance(point, start, end):
    """Distance from *point* to the line through ``start``-``end``.

    Measured across every coordinate the points carry, not just x/y. Most of
    the callers here are screen-space samples, but the payload shedder runs
    this over WORLD paths, where a stroke drawn on a wall varies in x and z
    while y barely moves — and an x/y-only metric reads that as a straight
    line and throws the whole shape away.

    Degenerate segments (both ends the same sample) fall back to the distance
    to that one point, so a stroke that doubles back on itself cannot make
    this divide by zero.
    """
    dimensions = min(len(point), len(start), len(end))
    if dimensions < 1:
        return 0.0
    segment = [float(end[i]) - float(start[i]) for i in range(dimensions)]
    relative = [float(point[i]) - float(start[i]) for i in range(dimensions)]
    span = sum(component * component for component in segment)
    if span <= 0.0:
        return math.sqrt(sum(component * component for component in relative))
    along = sum(relative[i] * segment[i] for i in range(dimensions)) / span
    return math.sqrt(
        sum((relative[i] - along * segment[i]) ** 2 for i in range(dimensions))
    )


def _worst_deviation(points, first, last):
    """``(index, distance)`` of the point in ``(first, last)`` furthest from
    the chord between them, or ``(-1, 0.0)`` when none is off it."""
    worst_index = -1
    worst = _MIN_DEVIATION
    start = points[first]
    end = points[last]
    for index in range(first + 1, last):
        distance = _perpendicular_distance(points[index], start, end)
        if distance > worst:
            worst = distance
            worst_index = index
    if worst_index < 0:
        return -1, 0.0
    return worst_index, worst


def _shape_indices(points, max_points):
    """Indices of at most *max_points* samples, chosen by deviation.

    Both ends, then repeatedly the sample furthest from the chord it spans,
    until the budget is spent or every remaining span is a straight line.
    """
    n = len(points)
    kept = {0, n - 1}
    # Segments still to consider: (deviation index, deviation, first, last).
    # Scanned linearly — the budget is a few dozen points, so a heap would
    # cost more in setup than it saves, and a linear scan keeps ties resolved
    # by position rather than by heap order (deterministic output).
    segments = [(*_worst_deviation(points, 0, n - 1), 0, n - 1)]

    while len(kept) < max_points:
        best = -1
        for entry in range(len(segments)):
            index, distance, _first, _last = segments[entry]
            if index < 0:
                continue
            if best < 0 or distance > segments[best][1]:
                best = entry
        if best < 0:
            break  # Every remaining span is a straight line: nothing to add.
        index, _distance, first, last = segments.pop(best)
        kept.add(index)
        if index - first > 1:
            segments.append((*_worst_deviation(points, first, index), first, index))
        if last - index > 1:
            segments.append((*_worst_deviation(points, index, last), index, last))
    return kept


def simplify_shape(points, max_points):
    """Reduce to at most *max_points*, keeping the points that carry the SHAPE.

    Douglas-Peucker driven by a point BUDGET rather than a tolerance: both
    ends are kept, then the sample furthest from the chord it spans is added
    repeatedly until the budget is spent. The corners a stroke turns on are
    exactly the samples with the largest deviation, so they survive; the
    samples a slow hand piled up along a straight run do not, because they
    add nothing the chord does not already say.

    This is what ``decimate`` cannot do. Uniform subsampling spends its budget
    evenly along the trace, so a drawn car keeps a point every Nth sample and
    loses the corner between roof and windscreen — the one place the outline
    actually bends. At the same 48 points this keeps the bends and drops the
    redundancy, which is what makes the shape still read as what was drawn.

    A straight run comes back as its two ends, UNDER the budget, because that
    is all a straight run is. That makes this the wrong tool for choosing
    where to spend a measurement the points do not yet contain — see
    ``sample_shape``. ``decimate`` remains the right tool for a gesture
    POLYGON (a hull, where every vertex is already a corner and even spacing
    is the honest reading).
    """
    n = len(points)
    if max_points < 2:
        max_points = 2
    if n <= max_points:
        return list(points)
    return [points[i] for i in sorted(_shape_indices(points, max_points))]


def sample_shape(points, max_points):
    """Exactly *max_points* samples (or all of them): shape first, then fill.

    For choosing where to spend a measurement the samples do not yet carry —
    a raycast into the scene. There, an unspent budget is information thrown
    away: a road drawn STRAIGHT across a hillside is two points of screen
    shape and a dozen of terrain, and ``simplify_shape`` cannot know that,
    because the thing that varies is not in the points it was given.

    So the deviation pass picks first (a stroke that does bend spends its
    budget on the bends), and whatever is left over is filled with evenly
    spaced samples the pass did not already take.
    """
    n = len(points)
    if max_points < 2:
        max_points = 2
    if n <= max_points:
        return list(points)

    kept = _shape_indices(points, max_points)
    if len(kept) < max_points:
        # Evenly spaced fill. Walked in order so the gaps close from the
        # start of the stroke rather than wherever a set happened to iterate.
        step = (n - 1) / (max_points - 1)
        for i in range(max_points):
            if len(kept) >= max_points:
                break
            kept.add(int(round(i * step)))
        index = 0
        while len(kept) < max_points and index < n:
            kept.add(index)
            index += 1
    return [points[i] for i in sorted(kept)]
