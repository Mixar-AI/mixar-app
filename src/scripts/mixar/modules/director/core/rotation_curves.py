# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Keep Director rotation keys on one continuous representation.

Every rotation mode Blender offers stores a pose in more than one way, and
``Object.matrix_world = ...`` picks a representation without looking at the
previous key (``rna_Object_matrix_world_update`` decomposes with
``use_compat=false``):

* Euler triples come back on whichever of the two branches has the smaller
  summed magnitude, clamped around +/-180 degrees — two nearby poses key as
  (for example) +180 and -135 degrees, or on opposite half-turn branches.
* Quaternions are canonicalised to ``w >= 0``: a camera yawing from +170 to
  -170 degrees keys as ``q`` and (nearly) ``-q``.
* Axis-angle keeps the angle in ``[0, pi]`` and flips the axis instead.

Blender interpolates each F-curve channel independently, so any of these
sends the camera the long way round between otherwise-correct keys.
Director preserves the camera's native rotation mode and instead rewrites
each chronological key to the equivalent representation nearest its
predecessor.  Keyed poses stay identical.  A key moved by an offset takes
its Bezier handles along; a key negated (quaternion sign, axis-angle axis)
mirrors its handles, so hand-shaped tangents keep their meaning.  Blender
still owns recalculation of automatic handles for the now-continuous curve.

Pure math, no ``bpy``: the filter runs on raw F-curve keyframe data.
"""

from __future__ import annotations

import math

from .anim_curves import assigned_fcurves


_EULER_MODES = {'XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX'}
_CHANNEL_COUNTS = {
    "rotation_euler": 3,
    "rotation_quaternion": 4,
    "rotation_axis_angle": 4,
}
_FRAME_EPSILON = 1.0e-4
_VALUE_EPSILON = 1.0e-7
_TWO_PI = 2.0 * math.pi
_KEEP3 = (1.0, 1.0, 1.0)
_KEEP4 = (1.0, 1.0, 1.0, 1.0)
_MIRROR4 = (-1.0, -1.0, -1.0, -1.0)


def rotation_data_path(obj) -> str:
    """The F-curve data path that stores *obj*'s native rotation."""
    mode = str(getattr(obj, "rotation_mode", ""))
    if mode == 'QUATERNION':
        return "rotation_quaternion"
    if mode == 'AXIS_ANGLE':
        return "rotation_axis_angle"
    return "rotation_euler"


def _rotation_curves(obj, data_path: str):
    """Every channel of *data_path* as one ordered tuple, or fail closed."""
    count = _CHANNEL_COUNTS[data_path]
    curves = {}
    for fcurve in assigned_fcurves(obj):
        if fcurve.data_path != data_path:
            continue
        index = int(fcurve.array_index)
        if 0 <= index < count and index not in curves:
            curves[index] = fcurve
    if len(curves) != count:
        return None
    return tuple(curves[index] for index in range(count))


def _aligned_key_rows(curves) -> tuple:
    """Return chronological point rows, or fail closed if keys differ."""
    points_by_axis = [
        sorted(fcurve.keyframe_points, key=lambda point: float(point.co[0]))
        for fcurve in curves
    ]
    lengths = {len(points) for points in points_by_axis}
    if len(lengths) != 1 or not lengths or next(iter(lengths)) < 2:
        return ()

    rows = []
    for row in zip(*points_by_axis, strict=True):
        frames = [float(point.co[0]) for point in row]
        if max(frames) - min(frames) > _FRAME_EPSILON:
            return ()
        rows.append(row)
    return tuple(rows)


def _nearest_turn(value: float, reference: float) -> float:
    return value + round((reference - value) / _TWO_PI) * _TWO_PI


def _flipped_branch(values, order: str) -> tuple[float, ...]:
    """The alternate Euler decomposition of the same rotation.

    Every Tait-Bryan triple has exactly one other representation: the
    order's middle axis takes the supplement while both outer axes shift by
    a half turn.  Matrix assignment (``Object.matrix_world = ...``) stores
    whichever of the two branches the decomposition happened to pick.
    """
    middle = "XYZ".index(order[1])
    return tuple(
        math.pi - value if axis == middle else value + math.pi
        for axis, value in enumerate(values)
    )


