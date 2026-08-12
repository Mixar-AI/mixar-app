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


def _install_fakes(monkeypatch):
    monkeypatch.setattr(
        rotation_curves,
        "assigned_fcurves",
        lambda camera: tuple(camera._test_curves),
    )


def _axis_rotation(axis, angle):
    c, s = math.cos(angle), math.sin(angle)
    if axis == 0:
        return [[1, 0, 0], [0, c, -s], [0, s, c]]
    if axis == 1:
        return [[c, 0, s], [0, 1, 0], [-s, 0, c]]
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def _matmul(a, b):
    return [
        [sum(a[row][i] * b[i][col] for i in range(3)) for col in range(3)]
        for row in range(3)
    ]


def _euler_matrix(values, order):
    matrix = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    for letter in order:
        axis = "XYZ".index(letter)
        matrix = _matmul(matrix, _axis_rotation(axis, values[axis]))
    return matrix


def _matrices_close(a, b, tolerance=1.0e-9):
    return all(
        math.isclose(a[row][col], b[row][col], abs_tol=tolerance)
        for row in range(3)
        for col in range(3)
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


def test_flipped_branch_is_the_same_rotation_in_every_order():
    values = (0.3, -1.1, 2.5)
    for order in ('XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX'):
        flipped = rotation_curves._flipped_branch(values, order)
        assert _matrices_close(
            _euler_matrix(values, order), _euler_matrix(flipped, order)
        ), order


def test_half_turn_branch_flip_is_repaired(monkeypatch):
    """Regression: a matrix-assigned pose keyed on the other Euler branch.

    Live capture data — three Director beats whose middle key stored the
    equivalent-but-flipped triple, making the camera barrel-roll 180 degrees
    between otherwise-adjacent poses.  Euler.make_compatible() left this
    untouched (it only removes whole-turn jumps), so the old repair reported
    zero changed rows.
    """
    _install_fakes(monkeypatch)
    rows = [
        (1.31353, 0.0, 3.12921),
        (-1.27829, -3.14159, -0.0019),
        (1.41302, 0.0, 3.11351),
    ]
    curves = [
        _Curve(axis, tuple(row[axis] for row in rows)) for axis in range(3)
    ]
    camera = _camera(curves)

    assert rotation_curves.repair_euler_rotation_continuity(camera) == 1

    repaired = [
        tuple(curve.keyframe_points[index].co[1] for curve in curves)
        for index in range(3)
    ]
    # The keyed orientations are untouched...
    for before, after in zip(rows, repaired, strict=True):
        assert _matrices_close(
            _euler_matrix(before, 'XYZ'),
            _euler_matrix(after, 'XYZ'),
            tolerance=1.0e-6,
        )
    # ...but every axis now interpolates without a half-turn detour.
    for axis in range(3):
        for earlier, later in zip(repaired, repaired[1:]):
            assert abs(later[axis] - earlier[axis]) < math.pi / 2

    assert rotation_curves.repair_euler_rotation_continuity(camera) == 0


def test_leading_flipped_key_pulls_later_rows_onto_its_branch(monkeypatch):
    """The first key anchors the chain even when it holds the flipped triple."""
    _install_fakes(monkeypatch)
    rows = [
        (-1.46666, 3.14159, 0.01198),
        (1.47074, 0.0, 3.13787),
    ]
    curves = [
        _Curve(axis, tuple(row[axis] for row in rows), frames=(1, 25))
        for axis in range(3)
    ]
    camera = _camera(curves)

    assert rotation_curves.repair_euler_rotation_continuity(camera) == 1

    repaired = [
        tuple(curve.keyframe_points[index].co[1] for curve in curves)
        for index in range(2)
    ]
    assert repaired[0] == rows[0]
    assert _matrices_close(
        _euler_matrix(rows[1], 'XYZ'),
        _euler_matrix(repaired[1], 'XYZ'),
        tolerance=1.0e-6,
    )
    for axis in range(3):
        assert abs(repaired[1][axis] - repaired[0][axis]) < math.pi / 2


def test_already_continuous_keys_stay_bit_exact():
    previous = (1.31353, 0.0, 3.12921)
    values = (1.41302, 0.0, 3.11351)
    assert (
        rotation_curves._compatible_euler_values(values, previous, 'XYZ')
        == values
    )
