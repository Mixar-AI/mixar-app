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

#: Geometry and palette live in their own header now; the API stayed put.
HEADER = (VIEW3D / "view3d_director_cinema_tokens.hh").read_text(encoding="utf-8")
CINEMA_HH = (VIEW3D / "view3d_director_cinema.hh").read_text(encoding="utf-8")
PAINT = (VIEW3D / "view3d_director_cinema_paint.cc").read_text(encoding="utf-8")
LAYOUT = (VIEW3D / "view3d_director_cinema_layout.cc").read_text(encoding="utf-8")
LEFT = (VIEW3D / "view3d_director_cinema_left.cc").read_text(encoding="utf-8")
RIGHT = (VIEW3D / "view3d_director_cinema_right.cc").read_text(encoding="utf-8")
CAMERAS = (VIEW3D / "view3d_director_cinema_cameras.cc").read_text(encoding="utf-8")
DOCK = (VIEW3D / "view3d_director_cinema_dock.cc").read_text(encoding="utf-8")
TOP = (VIEW3D / "view3d_director_cinema_top.cc").read_text(encoding="utf-8")
PHONE = (VIEW3D / "view3d_director_cinema_phone.cc").read_text(encoding="utf-8")
TIMELINE = (VIEW3D / "view3d_director_timeline.cc").read_text(encoding="utf-8")
TOPBAR = (INTERFACE / "interface_mixar_topbar.cc").read_text(encoding="utf-8")
MOTION = (INTERFACE / "mixar/motion.cc").read_text(encoding="utf-8")
KEYMAP = (DIRECTOR / "ui/keymap.py").read_text(encoding="utf-8")
CONSTANTS = (DIRECTOR / "constants.py").read_text(encoding="utf-8")


def _define(name: str) -> float:
    match = re.search(rf"^#define {name} (-?[0-9.]+)f?\s*(?:/\*.*)?$", HEADER, re.M)
    assert match is not None, f"{name} is not defined in view3d_director_cinema.hh"
    return float(match.group(1))


def _py_constant(name: str) -> float:
    match = re.search(rf"^{name} = (-?[0-9.]+)$", CONSTANTS, re.M)
    assert match is not None, f"{name} is not defined in director/constants.py"
    return float(match.group(1))


# -------------------------------------------------------------------------
# 1. Speed meter range and direction.


def test_speed_meter_range_mirrors_the_python_speed_bounds():
    assert _define("CINEMA_SPEED_MIN") == _py_constant("SPEED_MIN")
    assert _define("CINEMA_SPEED_MAX") == _py_constant("SPEED_MAX")
    # The slider rests in the middle: 0 is the timing as captured.
    assert _define("CINEMA_SPEED_MIN") == -_define("CINEMA_SPEED_MAX")


def test_speed_meter_is_the_level_bar_bound_to_the_shot():
    # The slider is a ButtonType::Scroll bound straight to `shot.speed`; the
    # meter is the design's level bar, lit from the left as the slider
    # travels (0 sits half-lit in the middle).
    assert "(speed - CINEMA_SPEED_MIN) / span" in LEFT
    assert "cinema_tick_meter(meter, TICKS, int(std::round(travel * float(TICKS))));" in LEFT
    assert '"speed",' in LEFT and "beat_seconds" not in LEFT
    assert "cinema_tick_meter_bipolar" not in PAINT
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
    # And a GAP under the pitch, so consecutive rows stop touching.
    assert "std::min(CINEMA_ROW_H, CINEMA_LIST_PITCH - CINEMA_LIST_GAP)" in LAYOUT
    assert _define("CINEMA_LIST_GAP") > 0.0
    # Both lists draw through the clamp; a raw CINEMA_ROW_H row overlaps the
    # next one, and the later-created ui::Button wins the shared band.
    assert "cinema_list_row_h()" in CAMERAS
    assert "cinema_list_row_h()" in LEFT
    assert "const float row_h = CINEMA_ROW_H * u;" not in CAMERAS


def test_rows_never_exceed_the_list_pitch():
    # One row class everywhere: the dropdown row IS the list row's height.
    assert _define("CINEMA_ROW_H") >= _define("CINEMA_LIST_PITCH")
    assert _define("CINEMA_SEGMENT_H") == _define("CINEMA_ROW_H")
    assert _define("CINEMA_PHONE_H") == _define("CINEMA_ROW_H")


