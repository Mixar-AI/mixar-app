# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Picking a track target only aims the camera.

The pick used to dolly the camera along its line until the object filled the
frame. That read as the camera zooming in on its own: tracking is an aim, and
where the camera stands and how much of the frame the subject fills stay the
director's. The Track To constraint turns the camera; nothing else moves.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRACKING = (
    ROOT / "src/scripts/mixar/modules/director/core/tracking.py"
).read_text(encoding="utf-8")
OPS = (
    ROOT / "src/scripts/mixar/modules/director/ui/operators/track_ops.py"
).read_text(encoding="utf-8")


def _modal_source() -> str:
    tree = ast.parse(OPS)
    modal = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "modal"
    )
    return ast.unparse(modal)


def test_the_eyedropper_sets_the_target_and_nothing_else():
    source = _modal_source()
    assert "shot.track_target = target" in source
    assert "frame_target" not in source
    # No write to the camera's placement or lens from the pick.
    assert "matrix_world" not in source
    assert ".location" not in source
    assert ".lens" not in source


def test_the_dolly_to_fit_is_gone():
    for name in ("def frame_target(", "def fit_distance(", "def _half_fov("):
        assert name not in TRACKING
    assert "frame_target" not in OPS


def test_tracking_itself_only_aims():
    body = TRACKING[TRACKING.index("def refresh_tracking(") :]
    body = body[: body.index("\ndef ")]
    assert "constraint.track_axis = 'TRACK_NEGATIVE_Z'" in body
    assert "matrix_world" not in body
    assert ".lens" not in body


def test_depth_of_field_keeps_the_bounding_sphere():
    """`core/dof.py` focuses on a picked subject's visual centre."""
    body = TRACKING[TRACKING.index("def world_bounding_sphere(") :]
    assert "matrix = obj.matrix_world" in body
    assert "matrix @ Vector(corner)" in body
