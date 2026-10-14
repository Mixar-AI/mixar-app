# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Python stall watchdog: captures the main thread's stack once per stall, joins it to
the native record on the iteration number, stays quiet while the loop moves."""

import json
import sys
import threading
from pathlib import Path

from mixar.modules.common.utils import stall_log, stall_watchdog

ROOT = Path(__file__).resolve().parents[1]


class FakeClockStop:
    """``stop.wait`` advances a fake clock by one poll and ends after ``ticks`` polls."""

    def __init__(self, ticks, poll_s):
        self.now, self.ticks, self.poll_s = 0.0, ticks, poll_s

    def wait(self, timeout):
        self.now += self.poll_s
        self.ticks -= 1
        return self.ticks < 0

    def clock(self):
        return self.now


def test_one_stack_per_stall_then_repeats(tmp_path):
    lines = []
    it = {"n": 1}
    frame = sys._getframe()                     # a real frame to walk
    stop = FakeClockStop(ticks=400, poll_s=0.05)   # 20 s of fake time

    def iteration():
        # Moves for 1 s, stalls 7 s, moves for 1 s, stalls 2 s, moves.
        t = stop.now
        if t < 1.0 or 8.0 <= t < 9.0 or t >= 11.0:
            it["n"] += 1
        return it["n"]

    written = stall_watchdog.run_watchdog(
        iteration, str(tmp_path / "s.jsonl"), stop, threshold_s=0.5, poll_s=0.05,
        clock=stop.clock, frames_fn=lambda: {threading.get_ident(): frame},
        main_ident=threading.get_ident(), write_fn=lambda p, line: lines.append(json.loads(line)))
    assert written == len(lines) == 3
    first, repeat, second = lines
    assert first["kind"] == "py_stack" and first["repeat"] is False and 500 <= first["stalled_ms"] <= 600
    assert repeat["repeat"] is True and repeat["it"] == first["it"] and repeat["stalled_ms"] >= 5500
    assert second["repeat"] is False and second["it"] != first["it"]
    assert any("test_stall_watchdog.py" in f and "test_one_stack_per_stall" in f for f in first["stack"])


def test_native_stall_gives_empty_stack():
    assert stall_watchdog.main_thread_stack(frames_fn=lambda: {}, main_ident=1) == []
    line = json.loads(stall_watchdog.stack_line(7, 0.812, [], False))
    assert line == {"t": line["t"], "kind": "py_stack", "it": 7, "stalled_ms": 812, "repeat": False, "stack": []}


def test_frame_format_shortens_mixar_paths():
    assert stall_watchdog.format_frame("/app/x/scripts/mixar/modules/a/b.py", 12, "tick") == "mixar/modules/a/b.py:12 tick"
    assert stall_watchdog.format_frame("/usr/lib/python3/threading.py", 3, "wait") == "threading.py:3 wait"


def test_reader_joins_stacks_to_records(tmp_path, monkeypatch):
    path = tmp_path / "stalls.jsonl"
    path.write_text(
        '{"t":"x","kind":"py_stack","it":41,"stalled_ms":600,"repeat":false,"stack":["mixar/a.py:1 tick","mixar/store.py:9 cleanup"]}\n'
        '{"t":"x","up":1,"seq":1,"it":41,"ms":5400,"ph":[0,0,5400,0],"job":0,"scopes":1,"top":[{"k":"timer","n":"m.tick","ms":5399,"d":0}],"n":{}}\n'
        '{"t":"x","up":2,"seq":2,"it":90,"ms":300,"ph":[0,0,0,300],"job":0,"scopes":0,"top":[],"n":{}}\n')
    monkeypatch.setenv("MIXAR_STALL_LOG", str(path))
    records = stall_log.read_stalls()
    assert [r["seq"] for r in records] == [1, 2]
    assert stall_log.python_frame(records[0]) == "mixar/store.py:9 cleanup"
    assert stall_log.python_frame(records[1]) is None and "py_stacks" not in records[1]
    assert len(stall_log.read_stacks()) == 1


def test_wiring_is_pinned():
    cc = (ROOT / "src/source/blender/python/intern/bpy_mixar_stall_watchdog.cc").read_text()
    assert '"_mixar_main_loop_iteration"' in cc and "Mixar_stall_iteration_count()" in cc
    aud = (ROOT / "src/source/blender/python/intern/bpy_audaspace.cc").read_text()
    assert "mixar_stall_watchdog_register(module);" in aud
    mon = (ROOT / "src/source/blender/windowmanager/intern/wm_stall_monitor.cc").read_text()
    assert "g_iteration.fetch_add(1, std::memory_order_relaxed);" in mon and '\\"it\\":%llu' in mon
    boot = (ROOT / "src/scripts/mixar/bootstrap/stall_watchdog_module.py").read_text()
    assert '"_mixar_main_loop_iteration"' in boot and "stall_watchdog.start(" in boot
    assert "bpy_mixar_stall_watchdog.cc" in (ROOT / "src/source/blender/python/intern/CMakeLists.txt").read_text()
