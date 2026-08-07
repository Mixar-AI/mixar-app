# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Undo-friendly movement of a Director shot's native camera keys."""

from __future__ import annotations

from .anim_curves import assigned_fcurves as _assigned_fcurves
from .frame_math import clamp_frame_delta
from .shot_api import refresh_manifest


_CAMERA_PATHS = {
    "location",
    "rotation_euler",
    "rotation_quaternion",
    "rotation_axis_angle",
}
_FRAME_EPSILON = 1.0e-4


def _director_keyframes(animated_id, data_paths: set[str], frames: set[int]):
    matches = []
    curves = []
    for fcurve in _assigned_fcurves(animated_id):
        if fcurve.data_path not in data_paths:
            continue
        curve_matches = [
            point
            for point in fcurve.keyframe_points
            if any(abs(float(point.co[0]) - frame) <= _FRAME_EPSILON for frame in frames)
        ]
        if curve_matches:
            curves.append(fcurve)
            matches.extend(curve_matches)
    return curves, matches


def _restore_shift(
    scene,
    shot,
    beat_frames,
    point_positions,
    curves,
    scene_state,
    manifest_json,
) -> None:
    for beat, frame in zip(shot.beats, beat_frames, strict=True):
        beat.frame = frame
    for point, co_x, left_x, right_x in point_positions:
        point.co[0] = co_x
        point.handle_left[0] = left_x
        point.handle_right[0] = right_x
    for fcurve in curves:
        fcurve.update()
    scene.frame_end = scene_state[1]
    scene.frame_preview_start = scene_state[2]
    scene.frame_preview_end = scene_state[3]
    shot.manifest_json = manifest_json
    scene.frame_set(scene_state[0])


def move_single_beat(
    scene,
    shot,
    index: int,
    requested_delta: int,
    *,
    rebuild_manifest: bool = True,
) -> int:
    """Move one beat and its matching native camera keys by a delta.

    Unlike :func:`shift_camera_beats` (which slides the whole strip), this
    retimes a single keyframe. The beat is clamped to stay between its
    time-neighbours — two Director keys must never share a frame, since the
    native transform/lens keys are matched by frame value — and inside the
    scene range. Returns the delta actually applied.
    """
    if shot is None or shot.state != 'DRAFT':
        raise ValueError("Create a new take before moving a locked shot")
    if index < 0 or index >= len(shot.beats):
        return 0
    beat = shot.beats[index]
    old_frame = int(beat.frame)

    lower = int(scene.frame_start)
    upper = 1048574
    for other_index, other in enumerate(shot.beats):
        if other_index == index:
            continue
        other_frame = int(other.frame)
        if other_frame < old_frame:
            lower = max(lower, other_frame + 1)
        elif other_frame > old_frame:
            upper = min(upper, other_frame - 1)
    new_frame = min(max(old_frame + int(requested_delta), lower), upper)
    delta = new_frame - old_frame
    if delta == 0:
        return 0
    camera = shot.camera
    if camera is None or camera.type != 'CAMERA':
        raise ValueError("Choose a camera before moving its shot")

    object_curves, object_points = _director_keyframes(
        camera,
        _CAMERA_PATHS,
        {old_frame},
    )
    data_curves, data_points = _director_keyframes(
        camera.data,
        {"lens"},
        {old_frame},
    )
    curves = object_curves + data_curves
    points = object_points + data_points
    point_positions = [
        (
            point,
            float(point.co[0]),
            float(point.handle_left[0]),
            float(point.handle_right[0]),
        )
        for point in points
    ]
    manifest_json = shot.manifest_json
    original_frame_end = int(scene.frame_end)

    try:
        for point in points:
            point.co[0] += delta
            point.handle_left[0] += delta
            point.handle_right[0] += delta
        for fcurve in curves:
            fcurve.update()
        beat.frame = new_frame
        scene.frame_end = max(scene.frame_end, new_frame)
        if rebuild_manifest:
            refresh_manifest(scene, shot)
    except Exception:
        for point, co_x, left_x, right_x in point_positions:
            point.co[0] = co_x
            point.handle_left[0] = left_x
            point.handle_right[0] = right_x
        for fcurve in curves:
            fcurve.update()
        beat.frame = old_frame
        scene.frame_end = original_frame_end
        shot.manifest_json = manifest_json
        raise
    return delta


def shift_camera_beats(
    scene,
    shot,
    requested_delta: int,
    *,
    rebuild_manifest: bool = True,
) -> int:
    """Move all beat metadata and matching native keys by one shared delta."""
    if shot is None or shot.state != 'DRAFT':
        raise ValueError("Create a new take before moving a locked shot")
    beat_frames = [int(beat.frame) for beat in shot.beats]
    if not beat_frames:
        return 0

    delta = clamp_frame_delta(
        beat_frames,
        requested_delta,
        minimum_frame=scene.frame_start,
    )
    if delta == 0:
        return 0
    camera = shot.camera
    if camera is None or camera.type != 'CAMERA':
        raise ValueError("Choose a camera before moving its shot")

    frame_set = set(beat_frames)
    object_curves, object_points = _director_keyframes(
        camera,
        _CAMERA_PATHS,
        frame_set,
    )
    data_curves, data_points = _director_keyframes(
        camera.data,
        {"lens"},
        frame_set,
    )
    curves = object_curves + data_curves
    points = object_points + data_points
    point_positions = [
        (
            point,
            float(point.co[0]),
            float(point.handle_left[0]),
            float(point.handle_right[0]),
        )
        for point in points
    ]
    scene_state = (
        int(scene.frame_current),
        int(scene.frame_end),
        int(scene.frame_preview_start),
        int(scene.frame_preview_end),
    )
    manifest_json = shot.manifest_json
    old_first = min(beat_frames)
    old_last = max(beat_frames)

    try:
        for point in points:
            point.co[0] += delta
            point.handle_left[0] += delta
            point.handle_right[0] += delta
        for fcurve in curves:
            fcurve.update()
        for beat in shot.beats:
            beat.frame += delta

        new_first = old_first + delta
        new_last = old_last + delta
        if (
            scene.use_preview_range
            and scene.frame_preview_start == old_first
            and scene.frame_preview_end == old_last
        ):
            scene.frame_preview_start = new_first
            scene.frame_preview_end = new_last
        scene.frame_end = max(scene.frame_end, new_last)
        if old_first <= scene_state[0] <= old_last:
            scene.frame_set(scene_state[0] + delta)
        if rebuild_manifest:
            refresh_manifest(scene, shot)
    except Exception:
        _restore_shift(
            scene,
            shot,
            beat_frames,
            point_positions,
            curves,
            scene_state,
            manifest_json,
        )
        raise
    return delta
