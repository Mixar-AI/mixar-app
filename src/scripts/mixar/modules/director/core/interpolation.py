# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Keyframe interpolation for a shot's camera curves.

Blender decides a key's interpolation per keyframe point, from the user
preference at insert time. Director exposes it per SHOT instead
(``shot.interpolation``): picking a type re-interpolates the keys the shot
itself owns, and every capture afterwards re-applies it, so the whole take
always eases the same way. Handles are untouched — Bezier keys keep the
continuity-filtered handles the capture path gave them.
"""

from .anim_curves import assigned_fcurves

# The channels Director keys for a shot's camera: the motion on the object,
# the lens on its data. Anything else on those IDs is the user's.
_OBJECT_PATHS = {
    "location",
    "rotation_euler",
    "rotation_quaternion",
    "rotation_axis_angle",
}
_DATA_PATHS = {"lens"}
_FRAME_EPSILON = 1.0e-4


def camera_keyframe_points(camera, frames=None):
    """Director's keyframe points on the camera object and its camera data.

    Scoped to the paths Director keys, and — when ``frames`` is given — to
    those frames. Both halves are load-bearing: a hand-keyed DOF rack or
    ``shift_x`` on the same camera must keep the easing its author chose, and
    because a take is a second Shot sharing the one camera (and therefore its
    F-curves), an unscoped sweep would rewrite the neighbouring take's keys
    too. This is the same data-path + frame scan ``timeline._director_keyframes``
    does for retiming.
    """
    if camera is None:
        return
    for owner, data_paths in (
        (camera, _OBJECT_PATHS),
        (getattr(camera, "data", None), _DATA_PATHS),
    ):
        if owner is None:
            continue
        for fcurve in assigned_fcurves(owner):
            if fcurve.data_path not in data_paths:
                continue
            for point in fcurve.keyframe_points:
                if frames is not None and not any(
                    abs(float(point.co[0]) - frame) <= _FRAME_EPSILON for frame in frames
                ):
                    continue
                yield fcurve, point


def apply_interpolation(shot, frame=None) -> int:
    """Set the shot's own keys on its camera to ``shot.interpolation``.

    ``frame`` names a key inserted for the beat being captured right now,
    which is not on ``shot.beats`` yet.

    Returns how many points changed. Safe to call with no camera or no
    animation yet: it is a no-op then.
    """
    camera = getattr(shot, "camera", None)
    value = getattr(shot, "interpolation", None)
    if camera is None or not value:
        return 0
    frames = {int(beat.frame) for beat in getattr(shot, "beats", ())}
    if frame is not None:
        frames.add(int(frame))
    changed = 0
    touched = []
    for fcurve, point in camera_keyframe_points(camera, frames):
        if point.interpolation != value:
            point.interpolation = value
            changed += 1
            if fcurve not in touched:
                touched.append(fcurve)
    for fcurve in touched:
        update = getattr(fcurve, "update", None)
        if callable(update):
            update()
    return changed
