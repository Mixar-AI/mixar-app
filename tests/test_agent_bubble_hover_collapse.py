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


def test_a_temp_window_freezes_the_collapse():
    """A file browser, the render window and props dialogs are all temp
    windows, and interacting with one must not dismiss its owner."""
    body = _dismiss_policy()
    guard = body.index("WM_window_is_temp_screen")
    minimise = body.rindex("return true;")
    assert guard < minimise


def test_the_islands_own_windows_are_exempt_from_the_temp_check():
    """The bubble and pill windows are themselves temp screens — that is how
    they stay out of the .blend. Asking about temp-ness without excluding
    them prevented every outside click from dismissing the island."""
    body = _dismiss_policy()
    assert "bubble, pill" in body
    island = body.index("is_island")
    temp = body.index("WM_window_is_temp_screen")
    assert island < temp
    assert "!is_island && WM_window_is_temp_screen(&win)" in body


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
    match = re.search(r"area.spacetype == SPACE_FILE[^\n]*", body)
    assert match is not None
    assert "area.full" in match.group(0)


def test_the_bubbles_own_popups_still_freeze_it():
    """Dropdowns/menus/tooltips are regions on the bubble window's screen,
    not windows of their own; widening the guard must not drop them."""
    body = _dismiss_policy()
    assert "win.runtime->ghostwin == bubble" in body
    assert "BLI_listbase_is_empty(&screen->regionbase)" in body
