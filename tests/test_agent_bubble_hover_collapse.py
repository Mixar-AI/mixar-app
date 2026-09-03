# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The hover-collapse guard in `mixar.bubble_hover_tick`.

The island's resting state is the pill, and moving the cursor off it
collapses the chat. A file picker, though, is opened BY the chat and lives
outside it — so reaching for a file read as "cursor left the island", the
bubble minimised, and the picker went down with it. That left the user
unable to attach a reference image or connect an asset library at all.

Source-level, like the rest of the C++ surface's contracts: the tick is a
GPU/window-manager path with no importable Python half.
"""

import re
from pathlib import Path

CPP = Path(__file__).resolve().parents[1] / "src/source/blender/editors/space_agent_bubble"
BUBBLE_CC = (CPP / "space_agent_bubble.cc").read_text(encoding="utf-8")


def _hover_tick() -> str:
    start = BUBBLE_CC.index("mixar_bubble_hover_tick_exec")
    end = BUBBLE_CC.index("void MIXAR_OT_bubble_hover_tick", start)
    return BUBBLE_CC[start:end]


def test_a_temp_window_freezes_the_collapse():
    """A file browser, the render window and props dialogs are all temp
    windows, and the cursor being over one is exactly the "outside the
    island" the collapse tests for."""
    body = _hover_tick()
    guard = body.index("WM_window_is_temp_screen")
    minimise = body.index('"MIXAR_OT_bubble_minimise"')
    assert guard < minimise


def test_the_islands_own_windows_are_exempt_from_the_temp_check():
    """The bubble and pill windows are themselves temp screens — that is how
    they stay out of the .blend. Asking about temp-ness without excluding
    them froze the collapse permanently and the hover UX stopped working."""
    body = _hover_tick()
    assert "g_pill_ghostwin" in body
    island = body.index("is_island")
    temp = body.index("WM_window_is_temp_screen")
    assert island < temp
    assert "!is_island && WM_window_is_temp_screen(win)" in body


def test_a_maximised_file_browser_freezes_it_too():
    """`screen->temp` only covers the picker's default WINDOW display type.
    Under USER_TEMP_SPACE_DISPLAY_FULLSCREEN it is a maximised area on a
    screen that is not temp at all."""
    body = _hover_tick()
    assert "SPACE_FILE" in body
    assert "area->full != nullptr" in body


def test_a_docked_file_browser_does_not_freeze_it():
    """`area->full` is what separates the temp overlay from a File Browser
    the user keeps in their own layout — without it, that layout would stop
    the island collapsing forever."""
    body = _hover_tick()
    match = re.search(r"area->spacetype == SPACE_FILE[^\n]*", body)
    assert match is not None
    assert "area->full" in match.group(0)


def test_the_bubbles_own_popups_still_freeze_it():
    """Dropdowns/menus/tooltips are regions on the bubble window's screen,
    not windows of their own; widening the guard must not drop them."""
    body = _hover_tick()
    assert "win->runtime->ghostwin == g_bubble_ghostwin" in body
    assert "BLI_listbase_is_empty(&screen->regionbase)" in body