# -------------------------------------------------------------------------
# 4. The wide-surface height gate covers the lowest content.


def test_height_gate_is_derived_from_the_lowest_content():
    assert "700.0f" not in LAYOUT
    assert "CINEMA_SPEED_CARD_Y + CINEMA_SPEED_CARD_H" in LAYOUT
    assert "CINEMA_EXPORT_Y + CINEMA_EXPORT_H" in LAYOUT
    assert "content_bottom - CINEMA_VIEWPORT_TOP" in LAYOUT


def test_height_gate_leaves_the_speed_slider_and_export_inside_the_region():
    content_bottom = max(
        _define("CINEMA_SPEED_CARD_Y") + _define("CINEMA_SPEED_CARD_H"),
        _define("CINEMA_EXPORT_Y") + _define("CINEMA_EXPORT_H"),
    )
    required = content_bottom - _define("CINEMA_VIEWPORT_TOP")
    # The compact layout pass brought the design's foot up from 728 so a
    # MacBook viewport with the timeline open (~680) holds it at 1x.
    assert required == pytest.approx(655.0)
    assert required <= 680.0


def test_the_surface_shrinks_to_fit_before_it_gives_up():
    # A laptop viewport (1512x982 logical, timeline expanded) is ~680 design
    # px tall against the 728 the design needs. Before the fit rule that meant
    # the compact rail on every MacBook; now the design draws at ~0.93x, and
    # only below CINEMA_SCALE_MIN does the compact fallback take over.
    assert 0.5 <= _define("CINEMA_SCALE_MIN") <= 0.8
    fits = LAYOUT[LAYOUT.index("bool cinema_surface_fits(") :]
    fits = fits[: fits.index("\n}\n")]
    assert "cinema_fit_scale(region) >= CINEMA_SCALE_MIN" in fits
    # The unit is the fit, never below the floor, and never above 1x.
    begin = LAYOUT[LAYOUT.index("void cinema_unit_begin(") :]
    begin = begin[: begin.index("\n}\n")]
    assert "std::max(fit, CINEMA_SCALE_MIN)" in begin
    scale = LAYOUT[LAYOUT.index("float cinema_fit_scale(") :]
    scale = scale[: scale.index("\n}\n")]
    # Never above 1x: the panels keep their size on a big screen; only the
    # camera gate grows (view3d_director_cinema_gate.cc).
    assert "std::clamp(fit, 0.0f, 1.0f)" in scale
    assert "CINEMA_REF_W" not in HEADER and "CINEMA_SCALE_MAX" not in HEADER


def test_every_draw_resolves_the_unit_from_the_viewport_region():
    OVERLAY = (VIEW3D / "view3d_director_overlay.cc").read_text(encoding="utf-8")
    assert OVERLAY.index("cinema_unit_begin(region)") < OVERLAY.index(
        "cinema_surface_fits(region)"
    )
    # The dock is one control row tall; its unit comes from the main region.
    assert "cinema_unit_begin(main_region)" in TIMELINE
    assert TIMELINE.index("cinema_unit_begin(main_region)") < TIMELINE.index(
        "cinema_draw_dock_panel(region)"
    )


def test_qa_records_are_cleared_before_either_layout_draws():
    # A compact draw after a wide one must not keep publishing the wide
    # surface's rects: the harness would click controls that are not there.
    OVERLAY = (VIEW3D / "view3d_director_overlay.cc").read_text(encoding="utf-8")
    assert OVERLAY.index("cinema_qa_begin(region)") < OVERLAY.index(
        "if (cinema_surface_fits(region))"
    )
    assert TIMELINE.index("cinema_qa_begin(region)") < TIMELINE.index(
        "cinema_draw_dock_panel(region)"
    )
    # The top strip publishes its rects first; no column may clear them.
    for name in ("view3d_director_cinema_left.cc", "view3d_director_cinema_right.cc"):
        assert "cinema_qa_begin(" not in (VIEW3D / name).read_text(encoding="utf-8"), name


