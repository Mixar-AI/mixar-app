# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A programmatic restore must survive the hover pump.

The island collapses when the cursor leaves it. But a restore can happen with
the pointer nowhere near it — the queue toast's "View Queue" opens the Queue
tab while the cursor is still on the toast, halfway across the screen. The
pump saw "outside" on its very next tick and shut it again instantly, so the
button looked broken.

`g_hover_await_enter` holds the island open until hover has actually been
offered it: set on every restore, cleared the first time the cursor is inside.
A hover-driven restore clears it immediately (the cursor is over the pill,
which counts as inside), so only restores away from the pointer are affected.
"""

from pathlib import Path

CC = (
    Path(__file__).resolve().parents[1]
    / "src/source/blender/editors/space_agent_bubble/space_agent_bubble.cc"
).read_text()


def _hover_tick() -> str:
    start = CC.index("mixar_bubble_hover_tick_exec")
    return CC[start : CC.index("void MIXAR_OT_bubble_hover_tick", start)]


def _restore() -> str:
    start = CC.index("mixar_bubble_restore_exec(bContext")
    return CC[start : start + 1600]


def test_restore_arms_the_latch():
    assert "g_hover_await_enter = true;" in _restore()


def test_the_latch_blocks_the_collapse_but_not_the_collapse_after_a_visit():
    body = _hover_tick()
    inside = body.index("if (inside) {")
    latch = body.index("if (g_hover_await_enter) {")
    minimise = body.index('"MIXAR_OT_bubble_minimise"')
    # Cleared on entry, checked before the collapse, and the collapse is last.
    assert inside < latch < minimise
    assert "g_hover_await_enter = false;" in body[inside:latch]


def test_the_latch_is_declared_before_every_use():
    decl = CC.index("static bool g_hover_await_enter")
    # The teardown paths clear it far above the hover section.
    assert decl < CC.index("void ED_agent_bubble_windows_closed")
    assert decl < CC.index("mixar_bubble_hover_tick_exec")


def test_teardown_clears_it_on_both_paths():
    """The sibling flag `g_bubble_grown_for_chat` is reset on the close path
    but NOT the freed path, and that asymmetry is a live bug. Do not repeat
    it: file load frees the bubble through `_window_freed` only."""
    closed = CC[CC.index("void ED_agent_bubble_windows_closed") :][:400]
    freed = CC[CC.index("void ED_agent_bubble_window_freed") :][:900]
    assert "g_hover_await_enter = false;" in closed
    assert "g_hover_await_enter = false;" in freed
