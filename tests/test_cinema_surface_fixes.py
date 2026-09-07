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
LAYOUT = (VIEW3D / "view3d_director_cinema_layout.cc").read_text(encoding="utf-8")
LEFT = (VIEW3D / "view3d_director_cinema_left.cc").read_text(encoding="utf-8")
RIGHT = (VIEW3D / "view3d_director_cinema_right.cc").read_text(encoding="utf-8")
DOCK = (VIEW3D / "view3d_director_cinema_dock.cc").read_text(encoding="utf-8")
TOP = (VIEW3D / "view3d_director_cinema_top.cc").read_text(encoding="utf-8")
TIMELINE = (VIEW3D / "view3d_director_timeline.cc").read_text(encoding="utf-8")
TOPBAR = (INTERFACE / "interface_mixar_topbar.cc").read_text(encoding="utf-8")
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
    assert "std::min(CINEMA_ROW_H, CINEMA_LIST_PITCH)" in LAYOUT
    # Both lists draw through the clamp; a raw CINEMA_ROW_H row overlaps the
    # next one, and the later-created ui::Button wins the shared band.
    assert "cinema_list_row_h()" in RIGHT
    assert "cinema_list_row_h()" in LEFT
    assert "const float row_h = CINEMA_ROW_H * u;" not in RIGHT


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
    GIZMO = (VIEW3D / "view3d_gizmo_navigate.cc").read_text(encoding="utf-8")
    assert "cinema_stage_rect(C, region, &stage)" in GIZMO
    assert "rect_adjusted.xmax = int(stage.xmax - pad)" in GIZMO
    # No branding chip: the top strip is hints and the phone hand-off only.
    assert "Cinema Mode" not in TOP.split("namespace blender {", 1)[1]


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
    assert '{0.0f, {"O"}, 1, "Navigate", false}' in TOP
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
    start = LAYOUT[LAYOUT.index("int cinema_list_window_start") :]
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


def test_every_rounded_control_shares_the_row_radius():
    """Dropdowns, segments, chips, list rows, the strip's controls and the
    Export button all round at CINEMA_ROW_RADIUS; only cards use the panel
    radius. The dock's 26px chips cap the radius to a pill."""
    assert "cinema_panel(track, CINEMA_ROW_RADIUS * u, track_top, track_bottom);" in RIGHT
    assert "cinema_fill(export_rect, CINEMA_ROW_RADIUS * u, export_col);" in RIGHT
    assert "CINEMA_PANEL_RADIUS * u, track_top" not in RIGHT
    assert "cinema_fill(rect, CINEMA_ROW_RADIUS * u, phone_bg);" in TOP
    assert "cinema_panel(row, CINEMA_ROW_RADIUS * u, top, bottom);" in TOP
    assert TOP.count("CINEMA_ROW_RADIUS * cinema_unit()") == 2
    assert DOCK.count("std::min(CINEMA_ROW_RADIUS * u, BLI_rctf_size_y(&rect) * 0.5f)") == 2


def test_hints_start_on_the_gate_and_the_phone_sits_over_the_right_column():
    # Hints align with the fitted camera border's left edge: the stage inset
    # by the SAME pad the gate fit uses, so nothing draws above the left column.
    assert "gate_left = margin + CINEMA_PANEL_W + CINEMA_STAGE_INSET + CINEMA_GATE_PAD;" in TOP
    # ... but the drawn border can be height-limited and sit inside the
    # stage, so the live border wins when there is one.
    assert "if (cinema_camera_gate_rect(C, region, &border)) {" in TOP
    assert "gate_left = border.xmin / u;" in TOP
    assert "float next_x = gate_left;" in TOP
    assert "next_x = hint_end[index] + CINEMA_HINT_GAP;" in TOP
    GATE = (VIEW3D / "view3d_director_cinema_gate.cc").read_text(encoding="utf-8")
    assert "BLI_rctf_pad(&target, -CINEMA_GATE_PAD * u, -CINEMA_GATE_PAD * u);" in GATE
    # The phone hand-off spans the right column, in the strip row.
    assert "const rctf phone = {float(region->winx) - (margin + CINEMA_PANEL_W) * u," in TOP
    assert "float(region->winx) - margin * u," in TOP
    assert "CINEMA_HINT_X" not in HEADER and "CINEMA_PHONE_W" not in TOP


