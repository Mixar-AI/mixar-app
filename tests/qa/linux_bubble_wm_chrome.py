# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Prove Agent Bubble X11 chrome against a live window manager.

Replays Mixar's GHOST sequence, including the rounded bounding shape:

* broken: map a DIALOG, apply a client shape, THEN write 5-long Motif
  (the 77ec63b path). xfwm4 ignores Motif decorations once shaped.
* fixed:  5-long Motif decorations=0 BEFORE map, then the same shape.

Prints xprop and drags the fixed window with xdotool. Run under Xvfb
plus a reparenting WM (xfwm4, openbox). No Mixar binary required.

    python3 tests/qa/linux_bubble_wm_chrome.py
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import time

xlib = ctypes.CDLL("libX11.so.6")
xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
xlib.XOpenDisplay.restype = ctypes.c_void_p
xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
xlib.XDefaultRootWindow.restype = ctypes.c_ulong
xlib.XDefaultScreen.argtypes = [ctypes.c_void_p]
xlib.XDefaultScreen.restype = ctypes.c_int
xlib.XRootWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
xlib.XRootWindow.restype = ctypes.c_ulong
xlib.XCreateSimpleWindow.argtypes = [
    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
    ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_ulong,
]
xlib.XCreateSimpleWindow.restype = ctypes.c_ulong
xlib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
xlib.XInternAtom.restype = ctypes.c_ulong
xlib.XChangeProperty.argtypes = [
    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
    ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int,
]
xlib.XSetTransientForHint.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
xlib.XStoreName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_char_p]
xlib.XMapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
xlib.XFlush.argtypes = [ctypes.c_void_p]
xlib.XSelectInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long]
xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]

PropModeReplace = 0
XA_ATOM = 4
XA_CARDINAL = 6
StructureNotifyMask = 1 << 17


class MotifHints(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_long),
        ("functions", ctypes.c_long),
        ("decorations", ctypes.c_long),
        ("input_mode", ctypes.c_long),
        ("status", ctypes.c_long),
    ]


def xprop(wid: int, *names: str) -> str:
    return subprocess.check_output(["xprop", "-id", hex(wid), *names], text=True)


def frame_extents(wid: int) -> tuple[int, ...] | None:
    try:
        text = xprop(wid, "_NET_FRAME_EXTENTS")
    except subprocess.CalledProcessError as exc:
        text = exc.output or str(exc)
    if "not found" in text or "no such atom" in text:
        return None
    match = re.search(r"= (-?\d+), (-?\d+), (-?\d+), (-?\d+)", text)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def window_type(wid: int) -> str:
    return xprop(wid, "_NET_WM_WINDOW_TYPE").strip()


def position(wid: int) -> tuple[int, int]:
    info = subprocess.check_output(["xwininfo", "-id", hex(wid)], text=True)
    return tuple(
        int(re.search(rf"Absolute upper-left {axis}:\s+(-?\d+)", info).group(1))
        for axis in ("X", "Y")
    )


class ClientMessage(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", ctypes.c_long * 5),
    ]


xlib.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p]
SubstructureRedirectMask = 1 << 20
SubstructureNotifyMask = 1 << 19
NorthWestGravity = 1


def write_motif(display, wid: int, flags: int, functions: int, decorations: int, nitems: int) -> None:
    motif_atom = xlib.XInternAtom(display, b"_MOTIF_WM_HINTS", 0)
    hints = MotifHints(flags=flags, functions=functions, decorations=decorations,
                       input_mode=0, status=0)
    xlib.XChangeProperty(display, wid, motif_atom, motif_atom, 32, PropModeReplace,
                         ctypes.byref(hints), nitems)
    xlib.XFlush(display)


class XRectangle(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_short),
        ("y", ctypes.c_short),
        ("width", ctypes.c_ushort),
        ("height", ctypes.c_ushort),
    ]


def apply_shape(display, wid: int, width: int = 400, height: int = 230) -> bool:
    """Install a Mixar-like bounding clip. xfwm4 then sets HAS_SHAPE."""
    try:
        xext = ctypes.CDLL("libXext.so.6")
    except OSError:
        return False
    ShapeBounding = 0
    ShapeSet = 0
    rect = XRectangle(x=2, y=2, width=width - 4, height=height - 4)
    xext.XShapeCombineRectangles.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ]
    xext.XShapeCombineRectangles(
        display, wid, ShapeBounding, 0, 0, ctypes.byref(rect), 1, ShapeSet, 0)
    xlib.XFlush(display)
    return True