def test_the_stage_spans_the_columns_and_hosts_the_gizmos():
    # Stage top = column top, stage bottom = lowest content: one rect, used
    # by the painter and by the navigation gizmo placement.
    stage = LAYOUT[LAYOUT.index("bool cinema_stage_rect(") :]
    stage = stage[: stage.index("\n}\n")]
    assert "CINEMA_COLUMN_TOP" in stage and "cinema_content_bottom()" in stage
    # No decorative frame is painted any more: the camera gate is fitted to
    # the stage instead, once per layout change.
    assert "cinema_draw_stage" not in LAYOUT
    GATE = (VIEW3D / "view3d_director_cinema_gate.cc").read_text(encoding="utf-8")
    assert "cinema_stage_rect(C, region, &stage)" in GATE
    assert "fit_matches(*record, fit)" in GATE
    assert "BKE_screen_view3d_zoom_from_fac(fac * scale)" in GATE
    OVERLAY = (VIEW3D / "view3d_director_overlay.cc").read_text(encoding="utf-8")
    assert "cinema_fit_camera_gate(C, region);" in OVERLAY
    # The navigation gizmos no longer park in the stage: Cinema Mode draws
    # none (tests/test_view3d_navigate_gizmo.py pins the poll).
    GIZMO = (VIEW3D / "view3d_gizmo_navigate.cc").read_text(encoding="utf-8")
    assert "cinema_stage_rect" not in GIZMO
    # The Mixar banner chip sits above the left column: the column's width
    # from the side margin, on the strip band, in the brand gradient with
    # the Mixar mark. It is chrome only.
    assert "brand_chip(" in TOP
    assert "ICON_MIXAR_ICON" in TOP
    assert "CinemaBrandTop" in TOP
    assert (
        "brand_chip(cinema_design_rect(region, margin, STRIP_Y, CINEMA_PANEL_W, CINEMA_PHONE_H))"
        in TOP
    )
    assert "const float margin = cinema_margin(region);" in TOP


def test_the_banner_chip_is_inert_and_only_on_the_wide_surface():
    chip = TOP[TOP.index("void brand_chip(") :]
    chip = chip[: chip.index("\n}\n")]
    # No button, no QA record, no tooltip: nothing for the harness to find.
    for forbidden in ("cinema_op_button", "cinema_icon_button", "cinema_popup_button",
                      "cinema_qa_record"):
        assert forbidden not in chip, forbidden
    # Same icon call the Agent island uses; the mark is drawn in colour.
    assert "ui::icon_draw_ex(" in chip and "/*mono_color=*/nullptr" in chip
    # Only the wide surface's strip paints it (the compact rail never does).
    assert TOP.count("brand_chip(") == 2
    assert TOP.index("void cinema_draw_top_strip(") < TOP.rindex("brand_chip(")
    # The tokens it lays out with exist and read sensibly.
    assert _define("CINEMA_BRAND_LOGO") < _define("CINEMA_PHONE_H")
    assert _define("CINEMA_BRAND_MARK") < _define("CINEMA_BRAND_LOGO")


def test_the_columns_place_their_lowest_cards_through_those_constants():
    assert "CINEMA_SPEED_CARD_Y, CINEMA_PANEL_W, CINEMA_SPEED_CARD_H" in LEFT
    assert "column_card(region, CINEMA_EXPORT_Y, CINEMA_EXPORT_H)" in RIGHT


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
    # The transport exists ONLY on the dock; dropping the row wholesale would
    # strand it. Everything else the compact layout needs is on the viewport
    # rail, which is what draws below the fit gate.
    assert "draw_transport(" in compact
    assert "draw_primary_action(" not in compact
    # Stale QA records from a previous wide draw must not survive.
    assert "cinema_qa_begin(region)" in compact


# -------------------------------------------------------------------------
# 6. The frame fields never overlap the transport.


def test_frame_fields_yield_to_the_transport():
    assert "transport_right_edge(region)" in DOCK
    # The pair shrinks to FIELD_MIN_W before it gives up (they used to be
    # dropped whole at the first pixel they did not fit at full width —
    # tests/director/test_dock_frame_fields.py).
    guard = re.search(r"if \(field_w < FIELD_MIN_W \* u\) \{\n    return start_x;", DOCK)
    assert guard is not None
    # Both fields live behind the one guard: dropping only Start would leave a
    # lone End field hanging off the transport.
    fields = DOCK[guard.end() :]
    assert fields.index('"frame_end"') < fields.index("draw_transport(")
    assert fields.index('"frame_start"') < fields.index("draw_transport(")


# -------------------------------------------------------------------------
# 7. Every painted keycap hint is a real binding.


