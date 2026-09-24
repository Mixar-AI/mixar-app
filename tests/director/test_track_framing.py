# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Picking a track target also frames it.

The Track To constraint aims the camera at the target's origin, which says
nothing about how much of the frame the object fills: picking a distant object
aimed correctly and left it a speck, which reads as a broken eyedropper.
"""

from __future__ import annotations

import ast
from math import atan2, radians, tan
from pathlib import Path

from mixar.modules.director.core.tracking import fit_distance

ROOT = Path(__file__).resolve().parents[2]
TRACKING = (
    ROOT / "src/scripts/mixar/modules/director/core/tracking.py"
).read_text(encoding="utf-8")
OPS = (
    ROOT / "src/scripts/mixar/modules/director/ui/operators/track_ops.py"
).read_text(encoding="utf-8")


def test_the_distance_puts_the_sphere_inside_the_frame():
    half_fov = radians(20.0)
    radius = 2.0
    distance = fit_distance(radius, half_fov, margin=1.0)
    # At that distance the sphere subtends exactly the frame.
    assert atan2(radius, distance) == radians(20.0) or abs(
        tan(half_fov) * distance - radius
    ) < 1e-6


def test_the_margin_leaves_air_around_the_subject():
    tight = fit_distance(1.0, radians(20.0), margin=1.0)
    default = fit_distance(1.0, radians(20.0))
    assert default > tight


def test_a_wider_lens_can_stand_closer():
    wide = fit_distance(1.0, radians(45.0))
    long = fit_distance(1.0, radians(10.0))
    assert wide < long


def test_degenerate_inputs_never_divide_by_zero():
    assert fit_distance(0.0, 0.0) > 0.0
    assert fit_distance(-5.0, radians(90.0)) > 0.0


def test_the_camera_moves_along_the_line_it_is_already_on():
    """The pick changes how much of the frame the subject fills, not the
    angle the director chose."""
    body = TRACKING[TRACKING.index("def frame_target(") :]
    assert "new_position = centre - direction.normalized() * distance" in body
    # Only the translation is written; the rotation the director set stays.
    assert "moved.translation = Vector(new_position)" in body
    assert "to_track_quat" not in body


def test_it_fits_the_narrower_axis():
    """The narrower axis clips a subject first, so fitting to it is what
    guarantees the whole object is in frame."""
    body = TRACKING[TRACKING.index("def _half_fov(") :]
    body = body[: body.index("\ndef ")]
    assert "min(float(data.sensor_width), float(data.sensor_height))" in body
    assert "data.sensor_fit == 'VERTICAL'" in body
    assert "data.sensor_fit == 'HORIZONTAL'" in body


def test_the_bounding_sphere_is_read_in_world_space():
    """A scaled or rotated object's local bound box does not contain it."""
    body = TRACKING[TRACKING.index("def world_bounding_sphere(") :]
    body = body[: body.index("\ndef ")]
    assert "matrix = obj.matrix_world" in body
    assert "matrix @ Vector(corner)" in body


def test_framing_never_raises_from_the_modal():
    """A target with no geometry, or a degenerate distance, must simply leave
    the camera alone."""
    body = TRACKING[TRACKING.index("def frame_target(") :]
    assert "except (AttributeError, ReferenceError, TypeError, ValueError, ZeroDivisionError):" in body
    assert "return False" in body


def test_the_eyedropper_frames_what_it_picks():
    tree = ast.parse(OPS)
    modal = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "modal"
    )
    source = ast.unparse(modal)
    assert "shot.track_target = target" in source
    assert "frame_target(shot.camera, target)" in source
    assert source.index("shot.track_target = target") < source.index("frame_target(")
