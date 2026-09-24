# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Opening away from the pointer stays open until a subsequent outside press."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/source/blender/editors/space_agent_bubble"
CC = (CPP / "space_agent_bubble.cc").read_text()
POLICY = (CPP / "agent_bubble_interaction.cc").read_text()


def test_timer_cannot_dismiss_or_open():
    tick = CC.split("static wmOperatorStatus mixar_bubble_hover_tick_exec")[1]
    tick = tick.split("void MIXAR_OT_bubble_hover_tick")[0]
    assert '"MIXAR_OT_bubble_minimise"' not in tick
    assert '"MIXAR_OT_bubble_restore"' not in tick
    assert "Mixar_WindowContainsScreenCursor" not in tick


def test_dismissal_requires_an_outside_button_press():
    assert "event->val != KM_PRESS" in POLICY
    assert "ELEM(event->type, LEFTMOUSE, MIDDLEMOUSE, RIGHTMOUSE)" in POLICY
    assert "ELEM(target->runtime->ghostwin, bubble, pill)" in POLICY
    wm = (ROOT / "src/source/blender/windowmanager/intern/wm_event_system.cc").read_text()
    assert "ED_agent_bubble_handle_event(C, event);" in wm


def test_native_height_is_not_capped_at_the_preset():
    constraints = CC.split("static void bubble_set_min_content_size")[1].split("/* A resize")[0]
    assert "Mixar_WindowSetMaxContentSize(ghostwin, 0, 0);" in constraints
    assert "AGENT_BUBBLE_EXPANDED_HEIGHT" not in constraints


def test_reopening_keeps_user_size_and_respects_the_composer_floor():
    restore = CC.split("static wmOperatorStatus mixar_bubble_restore_exec")[1]
    assert "Mixar_WindowGetContentSize(g_bubble_ghostwin, &width, &height)" in restore
    assert "std::max(height, agent_bubble_collapsed_height_for_current_attachments(C))" in restore


def test_a_pill_only_autoshow_never_collapses_an_open_island():
    """`agent_bubble_show_window(start_minimised=True)` is the file-load and
    workspace-change autoshow. On an island that is already OPEN it fell
    through WM_window_open's dedup into the start_minimised block and
    minimised the chat the user was typing in."""
    show = CC.split("static wmOperatorStatus agent_bubble_show_window_exec")[1]
    show = show.split("void MIXAR_OT_agent_bubble_show_window")[0]
    guard = show.index("if (start_minimised && g_bubble_ghostwin != nullptr && !g_bubble_minimised)")
    assert "return OPERATOR_FINISHED;" in show[guard:guard + 400]
    assert guard < show.index("g_bubble_minimised = true;")


def test_a_stale_pill_press_cannot_toggle_the_island():
    """A pill press whose RELEASE went to another window (a restore
    re-parents the pill mid-press) must not stay armed and minimise the
    island on some later release."""
    src = (ROOT / "src/scripts/mixar/modules/agent_bubble/ui/operators/bubble_header_drag_op.py").read_text()
    undecided = src.split("def _modal_pill_undecided")[1].split("def _pill_begin_drag")[0]
    assert "time.monotonic() - self._pill_press_at > PILL_CLICK_MAX_SECONDS" in undecided
    release = undecided.split("event.value == 'RELEASE'")[1].split("if event.type in")[0]
    assert "return {'CANCELLED'}" in release
    assert release.index("PILL_CLICK_MAX_SECONDS") < release.index("self._pill_click(context)")
    assert "self._pill_press_at = time.monotonic()" in src
    constants = (ROOT / "src/scripts/mixar/modules/agent_bubble/constants.py").read_text()
    assert "PILL_CLICK_MAX_SECONDS = 1.5" in constants
