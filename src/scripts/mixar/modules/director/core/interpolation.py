# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Keyframe interpolation for a shot's camera curves.

Blender decides a key's interpolation per keyframe point, from the user
preference at insert time. Director gives a SHOT a default
(``shot.interpolation``) and lets any keyframe override it
(``beat.interpolation``, which rests on ``SHOT``). A keyframe's interpolation
governs the segment FROM it TO the next one, so an override on the earlier
beat of a pair is exactly "the easing between these two keyframes" — one span
can ease while the rest of the take holds constant.

Picking a type re-interpolates the keys the shot itself owns, and every
capture afterwards re-applies it. Handles are untouched — Bezier keys keep
the continuity-filtered handles the capture path gave them.
"""

from ..constants import BEAT_INTERPOLATION_DEFAULT
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


def beat_interpolation(shot, beat) -> str:
    """The type *beat* actually eases with: its own, else the shot's.

    ``SHOT`` is not a Blender interpolation — it is the beat saying it has no
    opinion — so it never reaches a keyframe point.
    """
    own = getattr(beat, "interpolation", BEAT_INTERPOLATION_DEFAULT)
    if not own or own == BEAT_INTERPOLATION_DEFAULT:
        return getattr(shot, "interpolation", "") or ""
    return own


def interpolation_by_frame(shot, frame=None) -> dict[int, str]:
    """``{frame: interpolation}`` for every key this shot owns.

    ``frame`` names a key inserted for the beat being captured right now,
    which is not on ``shot.beats`` yet — it takes the shot's default, which
    is what a beat rests on anyway.
    """
    default = getattr(shot, "interpolation", "") or ""
    plan = {}
    for beat in getattr(shot, "beats", ()):
        resolved = beat_interpolation(shot, beat)
        if resolved:
            plan[int(beat.frame)] = resolved
    if frame is not None and default:
        plan.setdefault(int(frame), default)
    return plan


def apply_interpolation(shot, frame=None) -> int:
    """Write each of the shot's keys to the type its own beat resolves to.

    ``frame`` names a key inserted for the beat being captured right now,
    which is not on ``shot.beats`` yet.

    Returns how many points changed. Safe to call with no camera or no
    animation yet: it is a no-op then.
    """
    camera = getattr(shot, "camera", None)
    if camera is None:
        return 0
    plan = interpolation_by_frame(shot, frame)
    if not plan:
        return 0
    changed = 0
    touched = []
    for fcurve, point in camera_keyframe_points(camera, plan.keys()):
        # The scan matches within `_FRAME_EPSILON`, so the plan is looked up
        # on the rounded frame rather than the raw float the point carries.
        value = plan.get(round(float(point.co[0])))
        if value is None or point.interpolation == value:
            continue
        point.interpolation = value
        changed += 1
        if fcurve not in touched:
            touched.append(fcurve)
    for fcurve in touched:
        update = getattr(fcurve, "update", None)
        if callable(update):
            update()
    return changed
