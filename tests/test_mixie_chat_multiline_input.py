# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Subsequent Mixie / island prompts must stay multiline and on-screen.

The first empty-state composer is a tall whole-panel field. After Send the
island collapses to a one-row TOOLS strip (~29 px at the default 678-wide
window), which used to fail the 1.5*UI_UNIT_Y multiline gate and clip every
later Shift+Enter line. The Mixie footer could also draw a field taller than
its current winrct (invisible text) and inherit the previous draft's scroll.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITORS = ROOT / "src/source/blender/editors"
UI = EDITORS / "interface"
BUBBLE = EDITORS / "space_agent_bubble"
CHAT = EDITORS / "space_mixie_chat"

HANDLERS = (UI / "interface_handlers.cc").read_text(encoding="utf-8")
WIDGETS = (UI / "interface_widgets.cc").read_text(encoding="utf-8")
LAYOUT_HH = (BUBBLE / "agent_ui_layout.hh").read_text(encoding="utf-8")
LAYOUT_CC = (BUBBLE / "agent_ui_layout.cc").read_text(encoding="utf-8")
THEME_HH = (BUBBLE / "agent_ui_theme.hh").read_text(encoding="utf-8")
BUBBLE_CC = (BUBBLE / "space_agent_bubble.cc").read_text(encoding="utf-8")
FOOTER_LAYOUT = (CHAT / "mixie_chat_footer_layout.cc").read_text(encoding="utf-8")


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


def test_mixie_chat_input_is_always_multiline():
    for source in (HANDLERS, WIDGETS):
        gate = _function_body(source, "static bool ui_but_is_multiline_text")
        assert 'STREQ(RNA_property_identifier(but->rnaprop), "mixie_chat_input")' in gate
        assert "UI_UNIT_Y * 1.5f" in gate
        assert gate.index("mixie_chat_input") < gate.index("UI_UNIT_Y * 1.5f")


def test_island_strip_grows_with_visual_lines():
    assert "#define AGENT_INPUT_MAX_LINES 4" in THEME_HH
    assert "int agent_ui_composer_visual_lines(" in LAYOUT_HH
    assert "float agent_ui_composer_strip_h(" in LAYOUT_HH
    strip = _function_body(LAYOUT_CC, "float agent_ui_composer_strip_h(")
    assert "AGENT_INPUT_H * lines" in strip
    assert "AGENT_INPUT_MAX_LINES" in strip

    build = _function_body(LAYOUT_CC, "void agent_ui_layout_build(")
    assert "agent_ui_composer_strip_h(input_lines)" in build
    assert "chip_y - AGENT_INPUT_GAP - strip_h" in build
    # Chrome floor stays one row so the compact empty island still lays out.
    assert "panel_y - top_du + AGENT_INPUT_H + AGENT_INPUT_GAP + AGENT_CHIP_H +" in build
    assert "agent_ui_panel_top(active_tab)" in build


def test_island_chrome_uses_the_grown_strip():
    layout_get = _function_body(BUBBLE_CC, "bool agent_bubble_island_layout_get(")
    assert "agent_ui_composer_visual_lines(" in layout_get
    assert "agent_ui_composer_wrap_width_px(" in layout_get
    chrome = _function_body(BUBBLE_CC, "static void agent_bubble_sync_chrome_sizes(")
    assert "agent_ui_composer_strip_h(input_lines)" in chrome
    assert "wants_input_strip ? bottom_units : bottom_units_empty" in chrome


def test_footer_wrap_matches_the_widget_font():
    count = _function_body(FOOTER_LAYOUT, "int footer_layout_get_input_line_count(")
    assert "1.2f" not in count
    assert "FOOTER_TEXT_MARGIN_X * U.widget_unit" in count
    assert "ui::style_get()->widget" in count




def test_empty_draft_resets_copied_scroll():
    draw = _function_body(WIDGETS, "static void widget_draw_text_multiline")
    empty = draw[draw.index("if (!drawstr || !drawstr[0])") :]
    empty = empty[: empty.index("/* Calculate line height")]
    assert "state.scroll_offset = 0" in empty
    assert "state.was_editing = false" in empty


def test_multiline_chrome_is_not_hidden_by_field_height():
    draw = _function_body(WIDGETS, "static void widget_textbut_custom(")
    assert "BLI_rcti_size_y" not in draw
    assert "if (but->col[3] < 128)" in draw
    assert "widget_textbut(wcol, rect, state, roundboxalign, zoom)" in draw
