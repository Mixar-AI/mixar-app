# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turning raycast hits into "what did the user point at" — pure, no ``bpy``.

The raycast itself needs the depsgraph and lives in ``resolve``. Everything
around it — where to sample, how to rank what came back, and whether the mark
selected a whole object or part of one — is plain arithmetic, and lives here
so it can be tested against real numbers instead of a mock.

**Two different fractions, and conflating them is a real bug.** An agent acts
on these, so they are named apart:

* ``coverage`` — how much of *the mark* is this object. Sums to at most 1
  across the objects of one mark. Answers "is this mostly the house, or
  mostly the tree behind it?"
* ``object_fraction`` — how much of *the object* the mark covers. Independent
  per object. Answers "did they select the whole house or just its roof?",
  and is what sets ``partial``.

A mark that neatly circles a small chimney against a big house has a high
``coverage`` for the chimney and a high ``object_fraction`` too; a mark
scribbled over one wall of that house has high ``coverage`` and a LOW
``object_fraction`` — that difference is the whole reason a vertex group gets
written.
"""

from .geometry import bbox, point_in_polygon
from ..constants import (
    EMPTY_BACKGROUND,
    EMPTY_TOO_SMALL,
    MAX_OBJECTS_PER_MARK,
    MIN_HITS_FOR_COVERAGE,
    MIN_OBJECT_COVERAGE,
    PARTIAL_COVERAGE_MAX,
)


# =============================================================================
# Where to sample
# =============================================================================

def grid_samples(polygon, grid=8, anchor=None):
    """Points inside *polygon* on a *grid* x *grid* lattice over its bbox.

    Ordered row-major so a caller that has to truncate still covers the whole
    shape rather than only its bottom edge.

    A polygon too thin or too small to catch any lattice point (a tight
    circle at a low grid resolution, a strike-through) returns just the
    anchor when one is given — one honest sample beats reporting that the
    user pointed at nothing.
    """
    box = bbox(polygon) if polygon else None
    if box is None:
        return [anchor] if anchor else []

    min_x, min_y, max_x, max_y = box
    width = max_x - min_x
    height = max_y - min_y
    grid = max(1, int(grid))

    samples = []
    for row in range(grid):
        for col in range(grid):
            # Cell centres, so a sample never lands exactly on the polygon
            # boundary where containment is undefined.
            x = min_x + width * (col + 0.5) / grid
            y = min_y + height * (row + 0.5) / grid
            if len(polygon) >= 3:
                if point_in_polygon(x, y, polygon):
                    samples.append((x, y))
            else:
                samples.append((x, y))

    if not samples and anchor:
        return [anchor]
    return samples


# =============================================================================
# What came back
# =============================================================================

def tally_hits(hits):
    """``(counts, hit_total, miss_total)`` from a list of hit object names.

    *hits* entries are an object name, or None where the ray hit nothing.
    """
    counts = {}
    misses = 0
    for name in hits:
        if not name:
            misses += 1
            continue
        counts[name] = counts.get(name, 0) + 1
    return counts, sum(counts.values()), misses


def rank_objects(counts, hit_total, object_fractions=None,
                 max_objects=MAX_OBJECTS_PER_MARK,
                 min_coverage=MIN_OBJECT_COVERAGE):
    """Objects the mark landed on, most-covered first.

    Args:
        counts: ``{object_name: sample_count}`` from :func:`tally_hits`.
        hit_total: total samples that hit anything.
        object_fractions: optional ``{object_name: 0..1}`` — how much of each
            object's own on-screen extent the mark covers. Drives ``partial``.
            An object missing from this map is reported with
            ``object_fraction: None`` and ``partial: True``, because "we could
            not measure it" must never read as "the user selected all of it".

    Ties break on name so the ordering is stable across runs — an agent
    re-reading marks between turns should not see the dominant object swap.
    """
    if hit_total <= 0:
        return []

    fractions = object_fractions or {}
    ranked = []
    for name, count in counts.items():
        coverage = count / float(hit_total)
        if coverage < min_coverage:
            continue
        fraction = fractions.get(name)
        ranked.append({
            "name": name,
            "coverage": round(coverage, 4),
            "object_fraction": (
                round(float(fraction), 4) if fraction is not None else None
            ),
            "partial": (
                True if fraction is None else float(fraction) < PARTIAL_COVERAGE_MAX
            ),
            "samples": count,
        })

    ranked.sort(key=lambda o: (-o["coverage"], o["name"]))
    return ranked[:max_objects]


def resolve_status(hit_total, miss_total, sample_total):
    """``(hit, empty_reason)`` for the mark as a whole.

    Three genuinely different outcomes, kept apart because an agent can act
    on each: the mark landed on geometry; the mark landed on background; or
    the mark was too small to sample reliably and we will not pretend the one
    ray that did land is an answer.
    """
    if sample_total <= 0:
        return False, EMPTY_TOO_SMALL
    if hit_total <= 0:
        return False, EMPTY_BACKGROUND
    if hit_total < MIN_HITS_FOR_COVERAGE and miss_total > hit_total:
        return False, EMPTY_TOO_SMALL
    return True, None


# =============================================================================
# How much of the object
# =============================================================================

def rect_overlap_fraction(inner, outer):
    """Fraction of *inner*'s area that lies inside *outer*.

    Both are ``(min_x, min_y, max_x, max_y)``. Used with the object's
    projected screen bbox as *inner* and the mark's bbox as *outer*, giving a
    cheap, honest estimate of how much of an object the user enclosed.

    A zero-area *inner* (an object seen exactly edge-on, or a single
    projected point) returns 1.0 when its point is inside *outer* — an object
    with no measurable extent is either fully in or fully out.
    """
    ix0, iy0, ix1, iy1 = inner
    ox0, oy0, ox1, oy1 = outer

    inner_area = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)

    ox = max(0.0, min(ix1, ox1) - max(ix0, ox0))
    oy = max(0.0, min(iy1, oy1) - max(iy0, oy0))

    if inner_area <= 1e-12:
        inside = (ox0 <= ix0 <= ox1) and (oy0 <= iy0 <= oy1)
        return 1.0 if inside else 0.0

    return min(1.0, (ox * oy) / inner_area)


def points_in_polygon_mask(xs, ys, polygon):
    """Vectorized even-odd containment for many points at once.

    The scalar :func:`~.geometry.point_in_polygon` is fine for the few hundred
    grid samples of a raycast, but the vertex-group pass tests every vertex of
    a mesh — hundreds of thousands of them against up to 32 edges — and a
    Python loop there stalls the UI for seconds.

    Returns a boolean numpy array, or None when numpy is unavailable or the
    polygon is degenerate, so callers can fall back rather than fail.
    """
    try:
        import numpy as np
    except ImportError:  # pragma: no cover — numpy ships with Blender
        return None

    if len(polygon) < 3:
        return None

    px = np.asarray([float(p[0]) for p in polygon])
    py = np.asarray([float(p[1]) for p in polygon])
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)

    inside = np.zeros(xs.shape, dtype=bool)
    j = len(polygon) - 1
    for i in range(len(polygon)):
        yi, yj = py[i], py[j]
        xi, xj = px[i], px[j]
        straddles = (yi > ys) != (yj > ys)
        denom = yj - yi
        if abs(denom) > 1e-12:
            crossing = xi + (ys - yi) * (xj - xi) / denom
            inside ^= straddles & (xs < crossing)
        j = i
    return inside


def screen_bbox(points):
    """``(min_x, min_y, max_x, max_y)`` of projected points, or None.

    Callers pass the object's eight world bounding-box corners already
    projected into region space; entries that failed to project (behind the
    camera) are dropped rather than clamped, which would drag the box across
    the frame and make a distant object look enormous.
    """
    usable = [p for p in points if p is not None]
    return bbox(usable)
