# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Keyframe interpolation for a shot's camera curves.

Blender decides a key's interpolation per keyframe point, from the user
preference at insert time. Director exposes it per SHOT instead
(``shot.interpolation``): picking a type re-interpolates every key the shot
camera already has, and every capture afterwards re-applies it, so the whole
take always eases the same way. Handles are untouched — Bezier keys keep the
continuity-filtered handles the capture path gave them.
"""

from .anim_curves import assigned_fcurves


def camera_keyframe_points(camera):
    """Every keyframe point on the camera object and its camera data."""
    if camera is None:
        return
    for owner in (camera, getattr(camera, "data", None)):
        if owner is None:
            continue
        for fcurve in assigned_fcurves(owner):
            for point in fcurve.keyframe_points:
                yield fcurve, point


def apply_interpolation(shot) -> int:
    """Set every key of the shot camera to ``shot.interpolation``.

    Returns how many points changed. Safe to call with no camera or no
    animation yet: it is a no-op then.
    """
    camera = getattr(shot, "camera", None)
    value = getattr(shot, "interpolation", None)
    if camera is None or not value:
        return 0
    changed = 0
    touched = []
    for fcurve, point in camera_keyframe_points(camera):
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