def test_the_aerial_hint_is_bound():
    assert '{0.0f, {"O"}, 1, "Aerial view", false}' in TOP
    assert '"mixar.director_aerial",' in KEYMAP
    assert "type='O'," in KEYMAP
    assert "director_aerial" in KEYMAP.split("_OPERATOR_NAMES")[1]
    # O no longer starts the walk; the walk operator stays for the gate button.
    o_item = KEYMAP[: KEYMAP.index("type='O',")]
    assert o_item.rstrip().endswith('"mixar.director_aerial",')
    assert '"mixar.director_navigate",\n            type=\'O\'' not in KEYMAP


def test_aerial_is_not_bound_globally():
    # MIXAR_OT_director_aerial.poll has no area/region test, so the binding
    # must live only in keymaps dispatched inside a 3D viewport.
    block = KEYMAP.split("_NAVIGATE_KEYMAPS = (")[1].split("\n)")[0]
    assert "User Interface" not in block
    assert '"Object Mode"' in block
    assert '"3D View"' in block


#: Blender's own `View3D Walk Modal` keys. The strip may advertise these
#: while a walk is running because walk itself binds them — that is the whole
#: point of handing N to `view3d.walk` rather than reimplementing walking.
_BLENDER_WALK_KEYS = set("WASDQE")


def _hint_keys(array: str) -> set[str]:
    """Single-glyph keycaps painted by one of the top strip's hint sets."""
    block = TOP.split(f"const Hint {array}[", 1)[1].split("};", 1)[0]
    return set(re.findall(r'"([A-Z])"', block))


def _director_bound_keys() -> set[str]:
    bound = set(re.findall(r"type='([A-Z])',", KEYMAP))
    walk_keys = re.search(r"_WALK_KEYS = \((.*?)\)", KEYMAP)
    if walk_keys is not None:
        bound |= set(re.findall(r"'([A-Z])'", walk_keys.group(1)))
    walk_key = re.search(r"_WALK_KEY = '([A-Z])'", KEYMAP)
    if walk_key is not None:
        bound.add(walk_key.group(1))
    return bound


def test_every_painted_keycap_has_a_binding():
    """A hint is a promise, and the strip makes two different sets of them.

    At rest it may only advertise keys the Director keymap binds itself.
    While walking it advertises walk's OWN keys, which Blender binds, plus
    the one exit Director adds to walk's modal keymap.
    """
    bound = _director_bound_keys()
    resting = _hint_keys("resting_hints")
    assert resting <= bound, f"painted but unbound: {sorted(resting - bound)}"

    walking = _hint_keys("walking_hints")
    promised = bound | _BLENDER_WALK_KEYS
    assert walking <= promised, f"painted but unbound: {sorted(walking - promised)}"


# -------------------------------------------------------------------------
# 8. The camera list always shows the active shot.


def test_camera_list_windows_around_the_live_camera():
    # The window snaps to the live camera when it changes; a deliberate
    # scroll owns it after that (tests/director/test_camera_list_scroll.py).
    assert "cinema_list_window_start(count, active_index)" in CAMERAS
    assert "CINEMA_LIST_PITCH * float(slot)" in CAMERAS
    assert "const int max_rows = 4;" not in CAMERAS
    assert "the rest scrolls out of view" not in CAMERAS


def test_window_start_clamps_into_range():
    start = LAYOUT[LAYOUT.index("int cinema_list_window_start") :]
    assert "count <= CINEMA_LIST_MAX_ROWS" in start
    assert "std::clamp(centred, 0, count - CINEMA_LIST_MAX_ROWS)" in start


# -------------------------------------------------------------------------
# 9. Slider geometry is resolved in native window space in both modes.


def test_mode_slider_uses_final_window_geometry():
    body = TOPBAR[TOPBAR.index("void mixar_topbar_center_mode_slider("):]
    body = body[:body.index("\nnamespace {")]
    assert "WM_window_native_pixel_size" in body
    assert "button_to_pixelrect" in body
    assert "view2d_scale_get_x" in body
    assert "BLI_rctf_translate(&left->rect" in body
    assert "BLI_rctf_translate(&right->rect" in body
    assert "UI_HIDDEN" in body  # overflow tabs cannot cover the centered switch
    source = (WORKFLOW / "ui/headers/mode_filter_header.py").read_text()
    assert "_centring_pad_px" not in source
    assert "MIXAR_MT_engine_workspaces" in source
    assert "MIXAR_PT_scene_controls" in source


