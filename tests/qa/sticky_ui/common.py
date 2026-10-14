# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Shared helpers for the sticky-UI suite cases (no bpy here; code runs in-app via eval)."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

PLATFORM = {"darwin": "macos", "win32": "windows"}.get(sys.platform, sys.platform)


class NotApplicable(Exception):
    """The case cannot run on this platform; the message says why."""


@dataclass
class Ctx:
    qa: object          # scenarios/lib.QA
    app: object         # qa_launch.QAApp
    out: Path
    numbers: dict


def undo_mods(redo: bool = False) -> dict:
    """Cmd+Z / Cmd+Shift+Z on macOS, Ctrl+Z / Ctrl+Shift+Z elsewhere."""
    mods = {"oskey": True} if sys.platform == "darwin" else {"ctrl": True}
    if redo:
        mods["shift"] = True
    return mods


def main_view3d_window(qa):
    return qa.find(area_type="VIEW_3D")["widgets"][0]["window"]


def call_from_timer(qa, code: str, delay: float = 0.1) -> None:
    """Run ``code`` from a main-loop timer with the main window in context
    (operators that switch workspaces or start jobs need a real window)."""
    qa.eval("import bpy\n"
            "def _qa_timer_call():\n"
            "    win = bpy.context.window_manager.windows[0]\n"
            "    with bpy.context.temp_override(window=win, screen=win.screen):\n"
            + "".join("        " + line + "\n" for line in code.splitlines()) +
            "    return None\n"
            f"bpy.app.timers.register(_qa_timer_call, first_interval={delay})\n"
            "result = True")


JITTER_START = '''
import time, bpy
drv._jit = {"gaps": [], "ticks": 0, "last": None, "stop": False, "t0": time.perf_counter()}
def _qa_jitter():
    st = drv._jit
    now = time.perf_counter()
    if st["last"] is not None:
        gap = now - st["last"]
        if gap > 0.05:
            st["gaps"].append(round(gap * 1000))
    st["last"] = now
    st["ticks"] += 1
    return None if st["stop"] else 0.004
bpy.app.timers.register(_qa_jitter, first_interval=0.0)
result = True
'''

JITTER_READ = '''
import time
st = drv._jit
st["stop"] = True
result = {"seconds": round(time.perf_counter() - st["t0"], 2), "ticks": st["ticks"],
          "max_gap_ms": max(st["gaps"] or [0]), "gaps_over_100ms": sum(g > 100 for g in st["gaps"])}
'''


def jitter(qa, seconds: float) -> dict:
    """Main-loop responsiveness over ``seconds``: timer ticks and gaps over 50 ms."""
    qa.eval(JITTER_START)
    time.sleep(seconds)
    return qa.eval(JITTER_READ)


def mean_luminance(qa, png: Path) -> float:
    """Mean RGB of an image, computed in-app (Mixar's Python has numpy)."""
    return qa.eval(f'''
import bpy, numpy as np
img = bpy.data.images.load({str(png)!r}, check_existing=False)
px = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
img.pixels.foreach_get(px)
bpy.data.images.remove(img)
result = round(float(px.reshape(-1, 4)[:, :3].mean()), 4)
''')


def stall_seq(qa) -> int:
    return qa.eval("from mixar.modules.common.utils import stall_log\n"
                   "result = max([r['seq'] for r in stall_log.read_stalls()] or [0])")


def stalls_since(qa, seq: int) -> list:
    return qa.eval("from mixar.modules.common.utils import stall_log\n"
                   f"result = [{{'ms': r['ms'], 'culprit': stall_log.culprit(r)}} for r in stall_log.read_stalls(since_seq={seq})]")
