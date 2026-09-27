# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Outside-click dismissal preserves child pickers and chat popups."""

import re
from pathlib import Path

CPP = Path(__file__).resolve().parents[1] / "src/source/blender/editors/space_agent_bubble"
BUBBLE_CC = (CPP / "agent_bubble_interaction.cc").read_text(encoding="utf-8")


def _dismiss_policy() -> str:
    return BUBBLE_CC.split("static wmOperatorStatus capture_focus_exec")[0]


def test_a_press_inside_a_temp_window_is_not_an_outside_click():
    """A file browser, the render window, Preferences and props dialogs are
    all temp windows; pressing inside one is interaction with that window."""
    body = _dismiss_policy()
    assert "WM_window_is_temp_screen(target)" in body
    guard = body.index("WM_window_is_temp_screen(target)")
    minimise = body.rindex("return true;")
    assert guard < minimise


def test_the_islands_own_windows_are_exempt_from_the_temp_check():
    """The bubble and pill windows are themselves temp screens — that is how
    they stay out of the .blend. Asking about temp-ness without excluding
    them prevented every outside click from dismissing the island."""
    body = _dismiss_policy()
    assert "bubble, pill" in body
    island = body.index("is_island")
    temp = body.index("WM_window_is_temp_screen(&win)")
    assert island < temp
    assert "!is_island && WM_window_is_temp_screen(&win)" in body


def test_a_picker_launched_from_the_island_freezes_the_collapse():
    """The file dialog Upload Reference / Connect Library open is a dialog
    parented to the bubble window; hiding the island would take it down."""
    body = _dismiss_policy()
    assert "win.parent == bubble_win" in body
    assert "win.runtime->ghostwin == bubble" in body


def test_a_file_picker_anywhere_freezes_the_collapse():
    body = _dismiss_policy()
    temp_block = body[body.index("!is_island && WM_window_is_temp_screen(&win)"):]
    assert "area.spacetype == SPACE_FILE" in temp_block.split("if (!screen)")[0]


def test_an_unrelated_temp_window_does_not_freeze_the_collapse():
    """An open Preferences window (or a render view) elsewhere on screen used
    to block every outside click from collapsing the island. Temp-ness alone
    must never answer the policy: only the target, a bubble-parented dialog
    or a file picker may."""
    body = _dismiss_policy()
    temp_line = "if (!is_island && WM_window_is_temp_screen(&win)) {"
    assert temp_line in body
    after = body[body.index(temp_line) + len(temp_line):]
    first_stmt = after.lstrip().splitlines()[0]
    assert first_stmt.strip() != "return false;"
    assert "win.parent == bubble_win" in first_stmt


def test_a_maximised_file_browser_freezes_it_too():
    """`screen->temp` only covers the picker's default WINDOW display type.
    Under USER_TEMP_SPACE_DISPLAY_FULLSCREEN it is a maximised area on a
    screen that is not temp at all."""
    body = _dismiss_policy()
    assert "SPACE_FILE" in body
    assert "area.full != nullptr" in body


def test_a_docked_file_browser_does_not_freeze_it():
    """`area.full` is what separates the temp overlay from a File Browser
    the user keeps in their own layout — without it, that layout would stop
    the island collapsing forever."""
    body = _dismiss_policy()
    # The bare SPACE_FILE test lives inside the temp-window block only; the
    # sweep over every screen (after it) must still require `area.full`.
    non_temp = body[body.index("if (!screen)"):]
    match = re.search(r"area.spacetype == SPACE_FILE[^\n]*", non_temp)
    assert match is not None
    assert "area.full" in match.group(0)


def test_the_bubbles_own_popups_still_freeze_it():
    """Dropdowns/menus/tooltips are regions on the bubble window's screen,
    not windows of their own; widening the guard must not drop them."""
    body = _dismiss_policy()
    assert "win.runtime->ghostwin == bubble" in body
    assert "BLI_listbase_is_empty(&screen->regionbase)" in body
