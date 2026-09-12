# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The minimised pill opens on CLICK and can be DRAGGED anywhere.

Two things used to be true of the resting pill: hovering it unfolded the
island, and every minimise seated it at the host's centre-bottom under an
anchor that snapped it back on the host's next move. Together they made the
pill impossible to move — the press that should start a drag landed on an
island already opening — and opened the chat whenever the cursor merely
crossed the pill on its way somewhere else.

Now a press on the pill is decided by how it ENDS: released in place it is a
click (restore); past ``PILL_DRAG_THRESHOLD_PX`` it is a drag that moves the
pill window, and the seat the drag ends on is where the next minimise puts
the pill again, following the host from there.

Source-level, like the rest of the C++ surface's contracts: the hover tick,
the seat helpers and the GHOST anchors have no importable Python half. The
Python operator is also pinned by source since ``bpy.types.Operator`` is a
MagicMock under the test stub.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/source/blender/editors/space_agent_bubble"
BUBBLE_CC = (CPP / "space_agent_bubble.cc").read_text(encoding="utf-8")
COCOA_MM = (ROOT / "src/intern/ghost/intern/GHOST_SystemCocoa.mm").read_text(
    encoding="utf-8"
)
WIN32_CC = (ROOT / "src/intern/ghost/intern/GHOST_SystemWin32.cc").read_text(
    encoding="utf-8"
)
DRAG_OP = ROOT / "src/scripts/mixar/modules/agent_bubble/ui/operators/bubble_header_drag_op.py"
DRAG_OP_SRC = DRAG_OP.read_text(encoding="utf-8")
CONSTANTS_SRC = (
    ROOT / "src/scripts/mixar/modules/agent_bubble/constants.py"
).read_text(encoding="utf-8")


def _cc_function(name: str) -> str:
    start = BUBBLE_CC.index(name)
    # Body runs to the next top-level closing brace.
    end = BUBBLE_CC.index("\n}\n", start)
    return BUBBLE_CC[start:end]


def _hover_tick() -> str:
    start = BUBBLE_CC.index("mixar_bubble_hover_tick_exec")
    end = BUBBLE_CC.index("void MIXAR_OT_bubble_hover_tick", start)
    return BUBBLE_CC[start:end]


# ---------------------------------------------------------------------------
# 1. Hover never opens the pill
# ---------------------------------------------------------------------------


def test_hover_tick_never_restores_the_minimised_pill():
    """The minimised branch of the tick must not call restore, and must not
    even hit-test the pill — there is nothing hover can do with it."""
    body = _hover_tick()
    start = body.index("if (g_bubble_minimised)")
    end = body.index("if (g_bubble_ghostwin == nullptr)", start)
    minimised_branch = body[start:end]
    assert '"MIXAR_OT_bubble_restore"' not in minimised_branch
    assert "Mixar_WindowContainsScreenCursor" not in minimised_branch
    # Restore is nowhere in the tick at all.
    assert '"MIXAR_OT_bubble_restore"' not in body


def test_hover_tick_still_collapses_the_open_island():
    """Only the OPEN trigger changed; the collapse-on-leave is untouched."""
    body = _hover_tick()
    assert '"MIXAR_OT_bubble_minimise"' in body
    assert "Mixar_WindowContainsScreenCursor(g_bubble_ghostwin" in body


def test_hover_tick_keeps_the_working_pill_animated():
    """The tick's remaining job while minimised: pump the pill redraw so
    Mixie's cat (and the working glow) run while the main draw loop idles."""
    body = _hover_tick()
    start = body.index("if (g_bubble_minimised)")
    minimised_branch = body[start : start + 400]
    assert "agent_bubble_pill_tag_redraw" in minimised_branch


# ---------------------------------------------------------------------------
# 2. The pill press is decided by how it ends
# ---------------------------------------------------------------------------


def _operator_class() -> ast.ClassDef:
    tree = ast.parse(DRAG_OP_SRC)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "MIXAR_OT_bubble_header_drag":
            return node
    raise AssertionError("operator class missing")


def _method_src(name: str) -> str:
    cls = _operator_class()
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(DRAG_OP_SRC, node)
    raise AssertionError(f"{name} missing")


def test_pill_press_goes_modal_instead_of_toggling():
    """invoke() on the pill window must not call minimise/restore; it records
    the press and waits."""
    invoke = _method_src("invoke")
    pill_branch = invoke[invoke.index("_is_pill_window(area)") : invoke.index("# Pass through clicks")]
    assert "bubble_minimise" not in pill_branch
    assert "bubble_restore_user" not in pill_branch
    assert "modal_handler_add" in pill_branch
    assert "RUNNING_MODAL" in pill_branch
    assert "_pill_press = (event.mouse_x, event.mouse_y)" in pill_branch


def test_pill_click_is_the_release_without_travel():
    """The toggle runs from the RELEASE branch of the undecided modal, and
    only there."""
    undecided = _method_src("_modal_pill_undecided")
    release = undecided.index("event.value == 'RELEASE'")
    assert "_pill_click" in undecided[release:]
    click = _method_src("_pill_click")
    assert "bubble_minimise()" in click
    assert "bubble_restore_user()" in click
    # Nothing but the click path restores.
    assert DRAG_OP_SRC.count("bubble_restore_user()") == 1