def _compatible_euler_values(values, previous, order: str) -> tuple[float, ...]:
    """Represent *values* on the Euler branch nearest *previous*.

    Mirrors Blender's own compatible decomposition: both candidate branches
    are corrected by whole turns toward *previous* and the closer one (by
    summed per-axis distance) wins.  Euler.make_compatible() is not enough
    here — it only removes whole-turn jumps and leaves half-turn branch
    flips in place.  Pure +/-pi arithmetic keeps ties exact: an
    already-continuous key keeps its raw values bit for bit, so a repaired
    curve never appears dirty on the next pass.
    """

    def _aligned(candidate):
        aligned = tuple(
            _nearest_turn(value, reference)
            for value, reference in zip(candidate, previous)
        )
        distance = sum(
            abs(value - reference)
            for value, reference in zip(aligned, previous)
        )
        return aligned, distance

    raw, raw_distance = _aligned(tuple(float(value) for value in values))
    flipped, flipped_distance = _aligned(_flipped_branch(values, order))
    if flipped_distance < raw_distance:
        return flipped
    return raw


def _euler_compatibility(order: str):
    def _compatible(values, previous):
        return _compatible_euler_values(values, previous, order), _KEEP3

    return _compatible


def _compatible_quaternion_values(values, previous):
    """``q`` and ``-q`` are one rotation; keep the hemisphere of *previous*.

    Per-channel interpolation between opposite-sign keys passes through the
    zero quaternion (renormalised: the identity), i.e. rotates away and back
    the long way.  A non-negative dot product keeps the arc short.
    """
    dot = sum(value * reference for value, reference in zip(values, previous))
    if dot < 0.0:
        return tuple(-value for value in values), _MIRROR4
    return tuple(float(value) for value in values), _KEEP4


def _compatible_axis_angle_values(values, previous):
    """Axis-angle ``(angle, x, y, z)`` nearest *previous*.

    ``(theta, axis)`` equals ``(-theta, -axis)`` and any whole turn of the
    angle.  Opposing axes are mirrored first (a lerp between them crosses
    the zero axis, the identity), then the angle is carried to the turn
    nearest the previous key so 170 -> 190 degrees never plays as
    170 -> -170.
    """
    angle = float(values[0])
    axis = tuple(float(value) for value in values[1:])
    signs = _KEEP4
    aligned = sum(value * reference for value, reference in zip(axis, previous[1:]))
    if aligned < 0.0:
        angle = -angle
        axis = tuple(-value for value in axis)
        signs = _MIRROR4
    return (_nearest_turn(angle, float(previous[0])), *axis), signs


def _move_point(point, value: float, sign: float) -> bool:
    """Write *value*, carrying handles along (offset) or mirrored (sign<0)."""
    current = float(point.co[1])
    left = value + sign * (float(point.handle_left[1]) - current)
    right = value + sign * (float(point.handle_right[1]) - current)
    if (
        abs(value - current) <= _VALUE_EPSILON
        and abs(left - float(point.handle_left[1])) <= _VALUE_EPSILON
        and abs(right - float(point.handle_right[1])) <= _VALUE_EPSILON
    ):
        return False
    point.co[1] = value
    point.handle_left[1] = left
    point.handle_right[1] = right
    return True


def _repair_rows(rows, compatible) -> int:
    previous = tuple(float(point.co[1]) for point in rows[0])
    changed_rows = 0
    for row in rows[1:]:
        raw = tuple(float(point.co[1]) for point in row)
        values, signs = compatible(raw, previous)
        changed = False
        for point, value, sign in zip(row, values, signs, strict=True):
            changed = _move_point(point, value, sign) or changed
        if changed:
            changed_rows += 1
        previous = values
    return changed_rows


def repair_rotation_continuity(obj) -> int:
    """Remove equivalent-representation flips from *obj*'s rotation keys.

    Dispatches on the object's native rotation mode and returns the number
    of chronological key rows changed.  Incomplete or mismatched channel
    sets are left untouched: Director keys every channel of the rotation
    together, while partial curves may belong to an artist-authored setup
    whose intent cannot be inferred safely.
    """
    mode = str(getattr(obj, "rotation_mode", ""))
    if mode in _EULER_MODES:
        compatible = _euler_compatibility(mode)
    elif mode == 'QUATERNION':
        compatible = _compatible_quaternion_values
    elif mode == 'AXIS_ANGLE':
        compatible = _compatible_axis_angle_values
    else:
        return 0
    curves = _rotation_curves(obj, rotation_data_path(obj))
    if curves is None:
        return 0
    rows = _aligned_key_rows(curves)
    if not rows:
        return 0

    changed_rows = _repair_rows(rows, compatible)
    if changed_rows:
        for fcurve in curves:
            fcurve.update()
    return changed_rows
