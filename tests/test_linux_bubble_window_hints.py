# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""X11 Agent Bubble chrome: five-element Motif hints and a client drag fallback.

xfwm4 4.18's getMotifHints() discards _MOTIF_WM_HINTS unless items_read >= 5.
A 4-long write leaves the DIALOG bubble decorated, and _NET_WM_MOVERESIZE
then never sees the custom header. The overlay writes the full Motif struct
and moves the window from the header-drag modal via _NET_MOVERESIZE_WINDOW.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WINDOW_X11 = ROOT / "src/intern/ghost/intern/GHOST_WindowX11.cc"
WINDOW_HH = ROOT / "src/intern/ghost/intern/GHOST_WindowX11.hh"
IWINDOW = ROOT / "src/intern/ghost/GHOST_IWindow.hh"
WM_WINDOW = ROOT / "src/source/blender/windowmanager/intern/wm_window.cc"
BUBBLE_CC = ROOT / "src/source/blender/editors/space_agent_bubble/space_agent_bubble.cc"
DRAG_OP = ROOT / "src/scripts/mixar/modules/agent_bubble/ui/operators/bubble_header_drag_op.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function(text: str, signature: str) -> str:
    start = text.index(signature)
    brace = text.index("{", start)
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise AssertionError(signature)


def test_motif_hints_are_the_five_card32_iccmm_struct():
    text = _read(WINDOW_X11)
    struct = _function(text, "struct MotifWmHints")
    for field in ("flags", "functions", "decorations", "input_mode", "status"):
        assert f"long {field};" in struct
    assert "MOTIF_WM_HINTS_ELEMENTS = 5" in text
    write = _function(text, "static void write_motif_wm_hints(")
    assert "MOTIF_WM_HINTS_ELEMENTS" in write
    assert ",\n                  4)" not in text
    assert re.search(r"XChangeProperty\([^;]*_MOTIF_WM_HINTS[^;]*,\s*4\)", text) is None


def test_frameless_motif_keeps_move_and_resize_without_decorations():
    body = _function(text := _read(WINDOW_X11), "void GHOST_WindowX11::motifShowWindowFrame(")
    assert "MWM_HINTS_FUNCTIONS | MWM_HINTS_DECORATIONS" in body
    assert "MWM_FUNCTION_RESIZE | MWM_FUNCTION_MOVE | MWM_FUNCTION_CLOSE" in body
    assert "hints.decorations = 0;" in body
    assert "write_motif_wm_hints(" in body
    dialog = _function(text, "GHOST_TSuccess GHOST_WindowX11::setDialogHints(")
    assert "if (custom_decoration_)" in dialog
    assert "motifShowWindowFrame(false)" in dialog


def test_motif_is_written_before_map_and_before_shape():
    text = _read(WINDOW_X11)
    assert "Mixar_GHOST_RequestNextWindowCustomDecoration" in text
    assert "g_next_window_custom_decoration" in text
    ctor = _function(text, "GHOST_WindowX11::GHOST_WindowX11(")
    assert "pre_mapped_custom_decoration_ = true;" in ctor
    assert ctor.find("custom_decoration_ = true;") < ctor.find("setDialogHints(")
    custom = _function(text, "void GHOST_WindowX11::setCustomDecoration(")
    assert custom.find("motifShowWindowFrame(false)") < custom.find("getClientBounds(bounds)")
    assert "XWithdrawWindow" in custom
    assert "pre_mapped_custom_decoration_" in custom
    wm = _read(WM_WINDOW)
    assert "Mixar_GHOST_RequestNextWindowCustomDecoration()" in wm
    assert "SPACE_AGENT_BUBBLE" in wm


def test_x11_header_drag_uses_wm_moveresize_and_client_followup():
    text = _read(WINDOW_X11)
    begin = _function(text, "GHOST_TSuccess GHOST_WindowX11::beginWindowDrag(")
    assert "drag_active_ = true;" in begin
    assert "XIUngrabDevice" in begin
    assert "XUngrabPointer" in begin
    assert "x11_send_net_wm_moveresize(" in begin
    send = _function(text, "static void x11_send_net_wm_moveresize(")
    assert 'XInternAtom(display, "_NET_WM_MOVERESIZE", False)' in send
    assert "data.l[2] = 8;" in send
    update = _function(text, "GHOST_TSuccess GHOST_WindowX11::updateWindowDrag(")
    assert "x11_move_window_on_desktop(" in update
    assert "XQueryPointer" in update
    move = _function(text, "static void x11_move_window_on_desktop(")
    assert 'XInternAtom(display, "_NET_MOVERESIZE_WINDOW", False)' in move
    assert "XMoveWindow(display, window, x, y)" in move
    assert "x11_toplevel_of(" in move
    assert "x11_frame_extents(" in move
    header = _read(WINDOW_HH)
    assert "GHOST_TSuccess updateWindowDrag() override;" in header
    assert "GHOST_TSuccess endWindowDrag() override;" in header
    iface = _read(IWINDOW)
    assert "virtual GHOST_TSuccess updateWindowDrag()" in iface
    wm = _read(WM_WINDOW)
    pump = _function(wm, "static void mixar_pump_native_window_drags(")
    assert "Mixar_WindowUpdateNativeDrag" in pump
    assert "mixar_pump_native_window_drags(" in _function(wm, "void wm_window_events_process(")


def test_default_island_header_contains_eight_px_from_the_top():
    """xdotool (905,537) on a 678x240 island at (566,529) is 8px into
    the client. The HEADER slab is (panel_top - island_top) * width/1310
    and is aligned to the window top, so 8px is inside it. 20px is the
    safer empty-strip y (mid tab-strip, below the 14px corner clip)."""
    island_w = 1310
    island_top = 48
    card_y = 121
    header_h = 2 * (20 + 22)
    panel_y = card_y + header_h
    header_px = (panel_y - island_top) * (678 / island_w)
    assert header_px > 8
    assert 20 < header_px
    theme = _read(ROOT / "src/source/blender/editors/space_agent_bubble/agent_ui_theme.hh")
    assert "#define AGENT_ISLAND_W 1310" in theme
    assert "#define AGENT_ISLAND_TOP 48" in theme
    bubble = _read(BUBBLE_CC)
    assert "agent_bubble_header_for_drag(" in bubble


def test_linux_bubble_operators_drive_the_x11_followup():
    bubble = _read(BUBBLE_CC)
    update = _function(bubble, "static wmOperatorStatus mixar_bubble_window_update_drag_exec(")
    assert "Mixar_WindowUpdateNativeDrag" in update
    assert "return OPERATOR_CANCELLED;" in update
    end = _function(bubble, "static wmOperatorStatus mixar_bubble_window_end_drag_exec(")
    assert "Mixar_WindowEndNativeDrag" in end
    drag_op = _read(DRAG_OP)
    assert "def _linux_client_drag_followup()" in drag_op
    assert "def _event_hits_header(" in drag_op
    assert "INBETWEEN_MOUSEMOVE" in drag_op
    assert "event_timer_add" in drag_op
    assert "bubble_window_update_drag()" in drag_op
    assert "xdg_toplevel_move" in drag_op
    bootstrap = _read(ROOT / "src/scripts/mixar/bootstrap/agent_bubble_module.py")
    assert 'name="Agent Bubble Header"' in bootstrap
    assert "region_type='HEADER'" in bootstrap
