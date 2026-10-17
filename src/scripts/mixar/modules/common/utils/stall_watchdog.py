# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Python stack capture for main-thread stalls (the native monitor's blind spot).

The native stall monitor (``WM_stall_monitor.hh``) names the breadcrumb that held the
loop: an operator, a timer, a handler. A timer breadcrumb names the tick, not the call
inside it; the 5.4 s operation-history prune hid behind the executor's tick that way.

A worker thread polls the main loop's iteration counter. When it stops moving for
longer than the threshold the thread reads the main thread's Python frames through
``sys._current_frames()`` and appends one ``py_stack`` line to the same ``stalls.jsonl``
with the iteration number, so a record and its stack join on ``it``. An empty stack
means the main thread was not in Python at all: the stall is native.

Limits: the capture needs the GIL. Python code releases it every switch interval and
around blocking calls, so a Python stall is caught while it runs. A ``bpy`` call made
from Python holds the GIL until it returns, so its stack lands right after the call,
on the statement that follows it, still inside the function that made it.

No ``bpy`` here: everything the thread needs is passed in at start.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Callable, Optional

DEFAULT_THRESHOLD_S = 0.5
POLL_S = 0.05
REPEAT_S = 5.0          # a stall that keeps going gets another stack this often
MAX_FRAMES = 24
MAX_LINE_CHARS = 8000
_ROOT_MARKER = os.sep + "mixar" + os.sep


def format_frame(filename: str, lineno: int, name: str) -> str:
    """``mixar/...:line name`` for Mixar code, basename for everything else."""
    pos = filename.rfind(_ROOT_MARKER)
    short = filename[pos + 1:] if pos >= 0 else os.path.basename(filename)
    return f"{short.replace(os.sep, '/')}:{lineno} {name}"


def capture_stack(frame) -> list[str]:
    """Innermost-last frames of ``frame``'s stack, at most ``MAX_FRAMES``, no source lookup."""
    if frame is None:
        return []
    summary = traceback.StackSummary.extract(traceback.walk_stack(frame), lookup_lines=False)
    frames = [format_frame(f.filename, f.lineno or 0, f.name) for f in summary]
    frames.reverse()                      # walk_stack yields innermost first
    return frames[-MAX_FRAMES:]


def main_thread_stack(frames_fn=sys._current_frames, main_ident: Optional[int] = None) -> list[str]:
    ident = threading.main_thread().ident if main_ident is None else main_ident
    return capture_stack(frames_fn().get(ident))


def stack_line(it: int, stalled_s: float, stack: list[str], repeat: bool, now_utc=None) -> str:
    stamp = (now_utc or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = json.dumps({"t": stamp, "kind": "py_stack", "it": int(it), "stalled_ms": int(stalled_s * 1000),
                       "repeat": bool(repeat), "stack": stack}, ensure_ascii=False)
    if len(line) > MAX_LINE_CHARS:
        line = json.dumps({"t": stamp, "kind": "py_stack", "it": int(it), "stalled_ms": int(stalled_s * 1000),
                           "repeat": bool(repeat), "stack": stack[-6:], "truncated": True}, ensure_ascii=False)
    return line + "\n"


def append_line(path: str, line: str) -> None:
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


def run_watchdog(iteration_fn: Callable[[], int], log_path: str, stop: threading.Event, *,
                 threshold_s: float = DEFAULT_THRESHOLD_S, poll_s: float = POLL_S,
                 clock: Callable[[], float] = time.monotonic, frames_fn=sys._current_frames,
                 main_ident: Optional[int] = None, write_fn: Callable[[str, str], None] = append_line) -> int:
    """Poll until ``stop`` is set; returns the number of stack lines written.

    One capture per stall, then another every ``REPEAT_S`` while the same iteration is
    still stuck (``repeat`` true), so a long stall shows whether it moved on.
    """
    written = 0
    last_it = iteration_fn()
    last_change = clock()
    captured_it = None
    next_repeat = 0.0
    while not stop.wait(poll_s):
        it = iteration_fn()
        now = clock()
        if it != last_it:
            last_it, last_change, captured_it = it, now, None
            continue
        stalled = now - last_change
        if stalled < threshold_s:
            continue
        repeat = captured_it == it
        if repeat and now < next_repeat:
            continue
        stack = main_thread_stack(frames_fn, main_ident)
        write_fn(log_path, stack_line(it, stalled, stack, repeat))
        written += 1
        captured_it = it
        next_repeat = now + REPEAT_S
    return written


def start(iteration_fn: Callable[[], int], log_path: str, *, threshold_s: float = DEFAULT_THRESHOLD_S):
    """Start the daemon thread; returns ``(thread, stop_event)``."""
    stop = threading.Event()
    thread = threading.Thread(target=run_watchdog, args=(iteration_fn, log_path, stop),
                              kwargs={"threshold_s": threshold_s},
                              name="mixar-stall-watchdog", daemon=True)
    thread.start()
    return thread, stop