def make_window(display, root, transient_for, name: bytes, *, motif_before_map: bool) -> int:
    # Top-level, not a child of the host: WMs only decorate real clients.
    # Match GHOST: TYPE_DIALOG + transient, then map (setDialogHints first).
    wid = xlib.XCreateSimpleWindow(display, root, 120, 140, 400, 230, 0, 0, 0x303030)
    atom_type = xlib.XInternAtom(display, b"_NET_WM_WINDOW_TYPE", 0)
    atom_dialog = xlib.XInternAtom(display, b"_NET_WM_WINDOW_TYPE_DIALOG", 0)
    dialog = ctypes.c_ulong(atom_dialog)
    xlib.XChangeProperty(display, wid, atom_type, XA_ATOM, 32, PropModeReplace,
                         ctypes.byref(dialog), 1)
    xlib.XSetTransientForHint(display, wid, transient_for)
    if motif_before_map:
        # New Mixar: decorations=0 before XMapWindow.
        write_motif(display, wid, 0x3, 0x26, 0, 5)
    else:
        # Pre-map dialog functions only — GHOST setDialogHints without custom chrome.
        write_motif(display, wid, 0x1, 0x36, 0, 4)
    xlib.XStoreName(display, wid, name)
    xlib.XSelectInput(display, wid, StructureNotifyMask)
    xlib.XMapWindow(display, wid)
    xlib.XFlush(display)
    return wid


def ewmh_move(display, root, wid: int, x: int, y: int) -> None:
    event = ClientMessage(type=33, display=display, window=wid,
                          message_type=xlib.XInternAtom(display, b"_NET_MOVERESIZE_WINDOW", 0),
                          format=32,
                          data=(ctypes.c_long * 5)(
                              NorthWestGravity | (1 << 8) | (1 << 9) | (1 << 12),
                              x, y, 0, 0))
    xlib.XSendEvent(display, root, 0, SubstructureRedirectMask | SubstructureNotifyMask,
                    ctypes.byref(event))
    xlib.XFlush(display)


def net_wm_moveresize(display, root, wid: int, root_x: int, root_y: int) -> None:
    """Same ClientMessage Mixar sends from beginWindowDrag after XI ungrab."""
    event = ClientMessage(type=33, display=display, window=wid,
                          message_type=xlib.XInternAtom(display, b"_NET_WM_MOVERESIZE", 0),
                          format=32,
                          data=(ctypes.c_long * 5)(root_x, root_y, 8, 1, 1))
    xlib.XSendEvent(display, root, 0, SubstructureRedirectMask | SubstructureNotifyMask,
                    ctypes.byref(event))
    xlib.XFlush(display)


def run(cmd: list[str]) -> str:
    print("+", " ".join(cmd), flush=True)
    text = subprocess.check_output(cmd, text=True)
    print(text, end="" if text.endswith("\n") else "\n", flush=True)
    return text


def drag(display, root, wid: int) -> dict:
    before = position(wid)
    run(["xdotool", "windowactivate", "--sync", hex(wid)])
    run(["xdotool", "getwindowgeometry", hex(wid)])
    # 8px into the client at the horizontal center — the user's Debian
    # xdotool press. The Mixar HEADER starts at y=0 and is ~81px tall
    # on a 678-wide island; 8px is inside it. 20px is the safer empty
    # tab-strip y if a replay wants to stay off the 14px corner clip.
    x, y = before[0] + 200, before[1] + 8
    run(["xdotool", "mousemove", "--sync", str(x), str(y)])
    run(["xdotool", "mousedown", "1"])
    # Mixar beginWindowDrag: ungrab (harness has no grab) then this.
    net_wm_moveresize(display, root, wid, x, y)
    time.sleep(0.05)
    for step in range(1, 11):
        run(["xdotool", "mousemove_relative", "--sync", "--", "8", "5"])
        time.sleep(0.03)
    run(["xdotool", "mouseup", "1"])
    time.sleep(0.3)
    after = position(wid)
    run(["xdotool", "getwindowgeometry", hex(wid)])
    wm_owned = after != before
    if not wm_owned:
        # Fallback Mixar also uses: XQueryPointer + _NET_MOVERESIZE_WINDOW.
        run(["xdotool", "mousemove", "--sync", str(x), str(y)])
        run(["xdotool", "mousedown", "1"])
        for step in range(1, 5):
            ewmh_move(display, root, wid, before[0] + 24 * step, before[1] + 16 * step)
            time.sleep(0.05)
        run(["xdotool", "mouseup", "1"])
        time.sleep(0.3)
        after = position(wid)
    return {
        "before": before,
        "after": after,
        "moved": after != before,
        "wm_owned_moveresize": wm_owned,
    }


