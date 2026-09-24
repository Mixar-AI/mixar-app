# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Finding and restoring the native camera keys under a shot's beats.

The Speed retime (`core/retime.py`) moves each beat's own keys with it. The
dock's drags move keys through the camera's key selection instead
(`core/key_drag.py`), beats following their keys.
"""

from __future__ import annotations

from .anim_curves import assigned_fcurves as _assigned_fcurves
from .frame_math import write_preview_range


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
    write_preview_range(scene, scene_state[2], scene_state[3])
    scene.use_preview_range = scene_state[4]
    shot.manifest_json = manifest_json
    scene.frame_set(scene_state[0])
