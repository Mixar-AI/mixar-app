# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""3.15: the agent halo breathes on its own.

The halo is painted in the viewport's overlay pass and advanced by a frame
request about 20 times a second. A request that only tags the viewport region
was dropped by Blender's window-redraw test, so the main window repainted (and
the halo moved) only when something else redrew it. Screenshots cannot show
this: taking one repaints the window. The stall log, with its threshold near
zero, records every main-loop pass and how many windows and regions it drew;
a window repaint with no region redraw is a composite, which is what the
halo needs. Launched with ``MIXAR_STALL_THRESHOLD_MS`` (``run_suite.CASE_ENV``).
"""

from __future__ import annotations

import json
import time

from cases_chat import FAKE_TURN, _start_fake_turn

_SEQ = ("from mixar.modules.common.utils import stall_log\n"
        "result = max([r['seq'] for r in stall_log.read_stalls()] or [0])")


def _composites(app, seq0: int, seq1: int) -> dict:
    """Window repaints that redrew no region, over the passes in (seq0, seq1]."""
    passes = composites = 0
    for line in app.stall_log.read_text().splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not seq0 < rec.get("seq", -1) <= seq1:
            continue
        passes += 1
        kinds = rec.get("n", {})
        composites += max(0, kinds.get("window", 0) - kinds.get("draw", 0))
    return {"passes": passes, "composites": composites}


def _measure(qa, app, seconds: float) -> dict:
    seq0 = qa.eval(_SEQ)
    time.sleep(seconds)
    return _composites(app, seq0, qa.eval(_SEQ))


def halo_breathes(c):
    qa, app = c.qa, c.app
    idle = _measure(qa, app, 3.0)
    _start_fake_turn(qa)
    time.sleep(0.5)
    turn = _measure(qa, app, 4.0)
    active = qa.eval("import bpy\nresult = bpy.context.window_manager.get('mixar_agent_halo_active')")
    seq0 = qa.eval(_SEQ)
    qa.eval(FAKE_TURN.format(busy=False))
    time.sleep(1.5)
    after = _composites(app, seq0, qa.eval(_SEQ))
    c.numbers.update(idle_composites_3s=idle["composites"], turn_composites_4s=turn["composites"],
                     composites_after_turn=after["composites"], halo_active=active)
    assert turn["passes"] > 100, f"stall log recorded only {turn['passes']} passes (threshold env missing?)"
    assert active == 1, "halo not active during the fake turn"
    # 20 frame requests a second: 80 in 4 s. Before the fix: 0.
    assert turn["composites"] >= 40, \
        f"main window repainted {turn['composites']} times in 4 s of a turn: the halo is frozen"
    assert after["composites"] >= 1, "the halo's last frame was never cleared after the turn"
