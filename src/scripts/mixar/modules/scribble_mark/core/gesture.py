# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reading the shape of a mark — pure, deterministic, no ``bpy``.

People already share an annotation vocabulary: a loop means *this region*, an
arrow means *this, that way*, a tap means *this point*, a line through
something means *remove it*. Reading that here, with thresholds, is cheaper
and far more predictable than shipping the strokes to a model and asking what
the squiggle meant — which is exactly the guessing this whole feature exists
to delete.

**Classify, but never discard.** Every result carries the raw polygon
alongside the label, so an agent that thinks a "circle" was really an arrow
can look at the points and disagree. A misread gesture degrades the hint; it
never destroys the geometry.
"""

from .geometry import (
    bbox_diagonal,
    centroid,
    convex_hull,
    is_closed,
    max_turn_in_tail,
    path_length,
    polygon_area,
    straightness,
    tangent_at_end,
)
from ..constants import (
    ARROW_HEAD_MAX_RATIO,
    ARROW_HEAD_NEAR_FACTOR,
    ARROW_TANGENT_SPAN,
    ARROW_TURN_DEG,
    ARROW_TURN_TAIL,
    GESTURE_ARROW,
    GESTURE_CIRCLE,
    GESTURE_POINT,
    GESTURE_STRIKE,
    GESTURE_STROKE,
    POINT_MAX_DIAG_PX,
    POINT_MAX_PATH_PX,
    STRAIGHT_RATIO,
)

import math


def classify(strokes, scale=1.0):
    """Read *strokes* as one mark.

    Args:
        strokes: list of strokes, each a list of ``(x, y)`` region-pixel
            points. Empty and single-point strokes are tolerated.
        scale: UI scale factor. The two absolute thresholds (what counts as a
            tap) are expressed in unscaled pixels, so a HiDPI display would
            otherwise read every deliberate short drag as a tap.

    Returns:
        ``{"gesture", "anchor", "direction", "polygon", "closed"}``, or None
        when there is nothing to read. ``anchor`` is a region-pixel point,
        ``direction`` a unit vector or None, ``polygon`` the region-pixel
        outline the mark claims.
    """
    usable = [list(s) for s in strokes if s]
    if not usable:
        return None

    flat = [p for s in usable for p in s]
    if not flat:
        return None

    scale = scale if scale and scale > 0 else 1.0

    # Order matters: a tap is also technically "straight", and an arrow's
    # shaft is also technically "open", so the most specific reading wins.
    for reader in (_read_point, _read_arrow, _read_circle, _read_strike):
        result = reader(usable, flat, scale)
        if result is not None:
            return result

    return {
        "gesture": GESTURE_STROKE,
        "anchor": centroid(flat),
        "direction": None,
        "polygon": convex_hull(flat),
        "closed": False,
    }


# =============================================================================
# Readers, most specific first
# =============================================================================

def _read_point(strokes, flat, scale):
    """A tap: the hand did not meaningfully travel."""
    if len(strokes) != 1:
        return None
    stroke = strokes[0]
    if path_length(stroke) > POINT_MAX_PATH_PX * scale:
        return None
    if bbox_diagonal(stroke) > POINT_MAX_DIAG_PX * scale:
        return None
    return {
        "gesture": GESTURE_POINT,
        "anchor": centroid(stroke),
        "direction": None,
        # A tap has no meaningful outline; the resolver falls back to a small
        # box around the anchor rather than pretending a 3-pixel hull is a
        # region the user chose.
        "polygon": [],
        "closed": False,
    }


def _read_arrow(strokes, flat, scale):
    """An arrow, drawn either as shaft + separate head, or in one pen-down."""
    result = _arrow_two_stroke(strokes)
    if result is not None:
        return result
    return _arrow_single_stroke(strokes)


def _arrow_two_stroke(strokes):
    """Shaft plus a short head stroke landing near one of its endpoints."""
    if len(strokes) != 2:
        return None

    ordered = sorted(strokes, key=path_length, reverse=True)
    shaft, head = ordered[0], ordered[1]

    shaft_len = path_length(shaft)
    if shaft_len <= 1e-9 or len(shaft) < 2:
        return None
    if path_length(head) > shaft_len * ARROW_HEAD_MAX_RATIO:
        return None

    head_centre = centroid(head)
    if head_centre is None:
        return None

    diag = bbox_diagonal(shaft)
    if diag <= 1e-9:
        return None
    reach = diag * ARROW_HEAD_NEAR_FACTOR

    # Whichever end of the shaft the head sits on is the tip; the arrow points
    # away from the other end.
    start, end = shaft[0], shaft[-1]
    d_start = math.hypot(head_centre[0] - start[0], head_centre[1] - start[1])
    d_end = math.hypot(head_centre[0] - end[0], head_centre[1] - end[1])
    if min(d_start, d_end) > reach:
        return None

    if d_end <= d_start:
        tip, direction = end, tangent_at_end(shaft, ARROW_TANGENT_SPAN)
    else:
        tip, direction = start, tangent_at_end(list(reversed(shaft)), ARROW_TANGENT_SPAN)

    return {
        "gesture": GESTURE_ARROW,
        "anchor": tip,
        "direction": direction,
        "polygon": convex_hull([p for s in strokes for p in s]),
        "closed": False,
    }


def _arrow_single_stroke(strokes):
    """One unbroken stroke that doubles back sharply near its end."""
    if len(strokes) != 1:
        return None
    stroke = strokes[0]
    angle, index = max_turn_in_tail(stroke, ARROW_TURN_TAIL)
    if index < 0 or angle < ARROW_TURN_DEG:
        return None

    # A loop also turns sharply, and a loop is a circle, not an arrow.
    if is_closed(stroke):
        return None

    tip = stroke[index]
    direction = tangent_at_end(stroke[: index + 1], ARROW_TANGENT_SPAN)
    if direction is None:
        return None

    return {
        "gesture": GESTURE_ARROW,
        "anchor": tip,
        "direction": direction,
        "polygon": convex_hull(stroke),
        "closed": False,
    }


def _read_circle(strokes, flat, scale):
    """A loop. With several loops, the largest one is the mark."""
    closed = [s for s in strokes if is_closed(s)]
    if not closed:
        return None
    loop = max(closed, key=polygon_area)
    return {
        "gesture": GESTURE_CIRCLE,
        "anchor": centroid(loop),
        "direction": None,
        # The loop the user actually drew, not its hull — a concave selection
        # (around a handle, along a roofline) is information, and hulling it
        # would quietly widen what they asked for.
        "polygon": list(loop),
        "closed": True,
    }


def _read_strike(strokes, flat, scale):
    """A line through something, or an X across it — both mean 'this, gone'."""
    if len(strokes) > 2:
        return None
    if not all(straightness(s) >= STRAIGHT_RATIO for s in strokes if len(s) >= 2):
        return None
    if not any(len(s) >= 2 for s in strokes):
        return None
    return {
        "gesture": GESTURE_STRIKE,
        "anchor": centroid(flat),
        "direction": tangent_at_end(max(strokes, key=path_length), ARROW_TANGENT_SPAN),
        "polygon": convex_hull(flat),
        "closed": False,
    }
