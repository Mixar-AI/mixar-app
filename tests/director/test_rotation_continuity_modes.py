# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Long-way rotation regressions beyond the Euler branch filter.

Blender's ``matrix_world`` setter decomposes without compatibility
(``rna_Object_matrix_world_update`` passes ``use_compat=false``): Euler keys
land on whichever branch has the smaller summed magnitude, quaternions are
canonicalised to ``w >= 0``, and axis-angle keys get the angle in ``[0, pi]``
with the axis flipped instead. Each of these can put two nearly identical
poses on opposite representations, and Blender's per-channel F-curve
interpolation then rotates the camera the long way round.
"""

import math
from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.director.core import beat_sync, rotation_curves  # noqa: E402


class _Point:
    def __init__(self, frame, value, *, left_offset=-0.25, right_offset=0.5):
        self.co = [float(frame), float(value)]
        self.handle_left = [float(frame) - 1.0, float(value) + left_offset]
        self.handle_right = [float(frame) + 1.0, float(value) + right_offset]


class _Curve:
    def __init__(self, data_path, axis, values, frames=(1, 25)):
        self.data_path = data_path
        self.array_index = axis
        self.keyframe_points = [
            _Point(frame, value) for frame, value in zip(frames, values, strict=True)
        ]
        self.update_count = 0

    def update(self):
        self.update_count += 1


def _curves(data_path, rows, frames=(1, 25)):
    return [
        _Curve(data_path, axis, tuple(row[axis] for row in rows), frames)
        for axis in range(len(rows[0]))
    ]


def _object(curves, mode):
    return SimpleNamespace(
        rotation_mode=mode,
        animation_data=SimpleNamespace(action=object()),
        _test_curves=curves,
    )


def _install_fakes(monkeypatch):
    monkeypatch.setattr(
        rotation_curves,
        "assigned_fcurves",
        lambda obj: tuple(obj._test_curves),
    )


def _rows(curves):
    count = len(curves[0].keyframe_points)
    return [
        tuple(curve.keyframe_points[index].co[1] for curve in curves)
        for index in range(count)
    ]


# --- quaternion helpers (W, X, Y, Z) --------------------------------------


def _quat_mul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    )


def _normalized(values):
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return tuple(value / norm for value in values)


def _quat_angle(a, b):
    dot = abs(sum(x * y for x, y in zip(a, b, strict=True)))
    return 2.0 * math.acos(min(1.0, dot))


def _camera_quat(yaw_degrees):
    """A horizontal camera (X = 90 deg) yawed about world Z, canonical w >= 0.

    Exactly what ``mat3_normalized_to_quat`` stores for a matrix-assigned
    pose: the sign is chosen per key, never relative to the previous key.
    """
    half_yaw = math.radians(yaw_degrees) / 2.0
    tilt = (math.cos(math.pi / 4), math.sin(math.pi / 4), 0.0, 0.0)
    yaw = (math.cos(half_yaw), 0.0, 0.0, math.sin(half_yaw))
    quat = _quat_mul(yaw, tilt)
    return quat if quat[0] >= 0.0 else tuple(-value for value in quat)


def _quat_lerp_path(a, b, samples=24):
    """Rotation travelled by Blender's per-channel lerp + normalise."""
    total = 0.0
    previous = a
    for step in range(1, samples + 1):
        t = step / samples
        current = _normalized(
            tuple(x + (y - x) * t for x, y in zip(a, b, strict=True))
        )
        total += _quat_angle(previous, current)
        previous = current
    return total


def test_quaternion_keys_are_sign_aligned_to_the_previous_key(monkeypatch):
    """A 20-degree yaw keyed as q and ~-q must not spin 340 degrees."""
    _install_fakes(monkeypatch)
    first = _camera_quat(170.0)
    second = _camera_quat(-170.0)
    # Both canonical keys have w >= 0 yet point to opposite hemispheres.
    assert first[0] > 0 and second[0] > 0
    assert sum(x * y for x, y in zip(first, second, strict=True)) < -0.9
    geodesic = _quat_angle(first, second)
    assert math.isclose(math.degrees(geodesic), 20.0, abs_tol=1e-6)
    assert math.degrees(_quat_lerp_path(first, second)) > 300.0

    curves = _curves("rotation_quaternion", [first, second])
    camera = _object(curves, 'QUATERNION')
    point = curves[2].keyframe_points[1]
    left_offset = point.handle_left[1] - point.co[1]
    right_offset = point.handle_right[1] - point.co[1]

    assert rotation_curves.repair_rotation_continuity(camera) == 1

    repaired = _rows(curves)
    assert repaired[0] == first
    for value, expected in zip(repaired[1], second, strict=True):
        assert math.isclose(value, -expected)
    # Same orientation, short arc.
    assert math.isclose(_quat_angle(repaired[1], second), 0.0, abs_tol=1e-6)
    assert _quat_lerp_path(repaired[0], repaired[1]) < geodesic + math.radians(1)
    # Negating a key mirrors its curve locally, so shaped handles mirror too.
    assert math.isclose(point.handle_left[1] - point.co[1], -left_offset)
    assert math.isclose(point.handle_right[1] - point.co[1], -right_offset)
    assert [curve.update_count for curve in curves] == [1, 1, 1, 1]
    assert rotation_curves.repair_rotation_continuity(camera) == 0


def test_quaternion_keys_already_on_one_hemisphere_stay_bit_exact(monkeypatch):
    _install_fakes(monkeypatch)
    rows = [_camera_quat(10.0), _camera_quat(40.0), _camera_quat(70.0)]
    curves = _curves("rotation_quaternion", rows, frames=(1, 13, 25))
    camera = _object(curves, 'QUATERNION')

    assert rotation_curves.repair_rotation_continuity(camera) == 0
    assert _rows(curves) == rows
    assert all(curve.update_count == 0 for curve in curves)