# -------------------------------------------------------------------------
# 10. Topbar state comes from the payload, never from the press flag.


@pytest.mark.parametrize("painter", ["draw_cinema_pill", "draw_viewport_pill"])
def test_topbar_state_is_read_from_the_payload_only(painter):
    body = TOPBAR[TOPBAR.index(f"void {painter}") :]
    body = body[: body.index("\n}\n")]
    assert "mixar_button_motion(*but)" in body
    assert "motion.selected" in body and "motion.press" in body
    assert "UI_SELECT" not in body
    # The shared sampler preserves the old contract: a held operator supplies
    # press feedback, while its selection comes from the explicit payload.
    sampler = " ".join(MOTION.split())
    assert "native_selection = (button.flag & UI_SELECT_DRAW) || (toggle && (button.flag & UI_SELECT))" in sampler
    toggle_types = re.search(r"const bool toggle = ELEM\(button.type,(.*?)\);", sampler)
    assert toggle_types is not None
    for toggle in ("Toggle", "ToggleN", "IconToggle", "IconToggleN", "Checkbox", "CheckboxN", "Row", "ListRow"):
        assert f"ButtonType::{toggle}" in toggle_types.group(1)
    for action in ("But", "Menu", "Block", "Popover", "Pulldown"):
        assert f"ButtonType::{action}," not in toggle_types.group(1)
    assert "selected = style.lit || native_selection || cinema_selection" in sampler
    assert "pressed = !toggle && (button.flag & UI_SELECT)" in sampler
    assert "ELEM(button.type, ButtonType::But, ButtonType::Menu, ButtonType::Block, ButtonType::Popover, ButtonType::Pulldown)" in sampler


def test_every_rounded_control_shares_the_row_radius():
    """Dropdowns, segments, chips, list rows, the strip's controls and the
    Export button all round at CINEMA_ROW_RADIUS; only cards use the panel
    radius. The dock's 26px chips cap the radius to a pill."""
    assert "cinema_panel(track, CINEMA_ROW_RADIUS * u, track_top, track_bottom);" in RIGHT
    assert "cinema_fill(export_rect, CINEMA_ROW_RADIUS * u, export_col);" in RIGHT
    assert "CINEMA_PANEL_RADIUS * u, track_top" not in RIGHT
    # The phone hand-off moved to its own file when it stopped being paint
    # and became the Virtual Camera's live entry point; it still rounds
    # like the strip it sits in, in both of its states.
    assert "cinema_fill(rect, CINEMA_ROW_RADIUS * u, bg);" in PHONE
    assert "cinema_fill(rect, CINEMA_ROW_RADIUS * u, on);" in PHONE
    assert PHONE.count("CINEMA_ROW_RADIUS * u") == 3
    assert TOP.count("CINEMA_ROW_RADIUS * cinema_unit()") == 2
    # The dock's 26px chips (the interpolation dropdown that joined them from
    # the strip) and its frame fields cap to a pill; so does the ruler's unit
    # switch, which now lives in its own file.
    assert DOCK.count("std::min(CINEMA_ROW_RADIUS * u, BLI_rctf_size_y(&rect) * 0.5f)") == 2
    ruler = (VIEW3D / "view3d_director_cinema_dock_ruler.cc").read_text(encoding="utf-8")
    assert "std::min(CINEMA_ROW_RADIUS * u, BLI_rctf_size_y(&track) * 0.5f)" in ruler
    # The selected cell rounds inside the track it sits in.
    assert "std::min(radius, BLI_rctf_size_y(&cell) * 0.5f)" in ruler


def test_hints_start_on_the_gate_and_the_phone_sits_over_the_right_column():
    # The row never leaves the STAGE: the stage inset by the SAME pad the
    # gate fit uses, so nothing draws above either column. Outside camera
    # view the stage is the whole span.
    assert "const float stage_inset = margin + CINEMA_PANEL_W + CINEMA_STAGE_INSET + CINEMA_GATE_PAD;" in TOP
    assert "row_left = std::max(row_left, stage_left);" in TOP
    assert "row_right = std::min(row_right, stage_right);" in TOP
    # On a wide frame the row starts from the live border's edges ...
    assert "if (cinema_camera_gate_rect(C, region, &border)) {" in TOP
    assert "row_left = border.xmin / u;" in TOP
    assert "row_right = border.xmax / u;" in TOP
    assert "float next_x = row_left;" in TOP
    assert "next_x = hint_end[index] + CINEMA_HINT_GAP;" in TOP
    assert "const float strip_right = row_right * u;" in TOP


