# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Open the pill, type immediately, Send/Enter once.

Source-level pins for the Agent island composer. The running-app scenario is
``tests/qa/mixie_open_type_send_e2e.py``.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/source/blender/editors"
BUBBLE = CPP / "space_agent_bubble"
BUBBLE_CC = (BUBBLE / "space_agent_bubble.cc").read_text(encoding="utf-8")
COMPOSER_CC = (BUBBLE / "agent_bubble_composer.cc").read_text(encoding="utf-8")
INTERN_HH = (BUBBLE / "agent_bubble_intern.hh").read_text(encoding="utf-8")
CMAKE = (BUBBLE / "CMakeLists.txt").read_text(encoding="utf-8")
CONTROLS_PAINT_CC = (BUBBLE / "agent_ui_controls_paint.cc").read_text(encoding="utf-8")
HANDLERS_CC = (CPP / "interface/interface_handlers.cc").read_text(encoding="utf-8")
UI_HH = (CPP / "include/UI_interface_c.hh").read_text(encoding="utf-8")
PROBE = (ROOT / "tests/qa/chat_send_probe.py").read_text(encoding="utf-8")
E2E = (ROOT / "tests/qa/mixie_open_type_send_e2e.py").read_text(encoding="utf-8")


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


def test_composer_is_its_own_translation_unit():
    assert "agent_bubble_composer.cc" in CMAKE
    assert "agent_bubble_composer_focus_request" in INTERN_HH
    assert "agent_bubble_composer_focus_if_pending" in INTERN_HH
    assert "agent_bubble_composer_has_focused_draft" in INTERN_HH


def test_restore_makes_the_island_key_and_requests_composer_focus():
    restore = _function_body(BUBBLE_CC, "static wmOperatorStatus mixar_bubble_restore_exec")
    assert restore.index("Mixar_WindowOrderFront(g_bubble_ghostwin)") < restore.index(
        "Mixar_WindowMakeKey(g_bubble_ghostwin)"
    )
    assert restore.index("Mixar_WindowMakeKey(g_bubble_ghostwin)") < restore.index(
        "agent_bubble_composer_focus_request(C, g_bubble_ghostwin)"
    )


def test_window_menu_restore_also_hands_the_keyboard_to_the_composer():
    show = _function_body(BUBBLE_CC, "static wmOperatorStatus agent_bubble_show_window_exec")
    branch = show[show.index("if (g_bubble_ghostwin != nullptr && g_bubble_minimised) {") :]
    branch = branch[: branch.index("WM_window_open")]
    assert "Mixar_WindowMakeKey(g_bubble_ghostwin)" in branch
    assert "agent_bubble_composer_focus_request(C, g_bubble_ghostwin)" in branch


def test_focus_retries_from_the_layout_that_builds_the_field():
    tools = _function_body(BUBBLE_CC, "static void agent_bubble_island_controls_bottom(")
    window = _function_body(BUBBLE_CC, "static void agent_bubble_island_region_draw(")
    assert tools.count("agent_bubble_composer_focus_if_pending") == 1
    assert window.count("agent_bubble_composer_focus_if_pending") == 1
    assert "ui::textbutton_activate_rna(" in COMPOSER_CC
    assert ", true)" in COMPOSER_CC


def test_forced_text_activation_survives_a_rebuild():
    decl = UI_HH[UI_HH.index("bool textbutton_activate_rna(") :]
    decl = decl[: decl.index(";")]
    assert "bool force" in decl
    body = _function_body(HANDLERS_CC, "bool textbutton_activate_rna(")
    force = body[body.index("if (force) {") :]
    assert "button_activate_event(" in force
    assert "button_active_only(" not in force.split("else {")[0]


def test_hover_tick_retries_focus_and_keeps_a_focused_draft():
    tick = _function_body(BUBBLE_CC, "static wmOperatorStatus mixar_bubble_hover_tick_exec")
    assert tick.index("agent_bubble_composer_focus_tick(") < tick.index(
        "agent_bubble_composer_has_focused_draft("
    )
    draft = tick.index("agent_bubble_composer_has_focused_draft(")
    assert draft < tick.index('"MIXAR_OT_bubble_minimise"')


def test_enter_submits_the_whole_draft_from_any_caret():
    case = HANDLERS_CC[
        HANDLERS_CC.index("/* The RNA callback recognizes a trailing submit marker.") :
        HANDLERS_CC.index("case EVT_DELKEY:")
    ]
    assert "textedit_move(but, text_edit, STRCUR_DIR_NEXT, false, STRCUR_JUMP_ALL, true);" in case
    assert 'textedit_insert_buf(but, data->text_edit, "\\x1F", 1);' in case
    move = case.index("textedit_move")
    assert move < case.index("textedit_insert_buf")


def test_open_focus_still_scrolls_the_transcript():
    """The composer is focused on restore so typing works immediately.

    Wheel/trackpad would otherwise die in the modal multiline field,
    while the pointer is over the transcript. Scrolling over the composer
    itself must still scroll a long draft.
    """
    body = _function_body(HANDLERS_CC, "static bool mixie_chat_composer_scroll_transcript(")
    assert "SPACE_AGENT_BUBBLE" in body
    assert "RGN_TYPE_WINDOW" in body
    assert '"VIEW2D_OT_scroll_up"' in body
    assert '"VIEW2D_OT_scroll_down"' in body
    assert '"VIEW2D_OT_pan"' in body
    assert "transcript == CTX_wm_region(C)" in body
    assert "BLI_rcti_isect_pt_v(&transcript->winrct, event->xy)" in body
    edit = _function_body(HANDLERS_CC, "static int do_but_textedit(")
    gate = edit.index("ui_but_mixie_mention_scene(but)")
    assert gate < edit.index("mixie_chat_composer_scroll_transcript(")
    assert "MOUSEPAN" in edit[gate : gate + 400]


def test_send_click_commits_the_composer_and_keeps_the_press():
    body = _function_body(
        HANDLERS_CC, "static int handler_region_menu(bContext *C, const wmEvent *event, void * /*userdata*/)"
    )
    assert "SPACE_AGENT_BUBBLE" in body
    assert "ui_but_mixie_mention_scene(but)" in body
    assert "target->optype" in body
    assert "handle_button_activate(C, region, target, BUTTON_ACTIVATE_OVER)" in body
    exit_at = body.index("button_activate_exit(C, but, but->active, false, false)")
    transfer = body.index("handle_button_activate(C, region, target, BUTTON_ACTIVATE_OVER)")
    assert exit_at < transfer


def test_agent_action_reads_send_not_generate():
    assert 'label_centre(state->status_busy ? "Stop" : "Send"' in CONTROLS_PAINT_CC
    tools = _function_body(BUBBLE_CC, "static void agent_bubble_island_controls_bottom(")
    assert '"mixie_chat.send_message"' in tools
    assert '"Stop the running turn" : "Send"' in tools
    assert '"Generate"' not in tools[tools.index("btn_generate") :]


def test_the_qa_probe_only_replaces_the_transport_boundary():
    assert "get_connection_manager" in PROBE
    assert "create_sse_handler" in PROBE
    assert "send_message" not in PROBE.split("def install")[1].split("def record")[0]
    assert "mixie_chat_input" not in PROBE
    assert "MIXIE_CHAT_OT_send_message" in E2E
    assert "type_without_clicking_composer" in E2E
    assert "one_send_click_while_editing" in E2E
    assert "enter_from_middle_of_draft" in E2E
    assert "shift_enter_adds_newline" in E2E
    assert "failed_send_preserves_draft" in E2E
