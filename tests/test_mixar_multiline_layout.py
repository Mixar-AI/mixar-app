# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Keep native editing boundaries and renderer-owned caret geometry intact.

Behavior is exercised in tests/qa/run_chat_input_regressions.py in the real app.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'src/source/blender/editors/interface'
HANDLERS = (UI / 'interface_handlers.cc').read_text()
WIDGETS = (UI / 'interface_widgets.cc').read_text()


def body(source, start, end):
    return source[source.index(start):source.index(end, source.index(start))]


def test_click_mapping_uses_the_rendered_pixel_geometry():
    draw = body(WIDGETS, 'static void widget_draw_text_multiline', 'static void widget_draw_textbox')
    click = body(HANDLERS, 'static void textedit_set_cursor_pos', 'static void textedit_set_cursor_select')
    for member in ('text_rect', 'line_height', 'visible_lines', 'scroll_offset'):
        assert 'state.' + member in draw
        assert 'state.' + member in click
    lines = body(HANDLERS, 'static int ui_multiline_get_lines', 'static void textedit_move_vertical_mixar')
    assert 'state.font' in lines and 'state.wrap_width' in lines
    assert '1.2f' not in lines
    assert 'mixar_multiline_wrap(' in draw and 'mixar_multiline_wrap(' in lines


def test_scroll_state_belongs_to_each_text_button_and_survives_rebuild():
    intern = (UI / 'interface_intern.hh').read_text()
    text = body(intern, 'struct ButtonText :', 'struct ButtonTextBox :')
    assert 'MixarMultilineState multiline;' in text
    assert 'g_multiline_' not in HANDLERS + WIDGETS
    update = (UI / 'interface.cc').read_text()
    assert 'static_cast<ButtonText *>(but)->multiline = static_cast<ButtonText *>(oldbut)->multiline' in update


def test_native_single_line_and_textbox_paths_stay_outside_multiline_override():
    for source in (HANDLERS, WIDGETS):
        gate = body(source, 'static bool ui_but_is_multiline_text', '\n}\n')
        assert 'but->type != ButtonType::Text' in gate
        assert 'BUT_TEXTEDIT_UPDATE' in gate
        assert 'UI_UNIT_Y * 1.5f' in gate
        assert 'mixie_chat_input' in gate
    click = body(HANDLERS, 'static void textedit_set_cursor_pos', 'static void textedit_set_cursor_select')
    assert click.index('textbox_textedit_set_cursor_pos') < click.index('ui_but_is_multiline_text')
    activate = body(HANDLERS, 'static int do_but_TEX(', 'static int do_but_TEXTBOX(')
    assert 'but->type == ButtonType::TextBox || ui_but_mixie_mention_scene(but) != nullptr' in activate


def test_zen_input_padding_is_shared_by_placeholder_and_edit_geometry():
    draw = body(WIDGETS, 'static void widget_draw_text_multiline', 'static void widget_draw_textbox')
    assert draw.index('mixar_multiline_input_rect') < draw.index('button_placeholder_get')
    assert draw.index('mixar_multiline_input_rect') < draw.index('state.text_rect = *rect')
    style = (UI / 'mixar/style.cc').read_text()
    inset = body(style, 'bool mixar_multiline_input_rect', 'int64_t mixar_button_count')
    # The auto-growing chat composer owns its own line budget; generic fixed
    # editors must not change it or apply symmetric padding on top of native's.
    assert '"mixie_chat_input"' in inset
    assert 'MixarTheme::Zen' in inset and 'MixarComponent::Input' in inset
    assert 'text_rect = bounds' in inset
    assert 'BLI_rcti_pad(&text_rect, -padding, -padding)' in inset
