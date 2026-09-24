# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Director animation uses the shared assigned-slot F-curve helpers."""

from __future__ import annotations

from ..constants import RECORDED_KEY_TYPE
from ...common.utils.animation import action_fcurves, assigned_fcurves, remove_fcurves

__all__ = (
    "CAMERA_MOTION_PATHS",
    "action_fcurves",
    "assigned_fcurves",
    "camera_key_frames",
    "remove_fcurves",
)


# Transform channels that move a camera through the scene. Lens keys live on
# the camera DATA block and are gathered separately.
CAMERA_MOTION_PATHS = frozenset(
    {
        "location",
        "rotation_euler",
        "rotation_quaternion",
        "rotation_axis_angle",
    }
)


def camera_key_frames(camera, *, include_samples: bool = True) -> set[int]:
    """Every integer frame carrying a native camera transform or lens key.

    The ONE definition of "this camera is animated" — shared by the Director
    beat strip, which adopts these frames as beats, and by the camera-first
    Export to Moodboard surface, which has no beats to read and derives its
    render span from them directly. Beat adoption excludes dense recorded
    samples; their native key type survives file reloads, retimes and deletion.
    """
    frames: set[int] = set()
    if camera is None:
        return frames
    for fcurve in assigned_fcurves(camera):
        if fcurve.data_path in CAMERA_MOTION_PATHS:
            for point in fcurve.keyframe_points:
                if not include_samples and getattr(point, "type", None) == RECORDED_KEY_TYPE:
                    continue
                frames.add(round(float(point.co[0])))
    data = getattr(camera, "data", None)
    if data is not None:
        for fcurve in assigned_fcurves(data):
            if fcurve.data_path == "lens":
                for point in fcurve.keyframe_points:
                    if not include_samples and getattr(point, "type", None) == RECORDED_KEY_TYPE:
                        continue
                    frames.add(round(float(point.co[0])))
    return frames
