# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scribble on the Agent island.

The Scribble toggle was born in the chat and bubble Python headers, and the
island hides both of those header regions — so without a chip of its own the
feature's only entry point in the new UI would be invisible. These are
source-level contracts on the C++ island (a GPU/window-manager surface with no
importable Python half), in the style of the other island tests.
"""

import re
from pathlib import Path

CPP = Path(__file__).resolve().parents[1] / "src/source/blender/editors/space_agent_bubble"
BUBBLE_CC = (CPP / "space_agent_bubble.cc").read_text(encoding="utf-8")
DRAW_CC = (CPP / "agent_ui_controls_paint.cc").read_text(encoding="utf-8")
STATE_CC = (CPP / "agent_ui_state.cc").read_text(encoding="utf-8")
LAYOUT_CC = (CPP / "agent_ui_layout.cc").read_text(encoding="utf-8")
CHIP_FIT_HH = (CPP / "agent_ui_chip_fit.hh").read_text(encoding="utf-8")
ICONS_HH = (CPP / "agent_ui_icons.hh").read_text(encoding="utf-8")
ICONS_CC = (CPP / "agent_ui_icons.cc").read_text(encoding="utf-8")
DRAW_HH = (CPP / "agent_ui_draw.hh").read_text(encoding="utf-8")


def _function_body(source: str, signature_start: str) -> str:
    start = source.index(signature_start)
    open_brace = source.index("{", start)
    depth = 0
    for i in range(open_brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError(f"unterminated function: {signature_start}")


# ---------------------------------------------------------------------------
# The chip drives the EXISTING operators — nothing is re-implemented.
# ---------------------------------------------------------------------------

def test_composer_chip_drives_the_same_toggle_the_headers_do():
    body = _function_body(BUBBLE_CC, "static void agent_bubble_island_controls_bottom(")
    assert '"mixar.scribble_toggle"' in body
    assert '"mixar.scribble_mark_clear"' in body
    # The reading dropdown is the panes' own dropdown idiom over the same
    # WindowManager enum the header's icon_only prop edits.
    assert '"wm.context_menu_enum"' in body
    assert '"window_manager.mixar_mark_intent"' in body


def test_chip_is_gated_on_the_toggle_being_registered():
    """UI modules register in a deferred pass; a chip over a missing operator
    would sit there inert and read as broken."""
    body = _function_body(BUBBLE_CC, "static void agent_bubble_island_controls_bottom(")
    toggle = body.index('"mixar.scribble_toggle"')
    gate = body.rindex("state->scribble_available", 0, toggle)
    assert gate < toggle
    assert 'WM_operatortype_find("MIXAR_OT_scribble_toggle", true)' in STATE_CC


def test_reading_is_available_while_drawing_and_clear_only_after_done():
    body = _function_body(BUBBLE_CC, "static void agent_bubble_island_controls_bottom(")
    reading = body.index('"wm.context_menu_enum"')
    count_gate = body.rindex("state->scribble_armed || state->mark_count > 0", 0, reading)
    assert count_gate < reading
    clear = body.index('"mixar.scribble_mark_clear"')
    armed_gate = body.rindex("!state->scribble_armed", 0, clear)
    assert count_gate < armed_gate < clear, "Clear is offered only when NOT armed — the freeze has its own undo"


def test_attachment_column_does_not_overlap_the_scribble_chips():
    """References have their own region; chips must not also paint thumbnails."""
    body = _function_body(BUBBLE_CC, "static void agent_bubble_island_controls_bottom(")
    assert "footer_thumbnails_draw_image" not in body
    references = (CPP / "agent_bubble_references.cc").read_text()
    visible = _function_body(references, "bool agent_bubble_references_visible(")
    assert "!state.ink_visible" in visible
    assert "agent_bubble_reference_count(C) > 0" in visible
    assert "RGN_TYPE_UI" in references


# ---------------------------------------------------------------------------
# State is READ from the Python-registered properties, exactly as the headers.
# ---------------------------------------------------------------------------

def test_annotate_state_is_independent_of_handwriting():
    gather = _function_body(STATE_CC, "void agent_ui_state_gather(")
    assert '"mixie_chat_ink_visible"' in gather
    assert '"mixar_mark_armed"' in gather
    assert 'r_state->scribble_armed = read_bool_prop(&wm_ptr, "mixar_mark_armed");' in gather


def test_only_draft_marks_are_counted():
    gather = _function_body(STATE_CC, "void agent_ui_state_gather(")
    assert '"mixar_marks"' in gather
    assert 'STREQ(mark_state, "DRAFT")' in gather


def test_state_struct_carries_the_scribble_fields():
    for field in ("scribble_available", "scribble_armed", "ink_visible", "mark_count", "mark_intent"):
        assert re.search(rf"\b{field}\b", DRAW_HH), field


# ---------------------------------------------------------------------------
# Painting: island unit, accent while armed, glyphs stay in the enum contract.
# ---------------------------------------------------------------------------

def test_chip_row_paints_scribble_in_the_island_unit():
    body = _function_body(DRAW_CC, "void agent_ui_draw_chip_row(")
    assert "AGENT_ICON_PEN" in body
    assert "AgentIslandControl::Scribble" in body
    assert "layout->chip_scribble, state->scribble_armed" in body
    assert 'state->scribble_armed ? "Done" : "Sketch"' in body
    assert "AGENT_ICON_CROSS" in body
    assert "AGENT_ICON_CHEVRON_DOWN" in body


def test_new_glyphs_keep_count_last():
    """AGENT_ICON_COUNT is the range guard and the 'no mark' value."""
    enum_body = ICONS_HH[ICONS_HH.index("enum AgentIcon"):]
    enum_body = enum_body[: enum_body.index("};")]
    order = re.findall(r"\bAGENT_ICON_[A-Z_]+\b", enum_body)
    assert order[-1] == "AGENT_ICON_COUNT"
    assert "AGENT_ICON_PEN" in order and "AGENT_ICON_CROSS" in order
    switch = _function_body(ICONS_CC, "void agent_ui_icon_draw(")
    assert "case AGENT_ICON_PEN:" in switch
    assert "case AGENT_ICON_CROSS:" in switch


def test_layout_places_scribble_right_of_upload():
    assert "AGENT_SEG_X + AGENT_CHIP_UPLOAD_W + AGENT_CHIP_GAP" in LAYOUT_CC
    for rect in ("chip_scribble", "chip_reading", "chip_clear"):
        assert f"r_layout->{rect} = f.box(" in LAYOUT_CC


# ---------------------------------------------------------------------------
# Two island behaviours Scribble needed.
# ---------------------------------------------------------------------------

def test_outside_click_collapse_stands_down_while_scribble_is_armed():
    """Drawing on the viewport must not dismiss the Scribble composer."""
    body = _function_body(BUBBLE_CC, "void ED_agent_bubble_handle_event(")
    scribble = body.index("!agent_bubble_scribble_active(C)")
    minimise = body.index('"MIXAR_OT_bubble_minimise"')
    assert scribble < minimise
    assert "agent_bubble_should_dismiss(C, event," in body
    helper = _function_body(BUBBLE_CC, "static bool agent_bubble_scribble_active(")
    assert '"mixar_mark_armed"' in helper
    assert '"mixie_chat_ink_visible"' in helper


def test_empty_state_paints_the_ink_canvas_instead_of_the_field():
    """With no transcript the WINDOW region IS the whole-panel prompt field,
    an embossed uiBut whose chrome would cover the handwriting canvas."""
    start = BUBBLE_CC.index("agent_bubble_island_panel_color(panel_bg);")
    body = BUBBLE_CC[start : BUBBLE_CC.index("/* Side frame:", start)]
    ink = body.index("else if (ink_canvas_open)")
    field = body.index('"agent_island_field_panel"')
    assert ink < field, "the canvas branch must be taken before the field is built"
    canvas_branch = body[ink:field]
    assert "mixie_chat_draw_ink_overlay(C, region);" in canvas_branch
    assert "uiDefButR" not in canvas_branch
    assert "void mixie_chat_draw_ink_overlay(const bContext *C, ARegion *region);" in BUBBLE_CC


def test_handwriting_has_explicit_header_control_with_shared_geometry():
    body = _function_body(BUBBLE_CC, "static void agent_bubble_island_controls_header(")
    assert '"mixie_chat.ink_toggle"' in body
    assert "layout->hdr_handwriting" in body
    assert "state->handwriting_available" in body
    paint = _function_body(DRAW_CC, "void agent_ui_draw_handwriting_control(")
    assert "layout->hdr_handwriting" in paint
    assert "agent_ui_header_icon_draw(AGENT_ICON_SIGNATURE" in paint
    assert "Type instead" not in paint


def test_chip_widths_fit_mark_counts_voice_status_and_auto_switch():
    # The pure fitter measures the labels actually shown (Done, the Voice
    # status or Stop + trace, Auto with its switch); the layout feeds it state.
    assert 'in.scribble_armed ? "Done" : "Sketch"' in CHIP_FIT_HH
    assert 'width("Auto", m.switch_w)' in CHIP_FIT_HH
    assert "width(in.voice_status, m.icon)" in CHIP_FIT_HH
    assert 'width("Stop", m.icon)' in CHIP_FIT_HH
    assert "in.voice_status = state.voice_status;" in LAYOUT_CC
    assert "in.scribble_armed = state.scribble_armed;" in LAYOUT_CC
    assert 'agent_ui_layout_fit_controls(*r_layout, *r_state)' in BUBBLE_CC
