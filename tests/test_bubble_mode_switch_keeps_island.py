# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Chat island blink on a Zen/Engine click mid-turn.

The click counted as an outside click and collapsed the island; on macOS the
collapse detached the island from the main window before its fade, so the
main window covered it at once and nothing of the chat showed for ~0.3 s.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUBBLE = ROOT / "src/source/blender/editors/space_agent_bubble"


def test_mode_switch_press_is_not_an_outside_click():
    cc = (BUBBLE / "agent_bubble_interaction.cc").read_text()
    helper = cc[cc.index("static bool agent_bubble_press_hits_mode_switch"):cc.index("bool agent_bubble_should_dismiss(")]
    assert "ui::but_find_mouse_over(region, event)" in helper
    assert 'STRPREFIX(but->optype->idname, "MIXAR_OT_set_ui_mode_")' in helper
    body = cc[cc.index("bool agent_bubble_should_dismiss("):]
    assert body.index("agent_bubble_press_hits_mode_switch(C, event)") < body.index("wmWindowManager *wm")


def test_macos_collapse_keeps_the_island_above_the_host_until_its_fade_ends():
    cc = (BUBBLE / "space_agent_bubble.cc").read_text()
    exec_body = cc[cc.index("static wmOperatorStatus mixar_bubble_minimise_exec"):cc.index("void MIXAR_OT_bubble_minimise(")]
    mac = exec_body[exec_body.index("#else\n  /* Do NOT resize the pill here"):exec_body.index("#ifdef _WIN32\n  /* On Windows the \"animate\"")]
    assert "Mixar_WindowDetachFromParent(g_pill_ghostwin, g_bubble_ghostwin);" in mac
    assert "Mixar_WindowDetachFromParent(g_bubble_ghostwin, g_host_ghostwin);" not in mac
    finish = cc[cc.index("static void minimise_anim_finish"):cc.index("Island heartbeat and outside-click dismissal")]
    assert finish.index("Mixar_WindowDetachFromParent(g_bubble_ghostwin, g_host_ghostwin);") < \
        finish.index("Mixar_WindowOrderOut(g_bubble_ghostwin);")
