# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Handheld camera texture as F-curve noise modifiers.

Sparse keyframes cannot represent jitter — noise between two captured
poses would compress to a straight line — so handheld lives as named
noise modifiers on the shot camera's transform F-curves instead. The
captured keys stay clean (keys store raw values; noise applies at
evaluation), while everything that reads the EVALUATED camera carries the
texture: viewport preview, Beauty/Clay/Depth guide videos, and the
manifest's sampled poses. Blender's default noise modification mode is a
centered additive wiggle around the curve, exactly the drift wanted here.
"""

from __future__ import annotations

HANDHELD_MODIFIER_NAME = "Mixar Handheld"

_LOCATION_AMPLITUDE = 0.04  # metres of drift at full intensity
_ROTATION_AMPLITUDE = 0.02  # radians (~1.1°) of tremor at full intensity
_LOCATION_PERIOD = 30.0  # frames per noise feature: slow positional drift
_ROTATION_PERIOD = 18.0  # slightly faster angular tremor

_TRANSFORM_PATHS = {
    "location",
    "rotation_euler",
    "rotation_quaternion",
    "rotation_axis_angle",
}


def _transform_fcurves(camera):
    animation = getattr(camera, "animation_data", None)
    action = getattr(animation, "action", None)
    if action is None:
        return ()
    return tuple(
        fcurve for fcurve in action.fcurves if fcurve.data_path in _TRANSFORM_PATHS
    )


def remove_handheld(camera) -> None:
    """Strip exactly the modifiers this module added, nothing else."""
    if camera is None:
        return
    for fcurve in _transform_fcurves(camera):
        stale = [
            modifier
            for modifier in fcurve.modifiers
            if modifier.name == HANDHELD_MODIFIER_NAME
        ]
        for modifier in stale:
            fcurve.modifiers.remove(modifier)


def refresh_handheld(shot) -> None:
    """Apply, retune, or strip the shot's handheld noise. Idempotent.

    Must run again after captures: the first capture is what creates the
    transform F-curves a modifier can attach to.
    """
    camera = getattr(shot, "camera", None)
    if camera is None:
        return
    remove_handheld(camera)
    if not getattr(shot, "handheld", False):
        return
    strength = float(getattr(shot, "handheld_strength", 0.5))
    for index, fcurve in enumerate(_transform_fcurves(camera)):
        is_rotation = fcurve.data_path != "location"
        modifier = fcurve.modifiers.new(type='NOISE')
        modifier.name = HANDHELD_MODIFIER_NAME
        modifier.scale = _ROTATION_PERIOD if is_rotation else _LOCATION_PERIOD
        modifier.strength = strength * (
            _ROTATION_AMPLITUDE if is_rotation else _LOCATION_AMPLITUDE
        )
        # A unique phase per channel keeps the axes from moving in lockstep,
        # which is what makes the drift read as a human hand.
        modifier.phase = float(index * 17 + fcurve.array_index * 5 + 1)
