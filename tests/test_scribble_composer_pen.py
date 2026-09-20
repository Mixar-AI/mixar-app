# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Handwriting is explicit: pen taps/drags retain native text editing."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src/source/blender/editors"


def test_composer_keeps_native_selection_without_pen_auto_open():
    text = (ROOT / "interface/interface_handlers.cc").read_text()
    assert "mixie_pen_stroke_open" not in text
    assert "mixie_chat_ink_composer_stylus_stroke" not in text
    select = text[text.index("static int do_but_textedit_select("):]
    move = select[select.index("case MOUSEMOVE:"):]
    assert "textedit_set_cursor_select" in move[:350]


def test_chat_background_never_opens_handwriting_implicitly():
    text = (ROOT / "space_mixie_chat/mixie_chat_main_region.cc").read_text()
    assert "mixie_chat_ink_try_auto_open" not in text
    events = (ROOT / "space_mixie_chat/mixie_chat_ink_events.cc").read_text()
    assert "mixie_chat_ink_set_visible(C, true)" not in events
    assert "ink_open_from_event" not in events


def test_explicit_canvas_still_captures_footer_strokes():
    text = (ROOT / "space_mixie_chat/mixie_chat_ink_events.cc").read_text()
    assert "No text-edit while the canvas is open" in text
    assert "mixie_chat_ink_stroke_extend(rt, mx, my, event->tablet.pressure);" in text


def test_handwriting_never_captures_header_button_clicks():
    text = (ROOT / "space_mixie_chat/mixie_chat_ink_events.cc").read_text()
    header = text[text.index("int mixie_chat_ink_header_ui_handler("):]
    press = header[header.index("event->val == KM_PRESS"):]
    assert press.index("ui::but_find_mouse_over(region, event)") < press.index("mixie_chat_ink_stroke_begin")