def test_a_narrow_frame_widens_the_hint_row_instead_of_blanking_it():
    """A 9:16 border is far narrower than the row, and bounding the row by it
    dropped every hint group. The row widens evenly about the frame's centre
    by what it is missing — hints, their clearance, and the three chips."""
    body = TOP.split("void cinema_draw_top_strip(", 1)[1]
    assert "float row_need = 12.0f + CINEMA_PHONE_H * 3.0f + CINEMA_STRIP_GAP * 2.0f;" in body
    assert "row_need += hint_w[index] + (index > 0 ? CINEMA_HINT_GAP : 0.0f);" in body
    assert "const float missing = row_need - (row_right - row_left);" in body
    assert "row_left -= missing * 0.5f;" in body
    assert "row_right += missing * 0.5f;" in body
    # Widened BEFORE the clamp, so the stage still bounds it.
    assert body.index("row_left -= missing * 0.5f;") < body.index(
        "row_left = std::max(row_left, stage_left);"
    )
    # The groups are measured once and packed from the same widths.
    assert "hint_end[index] = hint.x + hint_w[index];" in body
    GATE = (VIEW3D / "view3d_director_cinema_gate.cc").read_text(encoding="utf-8")
    assert "BLI_rctf_pad(&target, -CINEMA_GATE_PAD * u, -CINEMA_GATE_PAD * u);" in GATE
    # The phone hand-off spans the right column, in the strip row.
    assert "const rctf phone = {float(region->winx) - (margin + CINEMA_PANEL_W) * u," in TOP
    assert "float(region->winx) - margin * u," in TOP
    assert "CINEMA_HINT_X" not in HEADER and "CINEMA_PHONE_W" not in TOP


def test_captions_use_the_dimmer_caption_colour():
    assert "MIXAR_THEME_LOAD(caption_col, CinemaRowCaption);" in LEFT
    assert "MIXAR_THEME_LOAD(label_col, CinemaRowCaption);" in LEFT
    assert "MIXAR_THEME_LOAD(label_col, CinemaRowCaption);" in CAMERAS


def test_popup_rows_paint_as_the_surface_row_class():
    """Dropdown popups are stock block popups; every option row is tagged as
    a CinemaRow card element so it paints as the graded chip / dim text the
    surface uses, with tokens mirrored from the cinema header."""
    popup = (VIEW3D / "view3d_director_popup.cc").read_text(encoding="utf-8")
    state = popup[popup.index("void director_popup_state(") :]
    state = state[: state.index("\n}\n")]
    assert "ui::MixarCinemaRowKind::Active : ui::MixarCinemaRowKind::Option" in state
    row = (INTERFACE / "interface_mixar_cinema_row.cc").read_text(encoding="utf-8")
    chrome = (ROOT / "src/source/blender/editors/include/UI_mixar_chrome.hh").read_text(
        encoding="utf-8"
    )
    assert f"cinema_row_radius = {_define('CINEMA_ROW_RADIUS'):.1f}f" in chrome
    assert "ROW_RADIUS = mixar_chrome::cinema_row_radius" in row
    assert "mixar_chrome::cinema_row_top" in row
    assert "mixar_chrome::cinema_row_bottom" in row
    assert "cinema_row_top[4] = {0x58, 0x58, 0x58, 255}" in chrome
    assert "cinema_row_bottom[4] = {0x24, 0x24, 0x24, 255}" in chrome
    topbar = (INTERFACE / "interface_mixar_topbar.cc").read_text(encoding="utf-8")
    assert "case MixarCardElement::CinemaRow:" in topbar


