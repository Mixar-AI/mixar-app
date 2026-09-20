# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reading a freeze's ink as a SKETCH — pure, deterministic, no ``bpy``.

Marks are read one pen-up pause at a time, and for pointing that is right: an
arrow's shaft and head become one mark, a circle another. But a user who
draws a road with two cars and three trees on the side has not made nine
marks — they have made ONE drawing, and chopping it into per-pause marks sent
the agent nine "empty spots on the ground" and no picture at all. It built a
campfire.

So the ink of a whole freeze gets a second reading, above the marks: is this
a set of gestures that each mean *this* or *here*, or is it a picture of what
to build? The rule is deterministic, for the same reason gesture reading is:
asking a model what the squiggle meant is the guessing the feature exists to
remove. It is also **advisory**. Both representations travel — the marks with
their resolution, and the sketch block with every stroke's place in the world
— and the label says which the user meant. The reading is shown in the hint
pill and can be flipped, because a misread mode the user cannot see is the
first thing ink tools get wrong (arXiv:2607.21468).

Everything here works on the stored mark dicts: normalized ``strokes`` plus
the resolver's ``strokes_world``, so it runs identically inside Blender and
in the standalone test suite.
"""

from __future__ import annotations

from .geometry import bbox as points_bbox, bbox_diagonal, is_closed, path_length
from ..constants import (
    GESTURE_CIRCLE,
    GESTURE_STROKE,
    INTENT_POINT,
    INTENT_SKETCH,
    PLANE_GROUND,
    SKETCH_CANVAS_MIN_STROKES,
    SKETCH_DOODLE_STROKES,
    SKETCH_DRAWN_FRACTION,
    SKETCH_MAX_OBJECT_FRACTION,
    SKETCH_MAX_STROKES,
    SKETCH_MIN_OPEN_STROKES,
    SKETCH_MIN_STROKES,
    SKETCH_PROSE_STROKES,
    SKETCH_TAP_MAX_UV,
    SKETCH_WORLD_POINTS,
    UV_DECIMALS,
    WORLD_DECIMALS,
)

KIND_OPEN = "open"
KIND_CLOSED = "closed"
KIND_TAP = "tap"


# =============================================================================
# Reading
# =============================================================================

def stroke_kind(points):
    """``open`` (a line), ``closed`` (a loop) or ``tap`` for one stroke."""
    if len(points) < 2:
        return KIND_TAP
    if bbox_diagonal(points) <= SKETCH_TAP_MAX_UV:
        return KIND_TAP
    if is_closed(points):
        return KIND_CLOSED
    return KIND_OPEN


def mark_strokes(mark):
    return [list(s) for s in (mark.get("strokes") or []) if s]


def is_drawn(mark, total_strokes):
    """Whether one mark reads as DRAWING rather than pointing.

    Ink on nothing is a drawing or a layout, never a selection. An irregular
    line that fitted no gesture is drawing. Three or more strokes in one
    pause is a doodle — arrows are two, X's are two. And in a session of
    drawing size, a loop covering a sliver of a big object was drawn ON that
    surface (a car on the floor mesh), not around it.
    """
    resolved = mark.get("resolved") or {}
    if not resolved.get("hit"):
        return True
    if mark.get("gesture") == GESTURE_STROKE:
        return True
    if len(mark_strokes(mark)) >= SKETCH_DOODLE_STROKES:
        return True
    if (mark.get("gesture") == GESTURE_CIRCLE
            and total_strokes >= SKETCH_CANVAS_MIN_STROKES):
        objects = resolved.get("objects") or []
        fraction = objects[0].get("object_fraction") if objects else None
        if fraction is not None and fraction < SKETCH_MAX_OBJECT_FRACTION:
            return True
    return False


def read_intent(marks):
    """``(intent, stats)`` for the marks of one freeze.

    A sketch needs enough ink to be a picture (``SKETCH_MIN_STROKES``), enough
    of it drawn as open lines rather than circled spots
    (``SKETCH_MIN_OPEN_STROKES`` — a layout of three circles is three
    placement targets), and most of its marks reading as drawn rather than as
    pointing gestures on objects (``SKETCH_DRAWN_FRACTION``). Anything short
    of that is pointing, which is the reading every existing behaviour is
    built on.
    """
    strokes = [s for m in marks for s in mark_strokes(m)]
    kinds = [stroke_kind(s) for s in strokes]
    total = len(strokes)
    open_count = sum(1 for k in kinds if k == KIND_OPEN)
    drawn = sum(1 for m in marks if is_drawn(m, total))
    stats = {"strokes": total, "open": open_count, "marks": len(marks),
             "drawn": drawn}

    if total < SKETCH_MIN_STROKES or open_count < SKETCH_MIN_OPEN_STROKES:
        return INTENT_POINT, stats
    if marks and drawn / float(len(marks)) < SKETCH_DRAWN_FRACTION:
        return INTENT_POINT, stats
    return INTENT_SKETCH, stats


# =============================================================================
# The sketch block
# =============================================================================

def build_sketch(marks):
    """Every stroke of the freeze, in drawing order, with its place in the world.

    The drawing itself is carried by the annotated frame; this block is what
    anchors it — where each line sits on the ground so a road can be built
    where the road was drawn. The LONGEST strokes are kept under the cap:
    outlines and roads matter more than the dots that detail them.
    """
    entries = []
    for mark in marks:
        strokes = mark_strokes(mark)
        projected = (mark.get("resolved") or {}).get("strokes_world") or []
        for index, stroke in enumerate(strokes):
            world = projected[index] if index < len(projected) else {}
            if not isinstance(world, dict):
                world = {}
            box = points_bbox(stroke)
            entries.append({
                "mark": mark.get("id"),
                "kind": stroke_kind(stroke),
                "bbox": [round(float(c), UV_DECIMALS) for c in box] if box else None,
                "world": [
                    [round(float(c), WORLD_DECIMALS) for c in p]
                    for p in (world.get("points") or [])
                ][:SKETCH_WORLD_POINTS],
                "on": world.get("on"),
                "_order": len(entries),
                "_length": path_length(stroke),
            })

    total = len(entries)
    if total > SKETCH_MAX_STROKES:
        kept = sorted(entries, key=lambda e: e["_length"], reverse=True)
        kept = kept[:SKETCH_MAX_STROKES]
        entries = sorted(kept, key=lambda e: e["_order"])
    for entry in entries:
        del entry["_order"]
        del entry["_length"]

    all_uv = [p for m in marks for s in mark_strokes(m) for p in s]
    all_world = [p for e in entries for p in e["world"]]
    box = points_bbox(all_uv)

    return {
        "stroke_count": total,
        "strokes": entries,
        "bbox": [round(float(c), UV_DECIMALS) for c in box] if box else None,
        "world_bbox": world_extent(all_world),
        "surfaces": _surfaces(entries),
    }


def world_extent(points):
    """``{"center", "size"}`` of world points, or None when there are none."""
    if not points:
        return None
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    return {
        "center": [round((lo[i] + hi[i]) / 2.0, WORLD_DECIMALS) for i in range(3)],
        "size": [round(hi[i] - lo[i], WORLD_DECIMALS) for i in range(3)],
    }


def _surfaces(entries):
    """How many strokes landed on the ground, and on which objects."""
    ground = 0
    objects = {}
    for entry in entries:
        on = entry.get("on")
        if on == PLANE_GROUND:
            ground += 1
        elif on:
            objects[on] = objects.get(on, 0) + 1
    return {"ground": ground, "objects": objects}


# =============================================================================
# Prose
# =============================================================================

def describe_sketch(payload):
    """The client's own restatement of a sketch payload."""
    sketch = payload.get("sketch") or {}
    count = int(sketch.get("stroke_count") or 0)
    chosen = payload.get("intent_source") == "user"
    lines = [
        f"The user DREW A SKETCH over the frozen view ({count} stroke"
        f"{'' if count == 1 else 's'}, "
        f"{'a reading they chose' if chosen else 'read from the ink'}). "
        f"The annotated frame IS the drawing: build what it depicts, laid out "
        f"where it was drawn — not one object per mark."
    ]
    extent = sketch.get("world_bbox")
    if extent:
        size = extent.get("size") or [0, 0, 0]
        center = extent.get("center") or [0, 0, 0]
        lines.append(
            f"It spans about {size[0]:.1f} m by {size[1]:.1f} m of the ground "
            f"around world ({center[0]:g}, {center[1]:g}, {center[2]:g})."
        )
    strokes = sketch.get("strokes") or []
    named = []
    for index, stroke in enumerate(strokes[:SKETCH_PROSE_STROKES], 1):
        world = stroke.get("world") or []
        if len(world) >= 2:
            a, b = world[0], world[-1]
            named.append(
                f"stroke {index} ({stroke.get('kind')}) from ({a[0]:g}, {a[1]:g}) "
                f"to ({b[0]:g}, {b[1]:g})"
            )
        elif world:
            a = world[0]
            named.append(f"stroke {index} ({stroke.get('kind')}) at ({a[0]:g}, {a[1]:g})")
    if named:
        more = len(strokes) - len(named)
        lines.append("Ground paths: " + "; ".join(named)
                     + (f"; and {more} more." if more > 0 else "."))
    return " ".join(lines)
