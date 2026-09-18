# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Canvas frames: the RNA side of grouping.

The geometry and the membership rule live in ``frame_geometry.py`` (``bpy``-
free, unit-tested directly). This module is the adapter: it reads and writes
``scene.mixie_moodboard_frames`` and the ``frame_id`` every member carries.

ONE definition of each of the four things a frame does, shared by every entry
point (the operators, the C++ drag end, the Python grab modal):

* :func:`create_frame` -- make one, auto-named and auto-coloured.
* :func:`resolve_membership` -- re-resolve who is inside which frame.
* :func:`frame_members` -- who is inside one.
* :func:`delete_frame` / :func:`ungroup_frame` -- take one away.
"""

from __future__ import annotations

import uuid

from mixar.config.logging_config import get_logger
from mixar.modules.moodboard.constants import (
    FRAME_DEFAULT_HEIGHT,
    FRAME_DEFAULT_WIDTH,
    FRAME_SELECTION_PADDING,
)
from .frame_geometry import (
    bounds_of,
    clamp_size,
    frame_for_point,
    grow_rect_to_contain,
    next_palette_index,
    rect_center,
    rect_of,
    resolve_membership as resolve_membership_pure,
    unique_frame_name,
)
from .moodboard_utils import get_moodboard_image_display_size

logger = get_logger(__name__)

# Every collection a frame can hold. Frames are not a picture feature: a
# reference, a note, an inference card and a 3D result all sit on one canvas
# and a frame that could only hold one of them was the single biggest thing
# wrong with the grouping this replaces. Mirrors the drag capture's table
# (`mixie_moodboard_move_selection.cc`) and the grab modal's
# `_GRAB_COLLECTIONS`, which move exactly the same four kinds.
FRAME_MEMBER_COLLECTIONS = (
    "mixie_moodboard_images",
    "mixie_moodboard_textboxes",
    "mixie_moodboard_action_nodes",
    "mixie_moodboard_asset_nodes",
)


def _frames(scene):
    return getattr(scene, "mixie_moodboard_frames", None)


def item_rect(item):
    """Canvas rect ``(left, bottom, right, top)`` of one board item, or None.

    Media carries a ``scale`` and an image aspect rather than a width and a
    height, so its size comes from the ONE definition every other surface uses
    (``get_moodboard_image_display_size``); text boxes and cards carry their
    size directly.
    """
    image = getattr(item, "image", None)
    if image is not None:
        width, height = get_moodboard_image_display_size(image, item.scale)
    else:
        width = getattr(item, "width", None)
        height = getattr(item, "height", None)
        if width is None or height is None:
            return None
    return rect_of(item.position_x, item.position_y, width, height)


def frame_rect(frame):
    return rect_of(frame.position_x, frame.position_y, frame.width, frame.height)


def frame_rects(scene) -> list[tuple[str, tuple[float, float, float, float]]]:
    """``(frame_id, rect)`` for every frame, for the membership resolver."""
    frames = _frames(scene)
    if not frames:
        return []
    return [(f.frame_id, frame_rect(f)) for f in frames if f.frame_id]


def frame_by_id(scene, frame_id: str):
    frames = _frames(scene)
    if not frames or not frame_id:
        return None
    for frame in frames:
        if frame.frame_id == frame_id:
            return frame
    return None


def frame_index(scene, frame_id: str) -> int:
    frames = _frames(scene)
    if not frames or not frame_id:
        return -1
    for index, frame in enumerate(frames):
        if frame.frame_id == frame_id:
            return index
    return -1


def board_items(scene):
    """Every framable item on the board, as ``(collection_name, item)``."""
    for name in FRAME_MEMBER_COLLECTIONS:
        collection = getattr(scene, name, None)
        if not collection:
            continue
        for item in collection:
            yield name, item


def _is_node_owned(item) -> bool:
    """Media drawn INSIDE an inference card. It has no independent position on
    the canvas, so it can neither be framed nor resolved into one."""
    return bool(getattr(item, "embedded_node_id", ""))


def frame_members(scene, frame_id: str) -> list:
    """Every item whose ``frame_id`` is *frame_id* (node-owned media excluded).

    The exclusion is not belt-and-braces. A generation result is placed on the
    board BEFORE ``connect_image_result`` marks it node-owned, so it can be
    stamped with a frame's id on the way in, and ``resolve_membership`` skips
    node-owned items -- it could never clear the stamp again. Filtering here
    makes membership agree with ``selected_items``/``create_frame``, so a
    card's own output is not counted, fitted around, or deleted with a frame.
    """
    if not frame_id:
        return []
    return [
        item
        for _name, item in board_items(scene)
        if getattr(item, "frame_id", "") == frame_id and not _is_node_owned(item)
    ]


def selected_items(scene) -> list:
    """Every directly selected framable item (node-owned media excluded)."""
    return [
        item
        for _name, item in board_items(scene)
        if item.selected and not _is_node_owned(item)
    ]


def selected_frames(scene) -> list:
    frames = _frames(scene)
    if not frames:
        return []
    return [frame for frame in frames if frame.selected]


def grow_frames_to_fit_members(scene, frame_ids=None) -> int:
    """Stretch every named frame until it contains its own members.

    GROW-ONLY, and therefore idempotent: a frame the user sized larger than its
    contents keeps that size, and a second call moves nothing. This is what
    makes a frame behave like a container -- dragging a member towards the edge
    takes the frame with it instead of orphaning the member. Distinct from
    :func:`fit_frame_to_members`, which is the explicit "Fit to Contents"
    action and also SHRINKS.

    Returns how many frames were grown.
    """
    grown = 0
    ids = None if frame_ids is None else {fid for fid in frame_ids if fid}
    for frame in getattr(scene, "mixie_moodboard_frames", []):
        frame_id = getattr(frame, "frame_id", "")
        if not frame_id or (ids is not None and frame_id not in ids):
            continue
        if getattr(frame, "collapsed", False):
            # A collapsed frame is just its title bar; growing a rect nobody
            # can see would silently change where it lands when reopened.
            continue
        rects = [item_rect(item) for item in frame_members(scene, frame_id)]
        rect = grow_rect_to_contain(
            frame_rect(frame),
            [r for r in rects if r is not None],
            FRAME_SELECTION_PADDING,
        )
        if rect is None:
            continue
        frame.position_x = rect[0]
        frame.position_y = rect[1]
        frame.width, frame.height = clamp_size(rect[2] - rect[0], rect[3] - rect[1])
        grown += 1
    return grown


def resolve_membership(scene, items=None) -> int:
    """Re-resolve which frame each item sits in. Returns the number of writes.

    Called at the END of a drag that moved ITEMS and when a frame is created --
    never when a frame is MOVED. A frame sweeping over the board and swallowing
    whatever it passed would be a surprise the user did not ask for; Figma does
    adopt on frame move and it catches people out constantly.

    Membership is STICKY and the frame GROWS to keep it: a member nudged past
    its frame's edge stays a member and the frame stretches to cover it, so a
    frame behaves like a container rather than a tripwire. Neither has an
    opt-out because nothing needs one -- a frame has no manual resize, and
    shrinking its rect past a member was the only gesture that ever meant
    "release this one". "Fit to Contents" still shrinks a frame to its members
    explicitly, which leaves every member inside and so grows nothing back.
    """
    frames = frame_rects(scene)
    if items is None:
        items = [item for _name, item in board_items(scene)]
    candidates = [
        (item, item_rect(item))
        for item in items
        if not _is_node_owned(item)
    ]
    candidates = [(item, rect) for item, rect in candidates if rect is not None]
    # Which frames the moved items belonged to BEFORE the resolve, so a frame
    # whose member merely shifted inside it is still grown to keep covering it.
    touched = {getattr(item, "frame_id", "") for item, _rect in candidates}
    changed = resolve_membership_pure(frames, candidates)
    for item, frame_id in changed:
        item.frame_id = frame_id
        touched.add(frame_id)
    grown = grow_frames_to_fit_members(scene, touched)
    # Both halves count: a drag that changed no membership but stretched a
    # frame still has to redraw, and callers gate their redraw on this.
    return len(changed) + grown


def frame_at_point(scene, x: float, y: float) -> str:
    """Id of the smallest frame containing the point -- the same rule
    membership uses, so clicking and containment can never disagree."""
    return frame_for_point(frame_rects(scene), x, y)


def create_frame(
    scene,
    *,
    from_items: list | None = None,
    position: tuple[float, float] | None = None,
    name: str = "",
):
    """Create one frame and return it.

    With items, the frame wraps their bounds plus
    ``FRAME_SELECTION_PADDING`` and adopts them. Without, it is an empty frame
    at *position* -- which is the whole point of a frame having its own rect:
    you can make the container first and drop into it afterwards.
    """
    frames = _frames(scene)
    if frames is None:
        logger.warning("Frames collection unavailable; cannot create a frame")
        return None

    rect = None
    if from_items:
        rects = [item_rect(item) for item in from_items if not _is_node_owned(item)]
        rect = bounds_of([r for r in rects if r is not None], FRAME_SELECTION_PADDING)
    if rect is None:
        center_x, center_y = position or (0.0, 0.0)
        rect = (
            center_x - FRAME_DEFAULT_WIDTH * 0.5,
            center_y - FRAME_DEFAULT_HEIGHT * 0.5,
            center_x + FRAME_DEFAULT_WIDTH * 0.5,
            center_y + FRAME_DEFAULT_HEIGHT * 0.5,
        )

    width, height = clamp_size(rect[2] - rect[0], rect[3] - rect[1])
    frame = frames.add()
    frame.frame_id = uuid.uuid4().hex
    frame.name = name or unique_frame_name([f.name for f in frames])
    frame.position_x = rect[0]
    frame.position_y = rect[1]
    frame.width = width
    frame.height = height
    # Cycled off the count BEFORE this one was appended, so the first frame
    # takes slot 0.
    frame.palette_index = next_palette_index(len(frames) - 1)

    if from_items:
        for item in from_items:
            if not _is_node_owned(item):
                item.frame_id = frame.frame_id
    return frame


def get_or_create_frame(scene, name: str):
    """The frame named *name*, created empty if it does not exist yet.

    For programmatic batches that want their results landing together (a
    generated set, an export). Named lookup rather than an id because the
    caller only knows the label it wants.
    """
    frames = _frames(scene)
    if frames is None or not name:
        return None
    for frame in frames:
        if frame.name == name:
            return frame
    return create_frame(scene, name=name)


def release_members(scene, frame_id: str) -> int:
    """Clear ``frame_id`` on every member. Returns how many were released."""
    released = 0
    for item in frame_members(scene, frame_id):
        item.frame_id = ""
        released += 1
    return released


def delete_frame(scene, frame_id: str) -> bool:
    """Remove one frame and RELEASE its members where they stand.

    Deleting a frame never deletes what is inside it. Figma deletes the
    children too, which here would mean one keypress silently destroying a
    board's references -- so "and its contents" is a separate, explicit menu
    item that runs the board's ordinary delete over the members first (see
    ``frame_ops.py``), keeping image lifecycle, link cleanup and in-flight job
    cancellation in the one place that already owns them.
    """
    frames = _frames(scene)
    index = frame_index(scene, frame_id)
    if frames is None or index < 0:
        return False
    release_members(scene, frame_id)
    frames.remove(index)
    return True


def ungroup_selection(scene) -> int:
    """Dissolve every selected frame, and the frame of every selected item.

    Returns the number of frames dissolved. Members are always released, never
    deleted -- Alt+G is "stop grouping these", not "delete these".
    """
    ids = {frame.frame_id for frame in selected_frames(scene) if frame.frame_id}
    for item in selected_items(scene):
        if getattr(item, "frame_id", ""):
            ids.add(item.frame_id)
    dissolved = 0
    for frame_id in ids:
        if delete_frame(scene, frame_id):
            dissolved += 1
    return dissolved


def select_frame(scene, frame_id: str, *, extend: bool = False) -> bool:
    """Make one frame the selection (or add it to it). False when unknown."""
    frame = frame_by_id(scene, frame_id)
    if frame is None:
        return False
    if not extend:
        deselect_all_frames(scene)
        _deselect_all_items(scene)
        frame.selected = True
    else:
        frame.selected = not frame.selected
    return True


def deselect_all_frames(scene) -> None:
    frames = _frames(scene)
    if not frames:
        return
    for frame in frames:
        if frame.selected:
            frame.selected = False


def _deselect_all_items(scene) -> None:
    for _name, item in board_items(scene):
        if item.selected:
            item.selected = False


def select_frame_contents(scene, frame_id: str) -> int:
    """Select every member of a frame (and drop the frame's own selection).

    "Select Contents" is the bridge out of frame-level editing into
    item-level editing, so leaving the frame itself selected would mean the
    next drag moved the frame AND its members' own recorded starts.
    """
    frame = frame_by_id(scene, frame_id)
    if frame is None:
        return 0
    frame.selected = False
    count = 0
    for item in frame_members(scene, frame_id):
        item.selected = True
        count += 1
    return count


def add_selection_to_frame(scene, frame_id: str) -> int:
    """Adopt every selected item into *frame_id*, wherever it sits.

    The explicit override on top of geometric membership: the user is telling
    us the grouping, so it is not re-derived from position afterwards. The
    frame grows to contain what it just adopted -- through the SAME grow as an
    item drag, padding included, so the next :func:`resolve_membership` finds
    nothing left to do rather than nudging the rect a second time.
    """
    if frame_by_id(scene, frame_id) is None:
        return 0
    items = [item for item in selected_items(scene)]
    if not items:
        return 0
    for item in items:
        item.frame_id = frame_id
    grow_frames_to_fit_members(scene, [frame_id])
    return len(items)


def fit_frame_to_members(scene, frame_id: str) -> bool:
    """Shrink or grow a frame to wrap its current members plus padding."""
    frame = frame_by_id(scene, frame_id)
    if frame is None:
        return False
    rects = [item_rect(item) for item in frame_members(scene, frame_id)]
    rect = bounds_of([r for r in rects if r is not None], FRAME_SELECTION_PADDING)
    if rect is None:
        return False
    frame.position_x = rect[0]
    frame.position_y = rect[1]
    frame.width, frame.height = clamp_size(rect[2] - rect[0], rect[3] - rect[1])
    return True


def migrate_legacy_groups(scene) -> int:
    """Turn a pre-frame board's ``group_index`` groups into real frames.

    Idempotent and one-way. The body lives in ``frame_migration`` (500-line
    rule); this stays the public entry point every caller already uses. The
    import is deferred so that module can import this one without a cycle.
    """
    from .frame_migration import migrate_legacy_groups as _migrate

    return _migrate(scene)


def frame_center(frame) -> tuple[float, float]:
    return rect_center(frame_rect(frame))