def test_pill_drag_starts_only_past_the_threshold():
    undecided = _method_src("_modal_pill_undecided")
    assert "PILL_DRAG_THRESHOLD_PX" in undecided
    move = undecided[undecided.index("'MOUSEMOVE'") : undecided.index("'RELEASE'")]
    assert "travelled < PILL_DRAG_THRESHOLD_PX" in move
    assert "_pill_begin_drag" in move
    assert "from mixar.modules.agent_bubble.constants import PILL_DRAG_THRESHOLD_PX" in DRAG_OP_SRC
    match = re.search(r"^PILL_DRAG_THRESHOLD_PX\s*=\s*(\d+)", CONSTANTS_SRC, re.M)
    assert match is not None
    assert 2 <= int(match.group(1)) <= 8


def test_pill_drag_goes_through_the_window_drag_operator():
    begin = _method_src("_pill_begin_drag")
    assert "bubble_window_begin_drag()" in begin
    # A refused drag (the status pill above an OPEN island) ends the gesture
    # as nothing — not a click.
    assert "'CANCELLED'" in begin
    assert "_pill_click" not in begin


def test_undecided_pill_modal_passes_other_events_through():
    """A WINDOW-level modal that swallowed TIMER would starve every other
    timer in the pill window."""
    undecided = _method_src("_modal_pill_undecided")
    assert undecided.rstrip().endswith("return {'PASS_THROUGH'}")


# ---------------------------------------------------------------------------
# 3. The drag moves the resting pill, and the seat is remembered
# ---------------------------------------------------------------------------


def test_begin_drag_moves_only_the_minimised_pill():
    body = _cc_function("static wmOperatorStatus mixar_bubble_window_begin_drag_exec")
    pill = body.index("win->runtime->ghostwin == g_pill_ghostwin")
    assert "if (!g_bubble_minimised)" in body[pill:]
    assert "return OPERATOR_CANCELLED" in body[pill:]
    # The drag must switch the pill off the centre-bottom anchor first, or
    # the host's next move snaps it back.
    switch = body.index("Mixar_WindowAnchorAtParentOffset", pill)
    assert switch < body.index("Mixar_WindowBeginDrag(win->runtime->ghostwin)")
    assert "g_pill_user_placed = true" in body[pill:switch]


def test_every_minimised_seat_goes_through_pill_seat_on_host():
    """No path may anchor the pill centre-bottom directly any more."""
    helper = _cc_function("static void pill_seat_on_host()")
    assert "Mixar_WindowAnchorAtParentCentreBottom" in helper
    assert "Mixar_WindowAnchorAtParentOffset" in helper
    assert "if (g_pill_user_placed)" in helper
    rest = BUBBLE_CC.replace(helper, "")
    calls = [
        m.start()
        for m in re.finditer(r"Mixar_WindowAnchorAtParentCentreBottom\(", rest)
        if not rest[max(0, m.start() - 12) : m.start()].endswith('void ')
    ]
    assert calls == [], "centre-bottom anchor called outside pill_seat_on_host"
    # And the helper is actually what the minimise paths call.
    assert BUBBLE_CC.count("pill_seat_on_host();") >= 4


def test_restore_remembers_where_the_user_left_the_pill():
    restore = _cc_function("static wmOperatorStatus mixar_bubble_restore_exec")
    remember = restore.index("pill_remember_user_seat();")
    # Before the pill is shrunk and re-parented onto the island.
    assert remember < restore.index("pill_set_size(C,")
    assert remember < restore.index("Mixar_WindowSetParent(g_pill_ghostwin, g_bubble_ghostwin)")


def test_user_seat_survives_window_recreation():
    """The seat statics are deliberately NOT cleared with the window pointers:
    a file load recreates the island around the same host."""
    closed = _cc_function("void ED_agent_bubble_windows_closed()")
    freed = _cc_function("void ED_agent_bubble_window_freed(const void *ghostwin)")
    assert "g_pill_user_placed" not in closed
    assert "g_pill_user_placed" not in freed


# ---------------------------------------------------------------------------
# 4. GHOST: the offset anchor exists on every platform the controls do
# ---------------------------------------------------------------------------


def test_offset_anchor_and_getter_exist_on_both_platforms():
    for src in (COCOA_MM, WIN32_CC):
        assert 'extern "C" void Mixar_WindowAnchorAtParentOffset(' in src
        assert 'extern "C" bool Mixar_WindowGetParentOffset(' in src


def test_cocoa_offset_anchor_adopts_user_moves_but_not_parent_translation():
    start = COCOA_MM.index('extern "C" void Mixar_WindowAnchorAtParentOffset(')
    end = COCOA_MM.index('extern "C" bool Mixar_WindowGetParentOffset(', start)
    body = COCOA_MM[start:end]
    # An observer on the CHILD's own move — the only signal an AppKit
    # window-server drag gives.
    assert "object:child" in body
    assert "adopt_child_move" in body
    # Guards: the parent moving, and the anchor's own re-seat.
    assert "NSEqualPoints(parent_frame.origin, last_parent_origin)" in body
    assert "last_applied" in body
    # y-DOWN from the parent's top: the convention shared with Win32.
    assert "NSMaxY(parent_frame) - NSMaxY(child_frame)" in body


def test_win32_offset_anchor_is_relative_offset_tracking():
    start = WIN32_CC.index('extern "C" void Mixar_WindowAnchorAtParentOffset(')
    end = WIN32_CC.index('extern "C" bool Mixar_WindowGetParentOffset(', start)
    body = WIN32_CC[start:end]
    assert "MIXAR_TRACK_RELATIVE_OFFSET" in body
    # EndDrag already re-reads RELATIVE_OFFSET offsets after a drag.
    end_drag = WIN32_CC[WIN32_CC.index('extern "C" void Mixar_WindowEndDrag(') :]
    end_drag = end_drag[: end_drag.index("\n}\n")]
    assert "MIXAR_TRACK_RELATIVE_OFFSET" in end_drag
