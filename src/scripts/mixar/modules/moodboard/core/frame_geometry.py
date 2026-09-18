# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Frame geometry and membership rules -- deliberately ``bpy``-free.

Every decision a frame makes about space lives here, over plain tuples, so it
is unit-tested directly rather than through the ``bpy`` mock (the same reason
``node_layout.py`` is split this way). ``core/frames.py`` is the thin RNA
adapter on top.

The membership rule is ONE rule: an item belongs to the **smallest** frame
whose rect contains the item's **centre point**. Centre, not "at least half the
area", because a user can predict where the centre of a thing is; and smallest,
so a frame nested visually inside another claims what is dropped in it.
"""

from __future__ import annotations

from mixar.modules.moodboard.constants import (
    FRAME_MIN_HEIGHT,
    FRAME_MIN_WIDTH,
    FRAME_PALETTE,
    FRAME_PALETTE_SIZE,
    FRAME_SELECTION_PADDING,
)


def palette_color(index: int) -> tuple[float, float, float]:
    """The pastel at *index*, wrapped into the palette."""
    if FRAME_PALETTE_SIZE == 0:  # pragma: no cover - palette is never empty
        return (0.65, 0.77, 0.94)
    return FRAME_PALETTE[int(index) % FRAME_PALETTE_SIZE][1]


def next_palette_index(existing_count: int) -> int:
    """Palette slot for the next frame.

    Cycled rather than random: a random pick repeats a neighbour's colour about
    one time in ``FRAME_PALETTE_SIZE`` and cannot be reproduced in a test, while
    cycling guarantees the next N frames are all different.
    """
    if FRAME_PALETTE_SIZE == 0:  # pragma: no cover
        return 0
    return int(existing_count) % FRAME_PALETTE_SIZE


def clamp_size(width: float, height: float) -> tuple[float, float]:
    """Never below the floors -- a frame must never invert or be crushed."""
    return (max(float(width), FRAME_MIN_WIDTH), max(float(height), FRAME_MIN_HEIGHT))


def rect_of(x: float, y: float, width: float, height: float) -> tuple[float, float, float, float]:
    """``(left, bottom, right, top)`` from a bottom-left origin plus a size."""
    return (float(x), float(y), float(x) + float(width), float(y) + float(height))


def rect_area(rect: tuple[float, float, float, float]) -> float:
    return max(rect[2] - rect[0], 0.0) * max(rect[3] - rect[1], 0.0)


def rect_contains(rect: tuple[float, float, float, float], x: float, y: float) -> bool:
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def rect_center(rect: tuple[float, float, float, float]) -> tuple[float, float]:
    return ((rect[0] + rect[2]) * 0.5, (rect[1] + rect[3]) * 0.5)


def rects_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> bool:
    """Do the two rects share any area? (Touching edges do not count.)"""
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def grow_rect_to_contain(
    rect: tuple[float, float, float, float],
    contents: list[tuple[float, float, float, float]],
    padding: float = FRAME_SELECTION_PADDING,
) -> tuple[float, float, float, float] | None:
    """*rect* stretched outwards until it contains *contents* plus *padding*.

    GROW-ONLY, which is what makes it safe to run after every item drag: it is
    idempotent (a second call moves nothing), and it can never shrink a frame
    the user deliberately sized larger than its contents. Returns ``None`` when
    the rect already contains everything, so a caller can skip the RNA write.
    """
    if not contents:
        return None
    left = min([rect[0]] + [r[0] - padding for r in contents])
    bottom = min([rect[1]] + [r[1] - padding for r in contents])
    right = max([rect[2]] + [r[2] + padding for r in contents])
    top = max([rect[3]] + [r[3] + padding for r in contents])
    grown = (left, bottom, right, top)
    return None if grown == tuple(rect) else grown


def bounds_of(
    rects: list[tuple[float, float, float, float]],
    padding: float = FRAME_SELECTION_PADDING,
) -> tuple[float, float, float, float] | None:
    """Union of *rects* grown by *padding*, or ``None`` when there are none."""
    if not rects:
        return None
    left = min(r[0] for r in rects)
    bottom = min(r[1] for r in rects)
    right = max(r[2] for r in rects)
    top = max(r[3] for r in rects)
    return (left - padding, bottom - padding, right + padding, top + padding)


def frame_for_point(
    frames: list[tuple[str, tuple[float, float, float, float]]],
    x: float,
    y: float,
) -> str:
    """Id of the smallest frame containing ``(x, y)``, or ``""``.

    *frames* is ``[(frame_id, rect), ...]``. Smallest-area wins so overlapping
    frames resolve deterministically and a frame drawn inside another one takes
    what is dropped into it -- the same tie-break the hit-test uses, which is
    why membership and clicking agree about which frame an area belongs to.
    """
    best_id = ""
    best_area = None
    for frame_id, rect in frames:
        if not frame_id or not rect_contains(rect, x, y):
            continue
        area = rect_area(rect)
        if best_area is None or area < best_area:
            best_area = area
            best_id = frame_id
    return best_id


def resolve_membership(
    frames: list[tuple[str, tuple[float, float, float, float]]],
    items: list[tuple[object, tuple[float, float, float, float]]],
) -> list[tuple[object, str]]:
    """``(item, frame_id)`` for every item whose membership should CHANGE.

    Only changes are returned, so a caller can skip writing RNA — and therefore
    skip pushing an undo step — when a drag did not move anything across a
    frame boundary.

    Membership is STICKY: a member stays in its CURRENT frame for as long as
    the two still overlap at all, even once its centre has left. A frame is a
    container the user put things in, so nudging a picture a little past the
    edge must stretch the frame (the caller then grows it), not evict the
    picture — an item leaves only by being dragged FULLY CLEAR. Landing
    centre-first inside ANOTHER frame is still a deliberate move and always
    wins over stickiness.

    Stickiness has no opt-out because nothing needs one: a frame has no manual
    resize, and shrinking the rect past a member was the only gesture that ever
    meant "release this one".
    """
    frame_rect_by_id = {frame_id: rect for frame_id, rect in frames if frame_id}
    changed = []
    for item, rect in items:
        center_x, center_y = rect_center(rect)
        resolved = frame_for_point(frames, center_x, center_y)
        current = getattr(item, "frame_id", "") or ""
        if (
            not resolved
            and current in frame_rect_by_id
            and rects_overlap(rect, frame_rect_by_id[current])
        ):
            resolved = current
        if resolved != current:
            changed.append((item, resolved))
    return changed


def unique_frame_name(existing: list[str], stem: str = "Frame") -> str:
    """``Frame 1``, ``Frame 2``, ... -- the first number not already taken.

    An auto name, because Ctrl+G creates the frame and drops straight into an
    inline rename: the user types over this, they are never asked for it.
    """
    taken = set(existing)
    index = 1
    while f"{stem} {index}" in taken:
        index += 1
    return f"{stem} {index}"
