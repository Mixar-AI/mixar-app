# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Source contracts for the camera-gate Director controls."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
OVERLAY = (
    ROOT
    / "src/source/blender/editors/space_view3d/view3d_director_overlay.cc"
)


def _read(relative: str) -> str:
    return (DIRECTOR / relative).read_text(encoding="utf-8")


def test_camera_controls_are_anchored_to_the_live_camera_gate():
    overlay = OVERLAY.read_text(encoding="utf-8")

    assert "ED_view3d_calc_camera_border" in overlay
    assert "border.xmin" in overlay
    assert "border.xmax" in overlay
    assert "border.ymin" in overlay
    assert "border.ymax" in overlay
    for operator in (
        "MIXAR_OT_director_show_fov_presets",
        "MIXAR_OT_director_show_aspect_presets",
        "MIXAR_OT_director_navigate",
        "MIXAR_OT_director_precise",
    ):
        assert operator in overlay


def test_camera_gate_exposes_flow_style_fov_presets():
    constants = _read("constants.py")
    operators = _read("ui/operators/camera_surface_ops.py")
    panels = _read("ui/panels/camera_surface_popovers.py")

    for name, degrees in (
        ("Ultra Narrow", "15.0"),
        ("Narrow", "30.0"),
        ("Standard", "45.0"),
        ("Wide", "60.0"),
        ("Ultra Wide", "75.0"),
        ("Extreme", "90.0"),
    ):
        assert name in constants
        assert degrees in constants
    assert "camera.data.angle = math.radians(self.angle_degrees)" in operators
    assert 'name="MIXAR_PT_director_fov_popover"' in operators
    assert "FOV_PRESETS_DEGREES" in panels


def test_camera_gate_exposes_named_output_aspects():
    constants = _read("constants.py")
    operators = _read("ui/operators/camera_surface_ops.py")
    panels = _read("ui/panels/camera_surface_popovers.py")

    for preset in (
        "Photography / DSLR · 3:2",
        "Smartphones · 4:3",
        "Video / TV · 16:9",
        "Cinema · 1.85:1",
        "Cinema · 2.39:1",
        "Social media · 9:16",
        "Square · 1:1",
    ):
        assert preset in constants
    assert 'name="MIXAR_PT_director_aspect_popover"' in operators
    assert '"mixar.director_set_aspect"' in panels