def test_captions_use_the_dimmer_caption_colour():
    assert "const float caption_col[4] = CINEMA_COL_CAPTION;" in LEFT
    assert "const float label_col[4] = CINEMA_COL_CAPTION;" in LEFT
    assert "const float label_col[4] = CINEMA_COL_CAPTION;" in RIGHT


def test_popup_rows_paint_as_the_surface_row_class():
    """Dropdown popups are stock block popups; every option row is tagged as
    a CinemaRow card element so it paints as the graded chip / dim text the
    surface uses, with tokens mirrored from the cinema header."""
    popup = (VIEW3D / "view3d_director_popup.cc").read_text(encoding="utf-8")
    state = popup[popup.index("void director_popup_state(") :]
    state = state[: state.index("\n}\n")]
    assert "ui::MixarCinemaRowKind::Active : ui::MixarCinemaRowKind::Option" in state
    row = (INTERFACE / "interface_mixar_cinema_row.cc").read_text(encoding="utf-8")
    assert f"ROW_RADIUS = {_define('CINEMA_ROW_RADIUS'):.1f}f" in row
    assert "ROW_TOP[4] = {0x58, 0x58, 0x58, 255}" in row  # CINEMA_COL_ROW_TOP #585858
    assert "ROW_BOTTOM[4] = {0x24, 0x24, 0x24, 255}" in row  # CINEMA_COL_ROW_BOTTOM #242424
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
    # The strip's controls hang off the drawn frame's right edge.
    assert "gate_right = border.xmax / u;" in TOP
    assert "const float strip_right = gate_right * u;" in TOP
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
    for name, slot in (("left", "Row"), ("top", "Strip"), ("right", "Export")):
        text = (VIEW3D / f"view3d_director_cinema_{name}.cc").read_text(encoding="utf-8")
        assert f"CinemaPopupSlot::{slot}" in text, name
    widgets = (INTERFACE / "interface_widgets.cc").read_text(encoding="utf-8")
    assert "block_flag & (BLOCK_POPUP | BLOCK_MIXAR_ROUND_ALL)" in widgets
    header = (ROOT / "src/source/blender/editors/include/UI_interface_c.hh").read_text(encoding="utf-8")
    assert "BLOCK_MIXAR_ROUND_ALL = 1 << 28," in header


def test_output_popup_rows_are_styled_and_toggles_keep_their_value():
    """The Export popup's kind toggles and action rows paint as CinemaRows.
    A Row (enum-flag toggle) keeps its VALUE in hardmax, so the tag must not
    write its payload there — that clobbered the bit each toggle set."""
    render = (VIEW3D / "view3d_director_popup_render.cc").read_text(encoding="utf-8")
    assert "UI_mixar_cinema_row_tag(toggle, ui::MixarCinemaRowKind::Option)" in render
    assert render.count("ui::MixarCinemaRowKind::Action") == 2
    row = (INTERFACE / "interface_mixar_cinema_row.cc").read_text(encoding="utf-8")
    tag = row[row.index("void UI_mixar_cinema_row_tag(") :]
    tag = tag[: tag.index("\n}\n")]
    assert "if (but->type != ButtonType::Row) {" in tag
    # The painter lays the row out itself from the FULL label (Blender clips
    # drawstr for its stock layout), dropping the icon when the cell is tight.
    assert "but->str.empty() ? but->drawstr.c_str() : but->str.c_str()" in row
    assert "icon_size + icon_gap + label_w <= float(BLI_rcti_size_x(&text))" in row


def test_transport_steps_are_triangle_plus_inner_dot():
    """The design's transport: play is a filled triangle; each step is a
    smaller triangle pointing outward with a dot on the side facing play."""
    glyph = DOCK[DOCK.index("void transport_glyph(") :]
    glyph = glyph[: glyph.index("\n}\n")]
    assert "const float outer = cx + dir * total * 0.5f;" in glyph
    assert "cinema_triangle(outer - dir * sw, cy, dir * sw, sh, col);" in glyph
    assert "const float dot_x0 = outer - dir * (sw + gap);" in glyph
    assert "stop" not in glyph
