# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Record a process's on-screen windows front to back, with opacity.

What a user actually sees of the chat island depends on window stacking and
opacity, which the app's own screenshots cannot show (they read each window's
own picture). macOS: the bundled ``winwatch.swift`` (CGWindowList), compiled on
first use with ``swiftc``. Windows: user32 through ctypes (z-order walk,
layered-window alpha). Other platforms: unsupported, reported as such.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Win:
    id: int
    alpha: float
    w: int
    h: int
    x: int
    y: int


Frame = tuple  # (seconds_since_start, [Win, ...] front to back)
_ROW = re.compile(r"#(\d+) L-?\d+ a([\d.]+) (\d+)x(\d+)@(-?\d+),(-?\d+)")


def parse_swift_line(line: str):
    head, _, rest = line.strip().partition(" ")
    wins = [Win(int(m[0]), float(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5]))
            for m in _ROW.findall(rest)]
    return float(head), wins


class StackRecorder:
    """``start(seconds)`` then ``frames()``: one frame per change of the stack."""

    def __init__(self, pid: int, work_dir: Path):
        self.pid, self.work_dir = pid, work_dir
        self._frames: list = []
        self._proc = None
        self._thread = None
        self.supported, self.reason = self._probe()

    def _probe(self):
        if sys.platform == "darwin":
            if shutil.which("swiftc") is None:
                return False, "swiftc not found (install Xcode command line tools)"
            return True, ""
        if sys.platform == "win32":
            return True, ""
        return False, f"no window-stack reader for {sys.platform}"

    def _swift_binary(self) -> Path:
        binary = self.work_dir / "winwatch"
        if not binary.exists():
            subprocess.run(["swiftc", "-O", str(HERE / "winwatch.swift"), "-o", str(binary)],
                           check=True, capture_output=True, timeout=300)
        return binary

    def start(self, seconds: float) -> None:
        if not self.supported:
            return
        if sys.platform == "darwin":
            self._proc = subprocess.Popen([str(self._swift_binary()), str(self.pid), str(seconds)],
                                          stdout=subprocess.PIPE, text=True)
        else:
            self._thread = threading.Thread(target=self._poll_win32, args=(seconds,), daemon=True)
            self._thread.start()

    def frames(self) -> list:
        if self._proc is not None:
            out, _ = self._proc.communicate(timeout=120)
            self._frames = [parse_swift_line(l) for l in out.splitlines() if l.strip()]
            self._proc = None
        if self._thread is not None:
            self._thread.join(timeout=120)
            self._thread = None
        return list(self._frames)

    # --- Windows ----------------------------------------------------------------
    def _poll_win32(self, seconds: float) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        GW_HWNDNEXT, GWL_EXSTYLE, WS_EX_LAYERED, LWA_ALPHA = 2, -20, 0x80000, 0x2
        user32.GetTopWindow.restype = wintypes.HWND
        user32.GetWindow.restype = wintypes.HWND
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        get_style = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        get_style.restype = ctypes.c_ssize_t
        get_style.argtypes = [wintypes.HWND, ctypes.c_int]

        def snapshot():
            wins = []
            hwnd = user32.GetTopWindow(None)
            while hwnd:
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == self.pid and user32.IsWindowVisible(hwnd):
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    alpha = 1.0
                    if get_style(hwnd, GWL_EXSTYLE) & WS_EX_LAYERED:
                        key, byte_alpha, flags = wintypes.DWORD(), ctypes.c_ubyte(), wintypes.DWORD()
                        if user32.GetLayeredWindowAttributes(hwnd, ctypes.byref(key), ctypes.byref(byte_alpha),
                                                             ctypes.byref(flags)) and flags.value & LWA_ALPHA:
                            alpha = byte_alpha.value / 255.0
                    wins.append(Win(int(hwnd), round(alpha, 2), rect.right - rect.left,
                                    rect.bottom - rect.top, rect.left, rect.top))
                hwnd = user32.GetWindow(hwnd, GW_HWNDNEXT)
            return wins

        t0, last = time.monotonic(), None
        while time.monotonic() - t0 < seconds:
            wins = snapshot()
            if wins != last:
                self._frames.append((round(time.monotonic() - t0, 3), wins))
                last = wins
            time.sleep(0.01)


def describe(frames: list) -> str:
    return "\n".join("%7.3f  " % t + " > ".join(f"#{w.id} a{w.alpha:.2f} {w.w}x{w.h}@{w.x},{w.y}" for w in wins)
                     for t, wins in frames)
