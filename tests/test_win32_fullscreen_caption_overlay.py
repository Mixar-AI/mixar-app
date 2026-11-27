# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Leaving full screen on Windows must give the main window its title bar back.

`GHOST_WindowWin32::setState` strips `WS_CAPTION` to enter full screen.
Upstream re-adds it on every state change; the Mixar overlay stopped doing that
so chromeless windows (Agent Bubble, pill) stay caption-free, which left the
main window with no title bar (move, minimize, maximize, close) after
Window > Toggle Window Fullscreen was turned off. The overlay now remembers
the windows whose caption full screen removed and restores it to exactly
those."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "src/intern/ghost/intern/GHOST_WindowWin32.cc"
SET = "s_mixar_fullscreen_stripped_caption"


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _set_state_body() -> str:
    text = _strip_comments(OVERLAY.read_text(encoding="utf-8"))
    start = text.index("GHOST_TSuccess GHOST_WindowWin32::setState(")
    end = text.index("GHOST_TSuccess GHOST_WindowWin32::setOrder(", start)
    return text[start:end]


def test_entering_full_screen_records_a_caption_it_removes():
    body = _set_state_body()
    fullscreen = body[body.index("case GHOST_kWindowStateFullScreen:"):
                      body.index("case GHOST_kWindowStateNormal:")]
    record = fullscreen.index(f"{SET}.insert(h_wnd_)")
    strip = fullscreen.index("style &= ~(WS_CAPTION | WS_MAXIMIZE)")
    assert record < strip, "the caption must be recorded before it is stripped"
    # WS_CAPTION is two bits (WS_BORDER | WS_DLGFRAME): require both.
    assert "(style & WS_CAPTION) == WS_CAPTION" in fullscreen


def test_every_other_state_restores_only_a_recorded_caption():
    body = _set_state_body()
    switch = body.index("switch (state)")
    head = body[:switch]
    assert "state != GHOST_kWindowStateFullScreen" in head
    assert f"{SET}.erase(h_wnd_) != 0" in head
    assert "style |= WS_CAPTION;" in head
    # Never unconditionally: chromeless windows must stay caption-free.
    assert head.count("style |= WS_CAPTION") == 1
    restore = head.index("style |= WS_CAPTION")
    assert head.rfind(f"{SET}.erase(h_wnd_)", 0, restore) != -1


def test_style_is_applied_after_the_restore():
    body = _set_state_body()
    assert body.index("style |= WS_CAPTION") < body.index(
        "::SetWindowLongPtr(h_wnd_, GWL_STYLE, style)"
    )
    # Frame changes are invisible until SWP_FRAMECHANGED.
    assert "SWP_FRAMECHANGED" in body


def test_destroyed_windows_are_forgotten():
    text = _strip_comments(OVERLAY.read_text(encoding="utf-8"))
    start = text.index("GHOST_WindowWin32::~GHOST_WindowWin32()")
    destructor = text[start:text.index("\n}\n", start)]
    assert f"{SET}.erase(h_wnd_)" in destructor
