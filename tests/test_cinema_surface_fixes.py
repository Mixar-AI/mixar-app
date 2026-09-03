# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Source-level contracts for the Cinema Mode surface and the topbar chrome.

Every assertion here pins a defect that is invisible at build time: the C++
compiles either way, and the only signal is a control that reads the wrong
number, lands off the region, or steals another control's clicks.
"""

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
VIEW3D = ROOT / "src/source/blender/editors/space_view3d"
INTERFACE = ROOT / "src/source/blender/editors/interface"
DIRECTOR = ROOT / "src/scripts/mixar/modules/director"
WORKFLOW = ROOT / "src/scripts/mixar/modules/workflow"

HEADER = (VIEW3D / "view3d_director_cinema.hh").read_text(encoding="utf-8")
PAINT = (VIEW3D / "view3d_director_cinema_paint.cc").read_text(encoding="utf-8")
LEFT = (VIEW3D / "view3d_director_cinema_left.cc").read_text(encoding="utf-8")
RIGHT = (VIEW3D / "view3d_director_cinema_right.cc").read_text(encoding="utf-8")
DOCK = (VIEW3D / "view3d_director_cinema_dock.cc").read_text(encoding="utf-8")
TOP = (VIEW3D / "view3d_director_cinema_top.cc").read_text(encoding="utf-8")
TIMELINE = (VIEW3D / "view3d_director_timeline.cc").read_text(encoding="utf-8")
TOPBAR = (INTERFACE / "interface_mixar_topbar.cc").read_text(encoding="utf-8")
KEYMAP = (DIRECTOR / "ui/keymap.py").read_text(encoding="utf-8")
CONSTANTS = (DIRECTOR / "constants.py").read_text(encoding="utf-8")


def _define(name: str) -> float:
    match = re.search(rf"^#define {name} ([0-9.]+)f?\s*(?:/\*.*)?$", HEADER, re.M)
    assert match is not None, f"{name} is not defined in view3d_director_cinema.hh"
    return float(match.group(1))


def _py_constant(name: str) -> float:
    match = re.search(rf"^{name} = ([0-9.]+)$", CONSTANTS, re.M)
    assert match is not None, f"{name} is not defined in director/constants.py"
    return float(match.group(1))


# -------------------------------------------------------------------------
# 1. Speed meter range and direction.


def test_speed_meter_range_mirrors_the_python_beat_bounds():
    assert _define("CINEMA_BEAT_SECONDS_MIN") == _py_constant("MIN_BEAT_SECONDS")
    assert _define("CINEMA_BEAT_SECONDS_MAX") == _py_constant("MAX_BEAT_SECONDS")


def test_speed_meter_fills_the_way_the_slider_travels():
    # The slider is a ButType::Scroll bound straight to `beat_seconds`, so it
    # rises rightwards; the meter it paints over must rise with it.
    assert "(beat_seconds - CINEMA_BEAT_SECONDS_MIN) / span" in LEFT
    assert "CINEMA_BEAT_SECONDS_MAX - CINEMA_BEAT_SECONDS_MIN" in LEFT
    # The old hardcoded, inverted window is gone.
    assert "4.0f - beat_seconds" not in LEFT
    assert "4.0f - 0.1f" not in LEFT


# -------------------------------------------------------------------------
# 2. Resolution chips read the axis the operator actually sets.


def test_resolution_chips_match_on_the_short_side():
    # MIXAR_OT_director_set_resolution scales the SHORTER side, so a 9:16
    # scene at 1080p is 1080x1920 and `ysch` matches no tier.
    assert "std::min(scene->r.xsch, scene->r.ysch)" in RIGHT
    assert "scene ? scene->r.ysch : 1080" not in RIGHT


def test_the_resolution_operator_still_scales_the_short_side():
    template_ops = (DIRECTOR / "ui/operators/template_ops.py").read_text(encoding="utf-8")
    assert "short_side / float(min(width, height))" in template_ops


# -------------------------------------------------------------------------
# 3. List rows may not overlap their pitch.


def test_list_row_height_is_clamped_to_the_pitch():
    assert "std::min(CINEMA_ROW_H, CINEMA_LIST_PITCH)" in PAINT
    # Both lists draw through the clamp; a raw CINEMA_ROW_H row overlaps the
    # next one, and the later-created uiBut wins the shared band.
    assert "cinema_list_row_h()" in RIGHT
    assert "cinema_list_row_h()" in LEFT
    assert "const float row_h = CINEMA_ROW_H * u;" not in RIGHT


def test_the_clamp_actually_bites_for_the_current_tokens():
    assert _define("CINEMA_ROW_H") > _define("CINEMA_LIST_PITCH")


# -------------------------------------------------------------------------
# 4. The wide-surface height gate covers the lowest content.


def test_height_gate_is_derived_from_the_lowest_content():
    assert "700.0f" not in PAINT
    assert "CINEMA_SPEED_CARD_Y + CINEMA_SPEED_CARD_H" in PAINT
    assert "CINEMA_EXPORT_Y + CINEMA_EXPORT_H" in PAINT
    assert "content_bottom - CINEMA_VIEWPORT_TOP" in PAINT


def test_height_gate_leaves_the_speed_slider_and_export_inside_the_region():
    content_bottom = max(
        _define("CINEMA_SPEED_CARD_Y") + _define("CINEMA_SPEED_CARD_H"),
        _define("CINEMA_EXPORT_Y") + _define("CINEMA_EXPORT_H"),
    )
    required = content_bottom - _define("CINEMA_VIEWPORT_TOP")
    # The old gate was 700 design units; the surface needs 728.
    assert required == pytest.approx(728.0)
    assert required > 700.0


def test_the_columns_place_their_lowest_cards_through_those_constants():
    assert "CINEMA_SPEED_CARD_Y, CINEMA_PANEL_W, CINEMA_SPEED_CARD_H" in LEFT
    assert "CINEMA_EXPORT_Y, CINEMA_PANEL_W, CINEMA_EXPORT_H" in RIGHT


# -------------------------------------------------------------------------
# 5. The dock's designed control row is gated like the rest of the surface.


def test_dock_row_is_gated_on_the_viewport_region_not_the_dock():
    # cinema_surface_fits reads a region's height, and the dock's own height
    # is one control row — it has to be asked about the VIEWPORT region.
    assert "BKE_area_find_region_type(area, RGN_TYPE_WINDOW)" in TIMELINE
    assert "cinema_surface_fits(main_region)" in TIMELINE
    controls = TIMELINE.index("cinema_draw_dock_controls")
    gate = TIMELINE.index("cinema_surface_fits(main_region)")
    assert gate < controls


def test_compact_dock_keeps_the_controls_with_no_other_home():
    assert "cinema_draw_dock_compact" in TIMELINE
    compact = DOCK[DOCK.index("void cinema_draw_dock_compact") :]
    # Collapse / immersive / explore and the transport exist ONLY on the dock;
    # dropping the row wholesale would strand them.
    assert "draw_transport(" in compact
    assert "draw_mode_tools(block, region, state, cy, /*full=*/false)" in compact
    # Stale QA records from a previous wide draw must not survive.
    assert "cinema_qa_begin(region)" in compact


# -------------------------------------------------------------------------
# 6. The frame fields never overlap the transport.


def test_frame_fields_yield_to_the_transport():
    assert "transport_right_edge(region)" in DOCK
    assert "fields_fit" in DOCK
    guard = re.search(r"if \(scene != nullptr && fields_fit\) \{", DOCK)
    assert guard is not None
    # Both fields live behind the one guard: dropping only Start would leave a
    # lone End field hanging off the transport.
    fields = DOCK[guard.end() :]
    assert fields.index('"frame_end"') < fields.index("}\n\nvoid cinema_draw_dock_compact")
    assert fields.index('"frame_start"') < fields.index("}\n\nvoid cinema_draw_dock_compact")


# -------------------------------------------------------------------------
# 7. Every painted keycap hint is a real binding.


def test_the_navigate_hint_is_bound():
    assert '{332.0f, {"O"}, 1, "Navigate", false}' in TOP
    assert '"mixar.director_navigate",' in KEYMAP
    assert "type='O'," in KEYMAP
    assert "director_navigate" in KEYMAP.split("_OPERATOR_NAMES")[1]


def test_navigate_is_not_bound_globally():
    # MIXAR_OT_director_navigate.poll has no area/region test, so the binding
    # must live only in keymaps dispatched inside a 3D viewport.
    block = KEYMAP.split("_NAVIGATE_KEYMAPS = (")[1].split("\n)")[0]
    assert "User Interface" not in block
    assert '"Object Mode"' in block
    assert '"3D View"' in block


def test_every_painted_keycap_has_a_binding():
    keys = set(re.findall(r'\{"([A-Z])"', TOP))
    bound = set(re.findall(r"\('([A-Z])', \"", KEYMAP)) | set(
        re.findall(r"type='([A-Z])',", KEYMAP)
    )
    assert keys <= bound, f"painted but unbound: {sorted(keys - bound)}"


# -------------------------------------------------------------------------
# 8. The camera list always shows the active shot.


def test_camera_list_windows_around_the_active_shot():
    assert "cinema_list_window_start(shot_count, active_index)" in RIGHT
    assert "CINEMA_LIST_PITCH * float(slot)" in RIGHT
    assert "const int max_rows = 4;" not in RIGHT
    assert "the rest scrolls out of view" not in RIGHT


def test_window_start_clamps_into_range():
    start = PAINT[PAINT.index("int cinema_list_window_start") :]
    assert "count <= CINEMA_LIST_MAX_ROWS" in start
    assert "std::clamp(centred, 0, count - CINEMA_LIST_MAX_ROWS)" in start


# -------------------------------------------------------------------------
# 9. The Zen slider's centring pad can never push it off the topbar.


class _FakeRegion:
    def __init__(self, width):
        self.width = width


class _FakeSystem:
    def __init__(self, ui_scale):
        self.ui_scale = ui_scale


class _FakePrefs:
    def __init__(self, ui_scale):
        self.system = _FakeSystem(ui_scale)


class _FakeContext:
    def __init__(self, width, ui_scale=1.0):
        self.region = _FakeRegion(width)
        self.preferences = _FakePrefs(ui_scale)


def _header():
    from mixar.modules.workflow.ui.headers import mode_filter_header

    return mode_filter_header


def _reserved_px(header, ui_scale):
    units = (
        header._MENU_STRIP_UNITS
        + header._SLIDER_HALF_UNITS * 2.0
        + header._PAD_SAFETY_UNITS
    )
    return units * 20.0 * ui_scale


@pytest.mark.parametrize(
    ("left_width", "ui_scale", "right_px"),
    [
        (1280, 1.0, 300),  # narrow window
        (1600, 1.25, 400),  # UI scale
        (1600, 1.0, 900),  # long account email widening the profile chip
        (400, 1.0, 300),  # absurdly narrow
    ],
)
def test_centring_pad_never_overruns_the_left_region(left_width, ui_scale, right_px):
    header = _header()
    pad = header._centring_pad_px(_FakeContext(left_width, ui_scale), right_px)
    assert pad >= 0.0
    assert pad <= right_px
    # `ui_update_flexible_spacing` bails out entirely once the content is
    # wider than the region, which left-packs everything and clips the slider.
    # Below the reserve the pad is simply spent to nothing — the slider stays
    # visible, just less perfectly centred.
    assert pad <= max(0.0, left_width - _reserved_px(header, ui_scale))


def test_centring_pad_is_the_full_right_region_when_it_fits():
    header = _header()
    assert header._centring_pad_px(_FakeContext(1920, 1.0), 300) == 300.0


def test_centring_pad_is_zero_without_a_region():
    header = _header()

    class _NoRegion:
        region = None
        preferences = _FakePrefs(1.0)

    assert header._centring_pad_px(_NoRegion(), 300) == 0.0


def test_the_pad_is_drawn_through_the_clamp():
    source = (
        WORKFLOW / "ui/headers/mode_filter_header.py"
    ).read_text(encoding="utf-8")
    assert "pad_px = _centring_pad_px(context, _right_region_width(context))" in source
    assert "layout.separator(factor=_separator_factor_for_px(context, pad_px))" in source
    assert "_separator_factor_for_px(context, right_px)" not in source


# -------------------------------------------------------------------------
# 10. Topbar state comes from the payload, never from the press flag.


@pytest.mark.parametrize("painter", ["draw_cinema_pill", "draw_viewport_pill"])
def test_topbar_state_is_read_from_the_payload_only(painter):
    body = TOPBAR[TOPBAR.index(f"void {painter}") :]
    body = body[: body.index("\n}\n")]
    lit = re.search(r"const bool lit = ([^;]+);", body)
    assert lit is not None
    assert lit.group(1).strip() == "but->hardmax >= 0.5f"
    # UI_SELECT survives only as a press affordance, and it must be a
    # different reading from the lit state.
    assert "const bool pressed =" in body
    assert "UI_SELECT" in body