def test_axis_angle_axis_flip_is_realigned_with_a_whole_turn(monkeypatch):
    """170 deg about +Z then 170 deg about -Z is a 20-degree turn.

    Interpolating the raw channels drags the axis through zero (identity)
    and back: a 340-degree detour. The repaired key keeps the axis and
    carries the angle past a half turn instead (190 degrees about +Z).
    """
    _install_fakes(monkeypatch)
    first = (math.radians(170.0), 0.0, 0.0, 1.0)
    second = (math.radians(170.0), 0.0, 0.0, -1.0)
    curves = _curves("rotation_axis_angle", [first, second])
    camera = _object(curves, 'AXIS_ANGLE')
    axis_point = curves[3].keyframe_points[1]
    left_offset = axis_point.handle_left[1] - axis_point.co[1]

    assert rotation_curves.repair_rotation_continuity(camera) == 1

    repaired = _rows(curves)
    assert repaired[0] == first
    angle, x, y, z = repaired[1]
    assert math.isclose(math.degrees(angle), 190.0)
    assert (x, y, z) == (0.0, 0.0, 1.0)
    # Midway the camera now sits 10 degrees from either key, not 170.
    midpoint = tuple((a + b) / 2.0 for a, b in zip(*repaired, strict=True))
    assert math.isclose(math.degrees(midpoint[0]), 180.0)
    assert midpoint[1:] == (0.0, 0.0, 1.0)
    assert math.isclose(axis_point.handle_left[1] - axis_point.co[1], -left_offset)
    assert rotation_curves.repair_rotation_continuity(camera) == 0


def test_partial_quaternion_curves_fail_closed(monkeypatch):
    _install_fakes(monkeypatch)
    rows = [_camera_quat(170.0), _camera_quat(-170.0)]
    curves = _curves("rotation_quaternion", rows)[:3]
    camera = _object(curves, 'QUATERNION')

    assert rotation_curves.repair_rotation_continuity(camera) == 0
    assert all(curve.update_count == 0 for curve in curves)


def test_rotation_data_path_follows_the_native_mode():
    assert rotation_curves.rotation_data_path(
        SimpleNamespace(rotation_mode='QUATERNION')
    ) == "rotation_quaternion"
    assert rotation_curves.rotation_data_path(
        SimpleNamespace(rotation_mode='AXIS_ANGLE')
    ) == "rotation_axis_angle"
    assert rotation_curves.rotation_data_path(
        SimpleNamespace(rotation_mode='ZXY')
    ) == "rotation_euler"


# --- beat_sync: keys the capture flow never sees ---------------------------


class _Beats(list):
    def add(self):
        beat = SimpleNamespace(beat_id="", frame=0, image=None)
        self.append(beat)
        return beat


def _shot(camera, frames=()):
    beats = _Beats()
    for frame in frames:
        beat = beats.add()
        beat.frame = frame
    return SimpleNamespace(
        camera=camera, state='DRAFT', beats=beats, active_beat_index=0,
    )


def _scene(*shots):
    return SimpleNamespace(
        mixar_director=SimpleNamespace(shots=list(shots)),
        frame_end=50,
        as_pointer=lambda: 1,
    )


def _sync_fakes(monkeypatch):
    repaired = []
    monkeypatch.setattr(beat_sync, "refresh_manifest", lambda scene, shot: None)
    monkeypatch.setattr(beat_sync, "scope_preview_range", lambda scene, shot: None)
    monkeypatch.setattr(beat_sync, "_ensure_timer", lambda: None)
    monkeypatch.setattr(beat_sync, "_redraw", lambda: None)
    monkeypatch.setattr(
        beat_sync,
        "repair_rotation_continuity",
        lambda camera: repaired.append(camera) or 1,
    )
    for key, value in beat_sync._INITIAL_STATE.items():
        monkeypatch.setitem(beat_sync._state, key, value)
    return repaired


def test_adopted_native_keys_are_continuity_filtered(monkeypatch):
    """I-key / auto-key / pasted keys never pass capture_beat's filter."""
    repaired = _sync_fakes(monkeypatch)
    monkeypatch.setattr(beat_sync, "_native_key_frames", lambda camera: {26, 58})
    camera = object()
    shot = _shot(camera)

    assert beat_sync.adopt_native_keyframes(_scene(shot), shot) == 2
    assert repaired == [camera]


def test_a_native_key_move_reorders_the_chain_and_refilters(monkeypatch):
    """Dragging a key past its neighbour in the Dope Sheet keeps the count."""
    repaired = _sync_fakes(monkeypatch)
    camera = SimpleNamespace(name="Camera")
    shot = _shot(camera, frames=(1, 25, 40))
    scene = _scene(shot)
    monkeypatch.setattr(beat_sync, "_watchable_shot", lambda _scene: shot)

    monkeypatch.setattr(beat_sync, "_native_key_frames", lambda camera: {1, 25, 40})
    beat_sync._on_depsgraph_update(scene, None)
    # A fresh watch may hold keys written before the filter existed.
    assert beat_sync._state["repair"] is True
    beat_sync._state["repair"] = beat_sync._state["adopt"] = False

    beat_sync._on_depsgraph_update(scene, None)
    assert beat_sync._state["repair"] is False

    monkeypatch.setattr(beat_sync, "_native_key_frames", lambda camera: {1, 25, 44})
    beat_sync._on_depsgraph_update(scene, None)
    assert beat_sync._state["repair"] is True
    assert beat_sync._state["adopt"] is False
    assert beat_sync._state["prune"] is False

    assert beat_sync._sync_timer() is None
    assert repaired == [camera]
    assert beat_sync._state["repair"] is False