def test_the_chat_bar_is_the_resting_pill_seated_under_the_gate():
    """The design's chat bar under the camera frame is the Agent island's own
    resting pill (existing behaviour kept): the gate fit reserves the pill's
    band, hands the seat over in window pixels every draw, and every draw
    that does not show the surface releases it. On the bubble side the
    Cinema seat outranks the user-placed one only while it is valid."""
    GATE = (VIEW3D / "view3d_director_cinema_gate.cc").read_text(encoding="utf-8")
    assert "ED_agent_bubble_pill_band_px(win)" in GATE
    # Foot CINEMA_CHAT_GAP above the timeline's top border (the region's
    # bottom), gate kept clear above it or on the columns' foot if higher.
    assert "const float pill_bottom = chat_gap;" in GATE
    assert "ED_agent_bubble_set_cinema_seat(win, true, region->winrct.ymin + int(pill_bottom));" in GATE
    # The frame's foot is free down to the chat bar; its top sits on the
    # columns' top; it is sized to the width between the columns.
    assert "stage.ymin = pill_top + chat_gap;" in GATE
    assert "const float dy = target.ymax - border.ymax;" in GATE
    # The strip's controls hang off the row's right edge, which is the drawn
    # frame's when the frame is wide enough for the row.
    assert "row_right = border.xmax / u;" in TOP
    assert "const float strip_right = row_right * u;" in TOP
    assert GATE.index("ED_agent_bubble_set_cinema_seat(win,") < GATE.index("GateFit fit;")
    OVERLAY = (VIEW3D / "view3d_director_overlay.cc").read_text(encoding="utf-8")
    assert OVERLAY.count("cinema_release_chat_seat(C);") == 2
    BUBBLE = (ROOT / "src/source/blender/editors/space_agent_bubble/space_agent_bubble.cc").read_text(
        encoding="utf-8"
    )
    seat = BUBBLE[BUBBLE.index("static void pill_seat_on_host()") :]
    seat = seat[: seat.index("\n}\n")]
    # A bottom MARGIN through the centre-bottom anchor: parent offsets are
    # measured from the host's frame top, and a content-relative y converted
    # to one lands a title bar too high.
    assert seat.index("pill_cinema_margin(&cinema_margin)") < seat.index("if (g_pill_user_placed)")
    assert "Mixar_WindowAnchorAtParentCentreBottom(g_pill_ghostwin, g_host_ghostwin, cinema_margin)" in seat
    assert "pill_cinema_offset" not in BUBBLE
    closed = BUBBLE[BUBBLE.index("void ED_agent_bubble_windows_closed()") :]
    closed = closed[: closed.index("\n}\n")]
    assert "g_pill_cinema_seat_valid = false;" in closed


def test_popups_size_to_their_bar_and_round_every_corner():
    """A dropdown's list is a detached chip under its bar: the rows take the
    bar's width (handed through the block button's arg), and the backdrop
    rounds all four corners instead of squaring the ones facing the bar."""
    popup = (VIEW3D / "view3d_director_popup.cc").read_text(encoding="utf-8")
    assert "int director_popup_width(const void *arg, const int fallback)" in popup
    assert "ui::block_flag_enable(block, ui::BLOCK_MIXAR_ROUND_ALL);" in popup
    assert "director_popup_width(arg, UI_UNIT_X * 12)" in popup
    interp = (VIEW3D / "view3d_director_popup_interp.cc").read_text(encoding="utf-8")
    render = (VIEW3D / "view3d_director_popup_render.cc").read_text(encoding="utf-8")
    assert "director_popup_width(arg" in interp and "director_popup_width(arg" in render
    assert "g_popup_bar_width[int(slot)]" in PAINT
    # One slot per BAR CLASS, not per file: Interpolation kept the Strip slot
    # when it moved from the top strip to the timeline dock.
    for name, slot in (("left", "Row"), ("dock", "Strip"), ("right", "Export")):
        text = (VIEW3D / f"view3d_director_cinema_{name}.cc").read_text(encoding="utf-8")
        assert f"CinemaPopupSlot::{slot}" in text, name
    assert "CinemaPopupSlot::" not in (
        VIEW3D / "view3d_director_cinema_top.cc"
    ).read_text(encoding="utf-8")
    widgets = (INTERFACE / "interface_widgets.cc").read_text(encoding="utf-8")
    assert "block_flag & (BLOCK_POPUP | BLOCK_MIXAR_ROUND_ALL)" in widgets
    header = (ROOT / "src/source/blender/editors/include/UI_interface_c.hh").read_text(encoding="utf-8")
    assert "BLOCK_MIXAR_ROUND_ALL = 1 << 28," in header


