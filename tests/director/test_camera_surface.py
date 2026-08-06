# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Source contracts for the camera-gate Director controls."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"


def _read(relative: str) -> str:
    return (DIRECTOR / relative).read_text(encoding="utf-8")


def _read_overlay() -> str:
    """The overlay implementation pair (split for the 500-line limit)."""
    return "\n".join(
        (VIEW3D / name).read_text(encoding="utf-8")
        for name in (
            "view3d_director_overlay.cc",
            "view3d_director_overlay_frame.cc",
        )
    )


def test_camera_controls_are_anchored_to_the_live_camera_gate():
    overlay = _read_overlay()

    assert "ED_view3d_calc_camera_border" in overlay
    assert "border.xmin" in overlay
    assert "border.xmax" in overlay
    assert "border.ymin" in overlay
    assert "border.ymax" in overlay
    for operator in (
        "MIXAR_OT_director_show_lens_presets",
        "MIXAR_OT_director_show_aspect_presets",
        "MIXAR_OT_director_navigate",
        "MIXAR_OT_director_precise",
        "MIXAR_OT_director_fit_frame",
        "MIXAR_OT_director_drag_frame",
    ):
        assert operator in overlay


def test_camera_gate_speaks_millimetres_not_degrees():
    """The artist feedback: remove FOV degrees, present lens type + mm.

    The gate label shows the focal length ("35mm") or the projection name,
    and the popover offers Perspective/Orthographic/Panoramic plus named
    photographic presets. No director-facing control shows degrees.
    """
    constants = _read("constants.py")
    operators = _read("ui/operators/camera_surface_ops.py")
    panels = _read("ui/panels/camera_surface_popovers.py")
    overlay = _read_overlay()

    for name in ("Perspective", "Orthographic", "Panoramic"):
        assert name in constants
    for mm, label in (
        ("18", "Ultra Wide"),
        ("24", "Wide"),
        ("35", "Classic"),
        ("50", "Standard"),
        ("85", "Portrait"),
        ("135", "Telephoto"),
    ):
        assert f"({mm}, \"{label}\")" in constants
    assert "FOV_PRESETS_DEGREES" not in constants

    assert "camera.data.type = self.lens_type" in operators
    assert 'name="MIXAR_PT_director_lens_popover"' in operators
    assert "angle_degrees" not in operators

    assert "LENS_PRESET_ITEMS" in panels
    assert '"mixar.director_set_lens"' in panels
    assert '"mixar.director_set_lens_type"' in panels
    assert 'f"{lens_mm}mm"' in panels

    assert '"%dmm  \\u25be"' in overlay or '%dmm' in overlay
    assert "Orthographic  " in overlay
    assert "Panoramic  " in overlay
    assert "fov_name" not in overlay
    assert "focallength_to_fov" not in overlay


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


def test_navigate_offers_level_horizon_fix_z():
    """Walk preserves pre-existing roll; Fix Z levels it on Navigate start."""
    viewport = _read("core/viewport.py")
    properties = _read("ui/properties/director_properties.py")
    popovers = _read("ui/panels/director_popovers.py")

    assert "def level_camera_horizon" in viewport
    assert "to_track_quat('-Z', 'Y')" in viewport
    assert 'getattr(state, "level_horizon", False)' in viewport
    assert "level_horizon: BoolProperty" in properties
    assert '"level_horizon"' in popovers


def test_camera_frame_can_move_resize_and_fill_the_viewport():
    """The gate is no longer fixed: drag to move, scroll to resize, or fit.

    The drag modal mirrors Blender's native camera-view pan math
    (offset += pixel delta over region size scaled by twice the zoom
    factor) so the frame follows the pointer exactly, and Esc restores the
    original offset and zoom.
    """
    frame_ops = _read("ui/operators/frame_ops.py")

    assert "view_camera_offset" in frame_ops
    assert "view_camera_zoom" in frame_ops
    assert "view3d.view_center_camera" in frame_ops
    assert "* 2.0" in frame_ops
    assert "_start_offset" in frame_ops
    assert "_start_zoom" in frame_ops
    assert "'WHEELUPMOUSE'" in frame_ops
    assert "cursor_modal_restore" in frame_ops


def test_auto_key_captures_after_camera_moves():
    """Auto Key: walk exits capture directly; Precise edits are debounced.

    The Precise watcher rebaselines on frame changes so scrubbing and
    playback never generate keys, and every capture path records the pose
    signature so a just-captured pose is not captured twice.
    """
    properties = _read("ui/properties/director_properties.py")
    camera_ops = _read("ui/operators/camera_ops.py")
    capture_ops = _read("ui/operators/capture_ops.py")
    capture = _read("core/capture.py")
    auto_key = _read("core/auto_key.py")
    watch = _read("ui/auto_key_watch.py")
    state_cc = (VIEW3D / "view3d_director_state.cc").read_text(encoding="utf-8")
    overlay = _read_overlay()

    assert "auto_key: BoolProperty" in properties
    assert "def _auto_capture" in camera_ops
    assert "self._start_pose" in camera_ops
    assert "MIXAR_OT_director_toggle_auto_key" in capture_ops
    assert "mark_captured(shot)" in capture
    assert "depsgraph_update_post" in auto_key
    assert "DEBOUNCE_SECONDS" in auto_key
    assert "navigation_mode != 'PRECISE'" in auto_key
    assert "_reset(key=key, frame=frame, sig=sig)" in auto_key
    assert "auto_key.register()" in watch
    assert '"auto_key"' in state_cc
    assert "MIXAR_OT_director_toggle_auto_key" in overlay
    assert "ICON_REC" in overlay
