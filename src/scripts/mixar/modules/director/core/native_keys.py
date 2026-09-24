# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The shot camera's own keyframes, edited the way the Dope Sheet edits them.

The dock draws every key the camera carries — a recorded take keys each frame
— one mark per COLUMN, the keys of every F-curve that share a frame
(`view3d_director_timeline_keys.cc`, Blender's own keylist). These are the
edits behind those marks.

Selection is Blender's own: the keys' select flags, the ones the Timeline and
the Dope Sheet read and write, so a key selected in one is selected in all
three. A column counts as selected when ANY key in it is, which is how the
keylist marks it (`BEZT_ISSEL_ANY`).

A beat is metadata ON a key column — its still, its timing, its manifest
pose. `core/key_drag.py` keeps beats on their keys while those move; this
module keeps them in step when keys are deleted.

Reads and writes go through ``foreach_get`` / ``foreach_set``: a recorded take
is a key per frame per channel, and a per-point attribute loop over a long
take is what made a Python selection feel like a stall.
"""

from __future__ import annotations

from bisect import bisect_left
from math import isfinite

from .anim_curves import action_fcurves, assigned_fcurves

#: Keys closer than this share a column — the keylist's own merge distance
#: (`BEZT_BINARYSEARCH_THRESH`), so a column here is exactly a column drawn.
COLUMN_EPSILON = 0.01
#: A beat's frame is an integer; the key under it is the one that rounds to it.
BEAT_EPSILON = 0.5

SELECT_MODES = ("SET", "EXTEND", "TOGGLE", "ALL", "NONE")

#: The Dope Sheet selects and deselects a key's handles with it.
_SELECT_FLAGS = ("select_control_point", "select_left_handle", "select_right_handle")


def camera_owners(camera) -> tuple:
    """The IDs whose keys the dock draws for *camera*: the object and its data.

    The same two `ob_to_keylist` gathers for an object row, so lens keys count
    alongside the transform.
    """
    if camera is None:
        return ()
    data = getattr(camera, "data", None)
    return (camera,) if data is None else (camera, data)


def camera_fcurves(camera) -> tuple:
    return tuple(
        fcurve for owner in camera_owners(camera) for fcurve in assigned_fcurves(owner)
    )


def parse_frames(text) -> list[float]:
    """Comma-separated frames from the dock, sorted, unique and finite.

    The string comes from the native timeline, but an operator is callable
    from anywhere, so anything that is not a frame is skipped.
    """
    frames = set()
    for part in str(text or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = float(part)
        except ValueError:
            continue
        if isfinite(value):
            frames.add(value)
    return sorted(frames)


def merge_columns(xs) -> list[float]:
    """Key times folded into columns the way the keylist folds them."""
    columns: list[float] = []
    for x in sorted(float(value) for value in xs):
        if columns and x - columns[-1] <= COLUMN_EPSILON:
            continue
        columns.append(x)
    return columns


def near(sorted_frames, x: float, epsilon: float = COLUMN_EPSILON) -> bool:
    """Whether *x* is within *epsilon* of any of *sorted_frames*."""
    index = bisect_left(sorted_frames, x - epsilon)
    return index < len(sorted_frames) and sorted_frames[index] <= x + epsilon


def key_times(points) -> list[float]:
    co = [0.0] * (2 * len(points))
    points.foreach_get("co", co)
    return co[0::2]


def selected_mask(points) -> list[bool]:
    count = len(points)
    mask = [False] * count
    for attribute in _SELECT_FLAGS:
        flags = [False] * count
        points.foreach_get(attribute, flags)
        mask = [a or bool(b) for a, b in zip(mask, flags)]
    return mask


def _write_selection(points, mask) -> None:
    values = [bool(value) for value in mask]
    for attribute in _SELECT_FLAGS:
        points.foreach_set(attribute, values)


def key_columns(camera) -> list[float]:
    """Every column the camera carries, in time order."""
    return merge_columns(
        x for fcurve in camera_fcurves(camera) for x in key_times(fcurve.keyframe_points)
    )


def selected_columns(camera) -> list[float]:
    """The columns carrying a selected key, in time order."""
    times = []
    for fcurve in camera_fcurves(camera):
        points = fcurve.keyframe_points
        if len(points):
            times.extend(
                x for x, sel in zip(key_times(points), selected_mask(points)) if sel
            )
    return merge_columns(times)


def has_selected_keys(camera) -> bool:
    return any(
        any(selected_mask(fcurve.keyframe_points))
        for fcurve in camera_fcurves(camera)
        if len(fcurve.keyframe_points)
    )


def column_selected(camera, frame: float) -> bool:
    return near(selected_columns(camera), float(frame))


def select_columns(camera, frames, mode: str) -> int:
    """Apply one dock selection gesture; returns the keys selected afterwards.

    ``SET`` makes *frames* the selection (the click, the box), ``EXTEND`` adds
    them (Shift+box), ``TOGGLE`` flips them as a group (Shift+click: a
    selected column deselects, any other selects), ``ALL`` / ``NONE`` are A
    and Alt+A. *frames* is ignored by the last two.
    """
    if mode not in SELECT_MODES:
        raise ValueError(f"Unknown selection mode {mode!r}")
    frames = sorted(float(frame) for frame in frames)
    deselect = False
    if mode == "TOGGLE":
        chosen = selected_columns(camera)
        deselect = bool(frames) and all(near(chosen, frame) for frame in frames)
    selected = 0
    for fcurve in camera_fcurves(camera):
        points = fcurve.keyframe_points
        count = len(points)
        if not count:
            continue
        if mode in ("ALL", "NONE"):
            mask = [mode == "ALL"] * count
        else:
            hit = [near(frames, x) for x in key_times(points)]
            if mode == "SET":
                mask = hit
            elif deselect:
                mask = [m and not h for m, h in zip(selected_mask(points), hit)]
            else:
                mask = [m or h for m, h in zip(selected_mask(points), hit)]
        _write_selection(points, mask)
        selected += sum(mask)
    return selected


def delete_keys(camera, frames=None) -> list[float]:
    """Delete the selected keys, or every key in *frames*' columns.

    Returns the columns that lost a key. An F-curve left with no keys is
    removed, as the Dope Sheet's delete removes it, so a fully cleared
    channel does not linger as an empty curve.
    """
    targets = None if frames is None else sorted(float(frame) for frame in frames)
    touched: list[float] = []
    for owner in camera_owners(camera):
        collection = action_fcurves(owner)
        for fcurve in assigned_fcurves(owner):
            points = fcurve.keyframe_points
            if not len(points):
                continue
            times = key_times(points)
            if targets is None:
                doomed = [i for i, sel in enumerate(selected_mask(points)) if sel]
            else:
                doomed = [i for i, x in enumerate(times) if near(targets, x)]
            if not doomed:
                continue
            touched.extend(times[i] for i in doomed)
            # Highest index first: each removal shifts everything after it.
            for index in reversed(doomed):
                points.remove(points[index], fast=True)
            if not len(points) and collection is not None:
                collection.remove(fcurve)
            else:
                fcurve.update()
    return merge_columns(touched)


def camera_shots(scene, camera) -> list:
    """The draft shots directing *camera*.

    Takes and split shots deliberately share one camera timeline, so a key
    edit can move or orphan a beat of a shot other than the active one.
    """
    state = getattr(scene, "mixar_director", None)
    shots = getattr(state, "shots", ()) if state is not None else ()
    return [
        shot
        for shot in shots
        if getattr(shot, "camera", None) == camera
        and getattr(shot, "state", "DRAFT") == "DRAFT"
    ]


def beat_on_column(frame, columns) -> bool:
    return near(columns, float(frame), BEAT_EPSILON)


def drop_beats_without_keys(scene, camera) -> int:
    """Remove every beat whose key column is gone.

    Metadata only — the keys are already deleted, and a beat's own delete
    would go on to purge the camera once the last beat went, taking the
    recorded samples the director kept with it.
    """
    from .capture import remove_beat

    columns = key_columns(camera)
    removed = 0
    for shot in camera_shots(scene, camera):
        orphans = [
            index
            for index, beat in enumerate(shot.beats)
            if not beat_on_column(beat.frame, columns)
        ]
        for index in reversed(orphans):
            if remove_beat(scene, shot, index, delete_keys=False):
                removed += 1
    return removed


def beat_index_at(shot, frame: float) -> int:
    """The index of *shot*'s beat on the column at *frame*, or -1."""
    for index, beat in enumerate(getattr(shot, "beats", ())):
        if abs(float(beat.frame) - float(frame)) < BEAT_EPSILON:
            return index
    return -1