def test_output_popup_rows_are_styled_and_toggles_keep_their_value():
    """The Export popup's video toggles and its one action row paint as
    CinemaRows. A Row (enum-flag toggle) keeps its VALUE in hardmax, so the
    tag must not write its payload there — that clobbered the bit each toggle
    set."""
    render = (VIEW3D / "view3d_director_popup_render.cc").read_text(encoding="utf-8")
    # The three video kinds are the cells of one segmented group (an Option
    # row with a leading icon fit "Clay" and not "Color", so the row read as
    # loose words); the tag still writes no value.
    assert "UI_mixar_cinema_row_tag(toggle, ui::MixarCinemaRowKind::Segment)" in render
    # One send action (tests/director/test_export_popup.py).
    assert render.count("ui::MixarCinemaRowKind::Action") == 1
    row = (INTERFACE / "interface_mixar_cinema_row.cc").read_text(encoding="utf-8")
    tag = row[row.index("void UI_mixar_cinema_row_tag(") :]
    tag = tag[: tag.index("\n}\n")]
    assert "but->hardmin" not in tag and "but->hardmax" not in tag
    # The painter lays the row out itself from the FULL label (Blender clips
    # drawstr for its stock layout), dropping the icon when the cell is tight.
    assert "but->str.empty() ? but->drawstr.c_str() : but->str.c_str()" in row
    assert "icon_size + icon_gap + label_w <= float(BLI_rcti_size_x(&text))" in row


def test_transport_steps_are_triangle_plus_inner_dot():
    """The design's transport: play is a filled triangle; each step is a
    smaller triangle pointing outward with a dot on the side facing play.

    Sizes are explicit design-px tokens measured off the mock (play 16 x 15,
    step triangle ~8.5 x 9.5, dot ~4.5, centres 36 apart, one muted grey) —
    the hit box must never decide how big a glyph paints, which is how the
    triangles came out twice too tall, half as wide, and near-white."""
    # The transport has its own translation unit (500-line rule).
    transport = (VIEW3D / "view3d_director_cinema_dock_transport.cc").read_text(
        encoding="utf-8"
    )
    glyph = transport[transport.index("void transport_glyph(") :]
    glyph = glyph[: glyph.index("\n}\n")]
    # Orientation: apex outward, dot on the inner (play-facing) side.
    assert "const float outer = cx + dir * total * 0.5f;" in glyph
    assert "cinema_triangle(outer - dir * sw, cy, dir * sw, sh, col);" in glyph
    assert "const float dot_x0 = outer - dir * (sw + gap);" in glyph
    assert "stop" not in glyph

    def dock_const(name: str) -> float:
        match = re.search(rf"^constexpr float {name} = (-?[0-9.]+)f;", transport, re.M)
        assert match is not None, f"{name} is not a constexpr in the transport"
        return float(match.group(1))

    # Explicit glyph tokens: the play is a squat near-equilateral triangle
    # (width ~= height), the steps two thirds its height.
    assert dock_const("PLAY_H") == 18.0
    assert dock_const("STEP_H") == 12.0
    assert dock_const("DOT_D") == 5.5
    assert dock_const("STEP_GAP") == 3.0
    assert 0.9 <= dock_const("GLYPH_ASPECT") <= 1.0
    # Pitch: 26 hit box + 18 gap = 44 design px between glyph centres.
    assert dock_const("TRANSPORT_SIZE") == 26.0
    assert dock_const("TRANSPORT_GAP") == 18.0
    # The glyph sizes itself from the tokens, never from the slot box.
    assert "PLAY_SCALE" not in transport
    assert "BLI_rctf_size_y(&box)" not in glyph
    assert "BLI_rctf_size_x(&box)" not in glyph
    for token in ("PLAY_H", "STEP_H", "DOT_D", "STEP_GAP", "GLYPH_ASPECT"):
        assert f"{token} * " in glyph, f"{token} is not what sizes the glyph"
    # One muted grey for all three glyphs (pause included): RGB 135 / 255.
    assert re.search(
        r"^constexpr float TRANSPORT_COL\[4\] = \{0\.53f, 0\.53f, 0\.53f, 1\.0f\};",
        transport,
        re.M,
    )
    assert "const float *col = TRANSPORT_COL;" in glyph
    assert "0.878f" not in transport
    assert re.search(r"const float col\[4\] = \{", glyph) is None
