# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sketch and Voice keep the island on its current tab.

A disabled pill does not eat the click, and the strip lives in the HEADER,
so a press with no button falls through to the window drag. The lock is a
real button that refuses. It is not an update on ``wm.mixar_bubble_tab``:
the handwriting pad forces AGENT through that property, and the pad has no
strip of its own.
"""

from pathlib import Path

CPP = Path(__file__).resolve().parents[1] / "src/source/blender/editors/space_agent_bubble"
BUBBLE_CC = (CPP / "space_agent_bubble.cc").read_text(encoding="utf-8")
DRAW_CC = (CPP / "agent_ui_controls_paint.cc").read_text(encoding="utf-8")
DETAIL_CC = (CPP / "agent_ui_generations_detail.cc").read_text(encoding="utf-8")


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


def test_other_tabs_refuse_while_sketching_or_dictating():
    body = _function_body(BUBBLE_CC, "static void agent_bubble_island_controls_header(")
    pad = body.index("if (layout->pad)")
    locked = body.index("state->scribble_armed || state->voice_listening")
    noop = body.index('"mixar.bubble_tab_locked"', locked)
    enum = body.index('"wm.context_set_enum"', locked)
    assert pad < locked < noop < enum
    assert "state->active_tab != tb.tab" in body[locked:noop]
    assert "continue;" in body[noop:enum]
    assert "uiDefButO" in body[locked:noop]


def test_the_refusal_is_a_registered_operator():
    assert "MIXAR_OT_bubble_tab_locked" in BUBBLE_CC
    assert "WM_operatortype_append(MIXAR_OT_bubble_tab_locked)" in BUBBLE_CC
    exec_body = _function_body(BUBBLE_CC, "static wmOperatorStatus mixar_bubble_tab_locked_exec(")
    assert "RPT_WARNING" in exec_body
    assert "OPERATOR_CANCELLED" in exec_body


def test_the_handwriting_pad_can_still_force_the_agent_tab():
    """The pad has no strip. Forcing AGENT is a property write, not a click."""
    body = _function_body(BUBBLE_CC, "static void agent_bubble_pad_apply(")
    assert 'RNA_enum_set_identifier(C, &wm_ptr, "mixar_bubble_tab", "AGENT")' in body


def test_inactive_pills_dim_while_the_strip_is_locked():
    body = _function_body(DRAW_CC, "void agent_ui_draw_tab_strip(")
    locked = body.index("state->scribble_armed || state->voice_listening")
    assert "!tab.active" in body[locked:locked + 200]
    assert "label_col[3]" in body[locked:locked + 250]


def test_open_queue_respects_the_same_lock():
    jump = DETAIL_CC.index("Jump to the Queue tab")
    block = DETAIL_CC[jump:jump + 900]
    assert "tabs_locked(C)" in block
    assert '"mixar.bubble_tab_locked"' in block
    assert '"wm.context_set_enum"' in block
    assert '"mixar_mark_armed"' in DETAIL_CC
    assert '"mixie_chat_voice_listening"' in DETAIL_CC