def main() -> int:
    display = xlib.XOpenDisplay(None)
    if not display:
        print("no DISPLAY", file=sys.stderr)
        return 2
    screen = xlib.XDefaultScreen(display)
    root = xlib.XRootWindow(display, screen)
    host = xlib.XCreateSimpleWindow(display, root, 0, 0, 800, 600, 0, 0, 0x101010)
    xlib.XStoreName(display, host, b"Mixar host")
    xlib.XMapWindow(display, host)
    xlib.XFlush(display)
    time.sleep(0.3)

    actual_root = xlib.XDefaultRootWindow(display)
    supporting = run(["xprop", "-root", "_NET_SUPPORTING_WM_CHECK", "_NET_WM_NAME"])
    control = xlib.XCreateSimpleWindow(display, actual_root, 40, 40, 240, 160, 1, 0, 0x445566)
    xlib.XStoreName(display, control, b"control-no-motif")
    xlib.XMapWindow(display, control)
    xlib.XFlush(display)
    broken = make_window(display, actual_root, host, b"broken-shape-then-motif",
                         motif_before_map=False)
    fixed = make_window(display, actual_root, host, b"fixed-motif-before-map",
                        motif_before_map=True)
    time.sleep(0.8)
    # 77ec63b Mixar: getClientBounds installed the rounded clip, then Motif.
    shaped = apply_shape(display, broken)
    write_motif(display, broken, 0x3, 0x26, 0, 5)
    # Fixed Mixar: Motif already on the window at map; shape comes after.
    apply_shape(display, fixed)
    time.sleep(1.0)

    print("+ xprop -id", hex(control), "_NET_FRAME_EXTENTS", flush=True)
    print(xprop(control, "_NET_FRAME_EXTENTS"), flush=True)
    print("+ xprop -id", hex(broken), "_MOTIF_WM_HINTS _NET_FRAME_EXTENTS _NET_WM_WINDOW_TYPE", flush=True)
    print(xprop(broken, "_MOTIF_WM_HINTS", "_NET_FRAME_EXTENTS", "_NET_WM_WINDOW_TYPE"), flush=True)
    print("+ xprop -id", hex(fixed), "_MOTIF_WM_HINTS _NET_FRAME_EXTENTS _NET_WM_WINDOW_TYPE", flush=True)
    print(xprop(fixed, "_MOTIF_WM_HINTS", "_NET_FRAME_EXTENTS", "_NET_WM_WINDOW_TYPE"), flush=True)

    result = {
        "wm": os.environ.get("MIXAR_QA_WM", "unknown"),
        "supporting_wm": supporting.strip(),
        "shaped": shaped,
        "control_no_motif": {"extents": frame_extents(control)},
        "broken": {
            "motif": xprop(broken, "_MOTIF_WM_HINTS").strip(),
            "type": window_type(broken),
            "extents": frame_extents(broken),
        },
        "fixed": {
            "motif": xprop(fixed, "_MOTIF_WM_HINTS").strip(),
            "type": window_type(fixed),
            "extents": frame_extents(fixed),
        },
    }
    result["fixed"]["drag"] = drag(display, actual_root, fixed)
    print(result)

    control_extents = result["control_no_motif"]["extents"]
    broken_extents = result["broken"]["extents"]
    fixed_extents = result["fixed"]["extents"]
    wm_decorates = control_extents is not None and any(control_extents)
    broken_framed = broken_extents is not None and any(broken_extents)
    frameless = fixed_extents is None or fixed_extents == (0, 0, 0, 0)
    moved = result["fixed"]["drag"]["moved"]
    if not wm_decorates:
        print("WM is not decorating ordinary windows", result, file=sys.stderr)
        xlib.XCloseDisplay(display)
        return 1
    if not frameless:
        print("fixed window still has a frame", result["fixed"], file=sys.stderr)
        xlib.XCloseDisplay(display)
        return 1
    if not moved:
        print("fixed window did not move", result["fixed"]["drag"], file=sys.stderr)
        xlib.XCloseDisplay(display)
        return 1
    if broken_framed:
        print("shape-then-motif stayed decorated (xfwm4 HAS_SHAPE skip)", flush=True)
    xlib.XCloseDisplay(display)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
