# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Slotted-action-safe F-curve access for Director's camera animation.

Blender 5 stores animation in layered actions with per-slot channelbags
and no longer exposes the legacy ``Action.fcurves`` collection. Every
Director read or removal of camera F-curves goes through these helpers,
which resolve the assigned slot's channelbag and fall back to the legacy
collection only for actions loaded from older files.
"""

from __future__ import annotations


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


def _fcurve_collection(animated_id):
    """The editable F-curve collection driving *animated_id*, or ``None``."""
    animation_data = getattr(animated_id, "animation_data", None)
    action = getattr(animation_data, "action", None)
    if action is None:
        return None
    try:
        from bpy_extras.anim_utils import (
            animdata_get_channelbag_for_assigned_slot,
        )

        channelbag = animdata_get_channelbag_for_assigned_slot(animation_data)
    except (AttributeError, ImportError, RuntimeError):
        channelbag = None
    if channelbag is not None:
        return channelbag.fcurves
    # Compatibility for legacy actions opened from older Blender versions.
    return getattr(action, "fcurves", None)


def assigned_fcurves(animated_id) -> tuple:
    """All F-curves currently driving *animated_id*."""
    collection = _fcurve_collection(animated_id)
    return tuple(collection) if collection is not None else ()


def remove_fcurves(animated_id, data_paths) -> int:
    """Delete every F-curve of *animated_id* whose path is in *data_paths*."""
    collection = _fcurve_collection(animated_id)
    if collection is None:
        return 0
    stale = [fcurve for fcurve in collection if fcurve.data_path in data_paths]
    for fcurve in stale:
        collection.remove(fcurve)
    return len(stale)


def camera_key_frames(camera) -> set[int]:
    """Every integer frame carrying a native camera transform or lens key.

    The ONE definition of "this camera is animated" — shared by the Director
    beat strip, which adopts these frames as beats, and by the camera-first
    Export to Moodboard surface, which has no beats to read and derives its
    render span from them directly.
    """
    frames: set[int] = set()
    if camera is None:
        return frames
    for fcurve in assigned_fcurves(camera):
        if fcurve.data_path in CAMERA_MOTION_PATHS:
            for point in fcurve.keyframe_points:
                frames.add(round(float(point.co[0])))
    data = getattr(camera, "data", None)
    if data is not None:
        for fcurve in assigned_fcurves(data):
            if fcurve.data_path == "lens":
                for point in fcurve.keyframe_points:
                    frames.add(round(float(point.co[0])))
    return frames
