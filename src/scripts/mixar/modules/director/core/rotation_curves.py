# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Keep Director Euler keys on one continuous rotation branch.

Blender stores an XYZ camera pose with many equivalent Euler triples.  Matrix
assignment commonly clamps those values around +/-180 degrees, so two nearby
poses can be keyed as (for example) +180 and -135 degrees.  Independent
F-curves then interpolate the 315-degree long way around and point the camera
away from the subject between otherwise-correct keys.

Director preserves the camera's native rotation mode.  For Euler cameras this
module rewrites each chronological key to the equivalent representation nearest
its predecessor, moving both Bezier handles by the same delta.  Keyed poses and
manually shaped handle offsets stay identical; Blender still owns recalculation
of automatic handles for the now-continuous curve.
"""

from __future__ import annotations

from .anim_curves import assigned_fcurves


_EULER_MODES = {'XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX'}
_FRAME_EPSILON = 1.0e-4
_VALUE_EPSILON = 1.0e-7


def _euler_curve_triplet(camera):
    curves = {}
    for fcurve in assigned_fcurves(camera):
        if fcurve.data_path != "rotation_euler":
            continue
        axis = int(fcurve.array_index)
        if axis in {0, 1, 2} and axis not in curves:
            curves[axis] = fcurve
    if len(curves) != 3:
        return None
    return tuple(curves[axis] for axis in range(3))


def _aligned_key_rows(curves) -> tuple:
    """Return chronological XYZ point rows, or fail closed if keys differ."""
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


def _compatible_euler_values(values, previous, order: str) -> tuple[float, ...]:
    """Represent *values* on the Euler branch nearest *previous*."""
    from mathutils import Euler

    raw = Euler(values, order)
    reference = Euler(previous, order)
    # Avoid a matrix round-trip here.  Euler.make_compatible() performs the
    # same branch selection without introducing enough floating-point drift to
    # make an already-repaired curve appear dirty on the next preview.
    raw.make_compatible(reference)
    return tuple(float(value) for value in raw)


def _move_point_value(point, value: float) -> bool:
    current = float(point.co[1])
    delta = float(value) - current
    if abs(delta) <= _VALUE_EPSILON:
        return False
    point.co[1] = value
    point.handle_left[1] += delta
    point.handle_right[1] += delta
    return True


def repair_euler_rotation_continuity(camera) -> int:
    """Remove equivalent-angle flips from a camera's native Euler F-curves.

    Returns the number of chronological key rows changed.  Incomplete or
    mismatched curve triplets are left untouched: Director captures all three
    axes together, while partial curves may belong to an artist-authored setup
    whose intent cannot be inferred safely.
    """
    order = str(getattr(camera, "rotation_mode", ""))
    if order not in _EULER_MODES:
        return 0
    curves = _euler_curve_triplet(camera)
    if curves is None:
        return 0
    rows = _aligned_key_rows(curves)
    if not rows:
        return 0

    previous = tuple(float(point.co[1]) for point in rows[0])
    changed_rows = 0
    for row in rows[1:]:
        raw = tuple(float(point.co[1]) for point in row)
        compatible = _compatible_euler_values(raw, previous, order)
        changed = False
        for point, value in zip(row, compatible, strict=True):
            changed = _move_point_value(point, value) or changed
        if changed:
            changed_rows += 1
        previous = compatible

    if changed_rows:
        for fcurve in curves:
            fcurve.update()
    return changed_rows
