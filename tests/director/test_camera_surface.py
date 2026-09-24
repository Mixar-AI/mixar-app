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
    for reference in (
        "view3d_director_lens_popup_create",
        "view3d_director_aspect_popup_create",
        "MIXAR_OT_director_navigate",
        "MIXAR_OT_director_fit_frame",
        "MIXAR_OT_director_drag_frame",
    ):
        assert reference in overlay
    # Precise is hidden from every surface until its role is clear.
    assert "MIXAR_OT_director_precise" not in overlay


def test_camera_gate_speaks_millimetres_not_degrees():
    """The artist feedback: remove FOV degrees, present lens type + mm.

    The gate label shows the focal length ("35mm") or the projection name,
    and the popover offers Perspective/Orthographic/Panoramic plus named
    photographic presets. No director-facing control shows degrees.
    """
    constants = _read("constants.py")
    operators = _read("ui/operators/camera_surface_ops.py")
    # The lens popup lives in its own translation unit (500-line rule).
    popup = (VIEW3D / "view3d_director_popup_lens.cc").read_text(encoding="utf-8")
    overlay = _read_overlay()

    for name in ("Perspective", "Orthographic", "Panoramic"):
        assert name in constants
        assert name in popup
    assert "FOV_PRESETS_DEGREES" not in constants

    assert "camera.data.type = self.lens_type" in operators
    assert "angle_degrees" not in operators

    # A focal length is named by its focal length: "Ultra Wide · 18mm" is
    # 18mm with a word in front of it, and the words are the arguable half.
    from mixar.modules.director.constants import LENS_PRESETS_MM

    assert LENS_PRESETS_MM == (18, 24, 35, 50, 85, 135)
    presets = popup[popup.index("const int presets[] = {") :]
    presets = presets[: presets.index("};")]
    assert [int(part) for part in presets.split("{")[1].split(",")] == list(
        LENS_PRESETS_MM
    )
    for gone in ("Ultra Wide", "Classic", "Telephoto", "Portrait  ·"):
        assert gone not in popup, gone
        assert gone not in constants, gone
    assert '"MIXAR_OT_director_set_lens"' in popup
    assert '"MIXAR_OT_director_set_lens_type"' in popup
    assert '"lens_mm"' in popup

    assert '%dmm' in overlay
    assert "Orthographic" in overlay
    assert "Panoramic" in overlay
    assert "fov_name" not in overlay
    assert "focallength_to_fov" not in overlay


def test_camera_gate_exposes_output_aspects_as_ratios_only():
    """The ratio IS the name.

    "Cinema · 2.39:1" is the same information with a label in front of it, and
    the labels disagreed with each other besides — "Video / TV" and "Social
    media" are one medium at two ratios.
    """
    constants = _read("constants.py")
    popup = (VIEW3D / "view3d_director_popup.cc").read_text(encoding="utf-8")

    for ratio in ("3:2", "4:3", "16:9", "1.85:1", "2.39:1", "9:16", "1:1"):
        assert f'"{ratio}"' in constants, ratio
        assert f'"{ratio}"' in popup, ratio
    for gone in ("Photography", "Smartphones", "Video / TV", "Social media", "Square ·"):
        assert gone not in constants, gone
        assert gone not in popup, gone
    assert '"MIXAR_OT_director_set_aspect"' in popup
    # Enum identifiers are the frozen contract between the native popup
    # and the Python operator.
    for identifier in ("PHOTO", "SMARTPHONE", "WIDE", "CINEMA_185", "CINEMA_239", "VERTICAL", "SQUARE"):
        assert f'"{identifier}"' in popup, identifier


def test_navigate_offers_level_horizon_fix_z():
    """Walk preserves pre-existing roll; Fix Z levels it on Navigate start."""
    viewport = _read("core/viewport.py")
    properties = _read("ui/properties/director_properties.py")
    assert "def level_camera_horizon" in viewport
    assert "to_track_quat('-Z', 'Y')" in viewport
    assert 'getattr(state, "level_horizon", False)' in viewport
    assert "level_horizon: BoolProperty" in properties


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
    # Full View must round-trip: a second click restores the prior framing.
    assert "_view_memory" in frame_ops
    assert '{"before": current, "fitted": fitted}' in frame_ops
    assert "* 2.0" in frame_ops
    assert "_start_offset" in frame_ops
    assert "_start_zoom" in frame_ops
    assert "'WHEELUPMOUSE'" in frame_ops
    assert "cursor_modal_restore" in frame_ops


def test_auto_key_captures_after_camera_moves():
    """Auto Key: walk exits capture directly; every other edit is debounced.

    The watcher rebaselines on frame changes so scrubbing and playback never
    generate keys, and every capture path records the pose signature so a
    just-captured pose is not captured twice.
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
    # Every mode that moves the shot camera is watched; see
    # tests/director/test_auto_key_modes.py for the two exclusions.
    assert "navigation_mode == 'EXPLORE'" in auto_key
    assert "move_in_progress()" in auto_key
    assert "_reset(key=key, frame=frame, sig=sig)" in auto_key
    assert "auto_key.register()" in watch
    # Blender's own Auto Keying, read natively (tests/director/test_dock_actions_row.py).
    assert "animrig::is_autokey_on(scene)" in state_cc
    # The compact rail binds the same RNA property the Timeline does.
    assert '"use_keyframe_insert_auto"' in overlay
    # Native timeline record icons, not a static REC glyph.
    assert "ICON_RECORD_ON : ICON_RECORD_OFF" in overlay


def test_aspect_presets_are_ratios_not_pixel_sizes():
    """A pixel size made aspect and resolution fight: 2.39:1 wrote 2390x1000,
    whose short side matched no tier, so the resolution segment lit nothing."""
    from mixar.modules.director.constants import ASPECT_PRESETS

    for key, (label, ratio_w, ratio_h) in ASPECT_PRESETS.items():
        assert ratio_w < 1000 and ratio_h < 1000, key
        assert label.replace(".", "").replace(":", "").isdigit(), key


def test_the_left_column_has_no_redundant_output_row():
    """It summarised what Export to Moodboard would produce and opened the
    very popup the Export button opens — nothing the export surface does not
    say better at the moment of use."""
    left = (VIEW3D / "view3d_director_cinema_left.cc").read_text(encoding="utf-8")
    right = (VIEW3D / "view3d_director_cinema_right.cc").read_text(encoding="utf-8")

    assert "output_label" not in left
    # The row itself, not the word: the comment above the card says why it
    # went.
    assert '               "Output",' not in left
    assert "view3d_director_render_popup_create" not in left
    # The popup itself is not lost: Export still opens it, passes and all.
    assert "view3d_director_render_popup_create" in right
    assert "render_output_types" not in left
