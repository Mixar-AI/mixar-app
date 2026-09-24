# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Duplicate a shot's keyframes.

A director reaches for this constantly: return to a pose already framed, or
repeat a move a beat later. Re-flying the camera back to a pose by hand never
lands on it exactly, and the pose IS the shot.

Copies land AFTER the shot's last keyframe, keeping the spacing the selection
had, so a duplicate can never collide with a key that already exists — and two
Director keys sharing a frame would be unrecoverable, since the native
transform and lens keys are matched to beats BY FRAME VALUE and nothing else.

The camera keys are copied point to point rather than re-keyed from a pose:
re-keying would have to move the playhead, evaluate the rig and write whatever
came out, which loses the handles, the interpolation, and any constraint-free
value the curve actually holds.
"""

from __future__ import annotations

import uuid

from .anim_curves import assigned_fcurves
from .frame_math import frames_per_beat
from .retime import note_beat_timing
from .rotation_curves import repair_rotation_continuity
from .shot_api import refresh_manifest, release_preview_range

#: The channels a Director keyframe is made of, per owner.
_OBJECT_PATHS = {
    "location",
    "rotation_euler",
    "rotation_quaternion",
    "rotation_axis_angle",
}
_DATA_PATHS = {"lens"}
_FRAME_EPSILON = 1.0e-4


def _owners(camera):
    yield camera, _OBJECT_PATHS
    data = getattr(camera, "data", None)
    if data is not None:
        yield data, _DATA_PATHS


def _point_at(fcurve, frame: int):
    for point in fcurve.keyframe_points:
        if abs(float(point.co[0]) - float(frame)) <= _FRAME_EPSILON:
            return point
    return None


#: Copied verbatim from the source point onto its copy. Read BEFORE the
#: insert that invalidates the source (see `_copy_point`); a field a running
#: Blender does not have costs the copy that attribute, never the duplicate.
_POINT_ENUMS = ("interpolation", "handle_left_type", "handle_right_type", "easing")


def _copy_point(fcurve, source, target_frame: int) -> None:
    """Insert a copy of *source* at *target_frame* on the same curve.

    Everything is read off *source* FIRST. `keyframe_points.insert()` grows
    the curve's point array, and an RNA reference into that array is a
    pointer into the old allocation: reading the source after the insert is
    a use-after-free that happens to survive most of the time.
    """
    source_frame = float(source.co[0])
    source_value = float(source.co[1])
    enums = {name: getattr(source, name, None) for name in _POINT_ENUMS}
    # Handles carry the shape of the ease; copying the values without them
    # would silently flatten a Bezier the director spent time on.
    handles = {}
    for name in ("handle_left", "handle_right"):
        handle = getattr(source, name, None)
        if handle is not None:
            handles[name] = (float(handle[0]), float(handle[1]))

    inserted = fcurve.keyframe_points.insert(
        float(target_frame),
        source_value,
        options={'FAST'},
    )
    delta = float(target_frame) - source_frame
    for name, (handle_x, handle_y) in handles.items():
        target_handle = getattr(inserted, name, None)
        if target_handle is None:
            continue
        target_handle[0] = handle_x + delta
        target_handle[1] = handle_y
    for name, value in enums.items():
        if value is None:
            continue
        try:
            setattr(inserted, name, value)
        except (AttributeError, TypeError):
            pass


def copy_camera_keys(camera, moves: list[tuple[int, int]]) -> int:
    """Copy every Director key at each ``(source, target)`` frame pair.

    Returns how many points were written. ``FAST`` insertion skips the
    per-insert re-sort, so every touched curve is updated once at the end.
    """
    written = 0
    for owner, data_paths in _owners(camera):
        for fcurve in assigned_fcurves(owner):
            if fcurve.data_path not in data_paths:
                continue
            touched = False
            for source_frame, target_frame in moves:
                source = _point_at(fcurve, source_frame)
                if source is None:
                    continue
                _copy_point(fcurve, source, target_frame)
                written += 1
                touched = True
            if touched:
                fcurve.update()
    return written


def duplicate_plan(frames: list[int], last_frame: int, stride: int) -> list[tuple[int, int]]:
    """``(source, target)`` pairs placing *frames* after *last_frame*.

    The group keeps its own spacing and starts one *stride* past the shot's
    last keyframe, so the copies read as a repeat of the move rather than a
    pile of keys on one frame.
    """
    ordered = sorted({int(frame) for frame in frames})
    if not ordered:
        return []
    base = int(last_frame) + max(1, int(stride))
    first = ordered[0]
    return [(frame, base + (frame - first)) for frame in ordered]


def duplicate_beats(scene, shot, indices, beat_seconds: float) -> list:
    """Duplicate the beats at *indices*; returns the new beats.

    Raises ``ValueError`` for a locked take or a shot with no camera, which
    is what the operator reports.
    """
    if getattr(shot, "state", "DRAFT") != 'DRAFT':
        raise ValueError("Create a new take before editing a locked shot")
    camera = getattr(shot, "camera", None)
    if camera is None or getattr(camera, "type", None) != 'CAMERA':
        raise ValueError("This take has no camera to duplicate keyframes on")
    beats = list(shot.beats)
    sources = [beats[index] for index in sorted(set(indices)) if 0 <= index < len(beats)]
    if not sources:
        return []

    stride = frames_per_beat(beat_seconds, scene.render.fps, scene.render.fps_base)
    last_frame = max(int(beat.frame) for beat in beats)
    # The still and the easing are what the pose LOOKS like; the copy is the
    # same pose, so it carries both. The image DATABLOCK is shared, not
    # re-rendered — `remove_beat` already refuses to free a still another
    # beat still points at.
    #
    # Read off the sources now, as values. `shot.beats.add()` reallocates the
    # collection's backing array, so a beat reference taken before it points
    # into freed memory — the same rule `_ShotSnapshot` spells out for shots.
    by_frame = {
        int(beat.frame): (beat.image, beat.interpolation) for beat in sources
    }
    moves = duplicate_plan(list(by_frame), last_frame, stride)
    copy_camera_keys(camera, moves)

    created_indices = []
    for source_frame, target_frame in moves:
        image, interpolation = by_frame[source_frame]
        beat = shot.beats.add()
        # A fresh id: the copy is its own keyframe, and the manifest, the
        # strip and the Speed slider all identify beats by it.
        beat.beat_id = uuid.uuid4().hex
        beat.frame = target_frame
        note_beat_timing(shot, beat)
        beat.image = image
        beat.interpolation = interpolation
        created_indices.append(len(shot.beats) - 1)
    # Resolved after the last `add()`, for the same reason.
    created = [shot.beats[index] for index in created_indices]
    if created:
        shot.active_beat_index = len(shot.beats) - 1
        # Natively written points never met the continuity filter, and the
        # copies extend the chronological chain the filter walks.
        repair_rotation_continuity(camera)
        scene.frame_end = max(int(scene.frame_end), moves[-1][1])
        refresh_manifest(scene, shot)
        release_preview_range(scene)
    return created
