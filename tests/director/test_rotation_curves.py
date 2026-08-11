# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Regression coverage for Director camera Euler interpolation continuity."""

import math
from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.director.core import rotation_curves  # noqa: E402


class _Point:
    def __init__(self, frame, value, *, left_offset=-0.25, right_offset=0.5):
        self.co = [float(frame), float(value)]
        self.handle_left = [float(frame) - 1.0, float(value) + left_offset]
        self.handle_right = [float(frame) + 1.0, float(value) + right_offset]


class _Curve:
    def __init__(self, axis, values, frames=(1, 11, 21)):
        self.data_path = "rotation_euler"
        self.array_index = axis
        self.keyframe_points = [
            _Point(frame, value) for frame, value in zip(frames, values, strict=True)
        ]
        self.update_count = 0

    def update(self):
        self.update_count += 1


def _camera(curves, mode='XYZ'):
    return SimpleNamespace(
        rotation_mode=mode,
        animation_data=SimpleNamespace(action=object()),
        _test_curves=curves,
    )


def _nearest_channel_values(values, previous, _order):
    result = []
    turn = 2.0 * math.pi
    for value, reference in zip(values, previous, strict=True):
        result.append(value + round((reference - value) / turn) * turn)
    return tuple(result)


def _install_fakes(monkeypatch):
    monkeypatch.setattr(
        rotation_curves,
        "assigned_fcurves",
        lambda camera: tuple(camera._test_curves),
    )
    monkeypatch.setattr(
        rotation_curves,
        "_compatible_euler_values",
        _nearest_channel_values,
    )


def test_wraparound_is_made_continuous_and_handles_keep_their_shape(monkeypatch):
    _install_fakes(monkeypatch)
    curves = [
        _Curve(0, (1.2, 1.2, 1.2)),
        _Curve(1, (0.0, 0.0, 0.0)),
        _Curve(2, (math.pi / 2, math.pi, -3 * math.pi / 4)),
    ]
    camera = _camera(curves)
    point = curves[2].keyframe_points[2]
    left_offset = point.handle_left[1] - point.co[1]
    right_offset = point.handle_right[1] - point.co[1]

    changed = rotation_curves.repair_euler_rotation_continuity(camera)

    assert changed == 1
    assert math.degrees(point.co[1]) == 225.0
    assert math.isclose(point.handle_left[1] - point.co[1], left_offset)
    assert math.isclose(point.handle_right[1] - point.co[1], right_offset)
    assert [curve.update_count for curve in curves] == [1, 1, 1]


def test_repair_is_chronological_and_idempotent(monkeypatch):
    _install_fakes(monkeypatch)
    curves = [
        _Curve(0, (1.2, 1.2, 1.2), frames=(21, 1, 11)),
        _Curve(1, (0.0, 0.0, 0.0), frames=(21, 1, 11)),
        _Curve(
            2,
            (-math.pi / 2, math.pi / 2, -3 * math.pi / 4),
            frames=(21, 1, 11),
        ),
    ]
    camera = _camera(curves)

    assert rotation_curves.repair_euler_rotation_continuity(camera) == 2
    keyed = sorted(curves[2].keyframe_points, key=lambda point: point.co[0])
    assert [round(math.degrees(point.co[1])) for point in keyed] == [90, 225, 270]
    assert rotation_curves.repair_euler_rotation_continuity(camera) == 0


def test_partial_or_misaligned_curves_fail_closed(monkeypatch):
    _install_fakes(monkeypatch)
    partial = [_Curve(0, (0.0, 0.0, 0.0)), _Curve(2, (0.0, 0.0, 0.0))]
    assert rotation_curves.repair_euler_rotation_continuity(_camera(partial)) == 0

    misaligned = [
        _Curve(0, (0.0, 0.0, 0.0)),
        _Curve(1, (0.0, 0.0, 0.0), frames=(1, 12, 21)),
        _Curve(2, (0.0, 0.0, 0.0)),
    ]
    assert rotation_curves.repair_euler_rotation_continuity(_camera(misaligned)) == 0
    assert all(curve.update_count == 0 for curve in misaligned)


def test_non_euler_camera_is_untouched(monkeypatch):
    _install_fakes(monkeypatch)
    curves = [_Curve(axis, (0.0, 0.0, 0.0)) for axis in range(3)]

    assert (
        rotation_curves.repair_euler_rotation_continuity(
            _camera(curves, mode='QUATERNION')
        )
        == 0
    )
    assert all(curve.update_count == 0 for curve in curves)
