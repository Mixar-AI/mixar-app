# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The composer can be typed into: a pen TAP places the caret, a pen STROKE
opens Scribble, and the keyboard never does.

The text-edit hook opened Scribble on `val == PRESS && tablet.active ==
STYLUS` with no check of the event TYPE. Blender builds every key event from
a copy of the window's event state, which keeps the `tablet` block of the
last button press — so after one pen tap every keystroke matched, and typing
the first letter into the composer opened the handwriting canvas.

Now a pen press only ARMS a possible stroke; the canvas opens once the pen
travels past the drag threshold while held, seeded from the press point.

Source-level: `interface_handlers.cc` is an overlay of Blender's UI handler
with no importable half.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IH = (ROOT / "src/source/blender/editors/interface/interface_handlers.cc").read_text(encoding="utf-8")
EV = (ROOT / "src/source/blender/editors/space_mixie_chat/mixie_chat_ink_events.cc").read_text(encoding="utf-8")
INTERN = (ROOT / "src/source/blender/editors/space_mixie_chat/mixie_chat_intern.hh").read_text(encoding="utf-8")


def _fn(source: str, signature_start: str, next_signature: str) -> str:
    start = source.index(signature_start)
    return source[start : source.index(next_signature, start)]


TEXTEDIT = _fn(IH, "static int do_but_textedit(", "static int do_but_textedit_select(")
SELECT = _fn(IH, "static int do_but_textedit_select(", "\n}\n")
TEX = _fn(IH, "static int do_but_TEX(", "\n}\n")


def test_the_gate_requires_a_mouse_button_event():
    """The whole point: a key press must never satisfy the pen check."""
    gate = _fn(IH, "static bool mixie_pen_is_stylus_press(", "\n}\n")
    assert "event->type == LEFTMOUSE" in gate
    assert "event->tablet.active == EVT_TABLET_STYLUS" in gate
    # The press-time open is gone everywhere.
    assert "mixie_chat_ink_composer_stylus_open" not in IH
    assert "mixie_chat_ink_composer_stylus_open" not in EV
    assert "mixie_chat_ink_composer_stylus_open" not in INTERN


def test_a_pen_press_arms_and_falls_through_to_the_caret():
    """In the text-edit handler the press arms and does NOT break out: the
    normal caret placement / selection start below it still runs."""
    hook = TEXTEDIT[TEXTEDIT.index("mixie_pen_is_stylus_press(event) && ui_but_mixie_mention_scene(but)") :]
    hook = hook[: hook.index("/* Allow clicks on extra icons")]
    assert "mixie_pen_arm(but, event);" in hook
    assert "BUTTON_STATE_EXIT" not in hook
    assert "retval = WM_UI_HANDLER_BREAK" not in hook
    assert "mixie_pen_disarm();" in hook  # on LEFTMOUSE release


def test_the_activating_press_arms_too():
    """do_but_TEX consumes the press that starts editing, so that press never
    reaches the text-edit handler — it must arm there as well."""
    assert "mixie_pen_is_stylus_press(event) && ui_but_mixie_mention_scene(but)" in TEX
    assert TEX.index("mixie_pen_arm(but, event);") < TEX.index(
        "button_activate_state(C, but, BUTTON_STATE_TEXT_EDITING);")


def test_the_canvas_opens_only_once_the_pen_travels():
    body = _fn(IH, "static bool mixie_pen_stroke_open(", "\n}\n")
    assert "WM_event_drag_test(event, g_mixie_pen_press.xy)" in body
    assert "g_mixie_pen_press.armed" in body and "g_mixie_pen_press.but != but" in body
    # Seeded from the PRESS point, not from wherever the threshold was crossed.
    assert "mixie_chat_ink_composer_stylus_stroke(C, press_xy, event->xy, pressure)" in body
    # Both text-edit states watch for it, and exit editing on success.
    for handler in (TEXTEDIT, SELECT):
        move = handler[handler.index("case MOUSEMOVE:") :]
        move = move[: move.index("break;")]
        assert "mixie_pen_stroke_open(C, but, event)" in move
        assert "BUTTON_STATE_EXIT" in move
    # In the selecting state the pen check comes BEFORE the drag-select update.
    move = SELECT[SELECT.index("case MOUSEMOVE:") :]
    assert move.index("mixie_pen_stroke_open") < move.index("textedit_set_cursor_select")


def test_release_disarms_in_the_selecting_state():
    release = SELECT[SELECT.index("case LEFTMOUSE:") :]
    release = release[: release.index("retval = WM_UI_HANDLER_BREAK")]
    assert "mixie_pen_disarm();" in release


def test_footer_handler_no_longer_opens_on_a_press_while_closed():
    handler = _fn(EV, "static int mixie_chat_ink_footer_ui_handler(", "\n}\n")
    tail = handler[handler.rindex("if (rt->ink_overlay_active) {") :]
    assert "ink_open_from_event" not in tail
    assert "return WM_UI_HANDLER_CONTINUE;" in tail
    # ...but still swallows input presses while open, and still captures
    # strokes over the composer band.
    assert "No text-edit while the canvas is open" in tail
    assert "mixie_chat_ink_stroke_extend(rt, mx, my, event->tablet.pressure);" in handler


def test_stroke_open_seeds_the_first_stroke_from_the_press():
    body = _fn(EV, "bool mixie_chat_ink_composer_stylus_stroke(", "\n}\n")
    assert "ink_open_for_area(C, area, rt);" in body
    assert "mixie_chat_ink_stroke_begin(rt, float(press_xy[0]) - ox, float(press_xy[1]) - oy, pressure);" in body
    assert "mixie_chat_ink_stroke_extend(rt, float(cur_xy[0]) - ox, float(cur_xy[1]) - oy, pressure);" in body
    # The transcript's own pen auto-open (a press on empty chat background) is untouched.
    assert "bool mixie_chat_ink_try_auto_open(bContext *C, const wmEvent *event)" in EV
