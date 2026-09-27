# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Per-tab script lanes for the main-thread executor (parallel scene tabs).

One FIFO per scene tab (chat session), served round-robin one script per
tick: a long build in one tab delays another tab's script by at most the
script executing right now. A worker lane's scripts queue under its tab
(``agent_ctx.chat_session_id``). A request's `prefetch` is a
ScriptAssetPrefetch handle (or None) — heavy texture-apply scripts start
downloading their assets the moment they are queued, and the tick holds
them at the head of THEIR tab's lane (UI responsive, other tabs unaffected)
until the cache is warm.

Thread contract: the WebSocket thread enqueues, the main thread serves and
drains. Every access to the lane table holds ``_lock``.
"""

from collections.abc import Callable
import queue
import threading
import time
from typing import Optional

from mixar.modules.common.agent_execution import pump
from mixar.modules.common.agent_execution.request import ExecutionRequest


class Lane:
    __slots__ = ("queue", "held")

    def __init__(self) -> None:
        self.queue: queue.Queue = queue.Queue()
        # Head request waiting for its asset prefetch: dequeued, not executed;
        # FIFO within the lane is preserved.
        self.held: Optional[ExecutionRequest] = None

    def pending(self) -> bool:
        return self.held is not None or not self.queue.empty()


_lanes: dict[str, Lane] = {}
_lock = threading.Lock()
MAX_QUEUED = 1000
_queued = 0  # requests across every lane (queued + held), under _lock
# Lane served by the previous tick: round-robin starts after it, and a
# different lane next means no 0.5 s breather.
_last_lane: str = ""


def lane_key(req: ExecutionRequest) -> str:
    """The tab a request queues under. Thread-safe: no bpy (the WebSocket
    thread enqueues), so a worker lane without an agent context keys by its
    own lane session — still one FIFO per agent."""
    return str((req.agent_ctx or {}).get("chat_session_id") or req.session_id or "")


def enqueue(req: ExecutionRequest) -> bool:
    """Queue ``req`` under its tab. False when the global cap is reached."""
    global _queued
    with _lock:
        if _queued >= MAX_QUEUED:
            return False
        _lanes.setdefault(lane_key(req), Lane()).queue.put_nowait(req)
        _queued += 1
    return True


def pending() -> bool:
    """True while any tab has a queued or held request."""
    with _lock:
        return any(lane.pending() for lane in _lanes.values())


def other_pending(served: str) -> bool:
    """True while a tab other than ``served`` has work."""
    with _lock:
        return any(key != served and lane.pending() for key, lane in _lanes.items())


def count() -> int:
    with _lock:
        return _queued


def take_next() -> tuple[Optional[ExecutionRequest], str, str]:
    """Advance the lanes by at most one request, round-robin from the lane
    after the last served one. Returns ``(request, status, lane)``: a request
    for READY / PREFETCH_*; HOLDING when every lane with work is waiting on
    a prefetch; EMPTY when nothing is queued. Main thread only."""
    global _queued
    holding = False
    with _lock:
        keys = list(_lanes)
        if _last_lane in keys:
            cut = keys.index(_last_lane) + 1
            keys = keys[cut:] + keys[:cut]
        for key in keys:
            lane = _lanes[key]
            req, lane.held, status = pump.take_next(lane.queue, lane.held)
            if status == pump.EMPTY:
                if not lane.pending():
                    _lanes.pop(key, None)
                continue
            if status == pump.HOLDING:
                holding = True
                continue
            _queued -= 1
            if not lane.pending():
                _lanes.pop(key, None)
            return req, status, key
    return None, (pump.HOLDING if holding else pump.EMPTY), ""


def switch_to(lane: str) -> Optional[str]:
    """Record ``lane`` as the one being served. Returns the previously served
    lane when the tick moved to a DIFFERENT tab (the caller logs the switch),
    else None."""
    global _last_lane
    if lane == _last_lane:
        return None
    previous = _last_lane
    _last_lane = lane
    return previous or None


def drain(mine: Callable[[ExecutionRequest], bool]) -> list[ExecutionRequest]:
    """Remove every queued or held request for which ``mine`` is true, from
    every lane, keeping the others in FIFO order. Returns the removed ones."""
    global _queued
    dropped: list[ExecutionRequest] = []
    with _lock:
        for key, lane in list(_lanes.items()):
            kept = []
            while True:
                try:
                    req = lane.queue.get_nowait()
                except queue.Empty:
                    break
                (dropped if mine(req) else kept).append(req)
            for req in kept:
                lane.queue.put(req)
            if lane.held is not None and mine(lane.held):
                dropped.append(lane.held)
                lane.held = None
            if not lane.pending():
                _lanes.pop(key, None)
        _queued -= len(dropped)
    return dropped


def clear() -> None:
    """Forget every tab's lane, prefetch-held requests included."""
    global _queued, _last_lane
    with _lock:
        _lanes.clear()
        _queued = 0
        _last_lane = ""


def held(lane: str) -> Optional[ExecutionRequest]:
    """The request parked at the head of ``lane`` (tests and diagnostics)."""
    with _lock:
        entry = _lanes.get(lane)
        return entry.held if entry is not None else None


class LaneQueue:
    """A ``queue.Queue``-shaped view over the lanes for the headless worker.

    ``bpy.app.timers`` never fire under ``--background``, so the sandbox
    worker (``headless/headless_main.py``) pumps requests itself through the
    shared ``pump.take_next``, which only knows ``get`` / ``get_nowait``.
    This hands it the next READY (or prefetch-failed) request across every
    lane; a lane still waiting on a prefetch keeps its request and reads as
    empty, exactly as the main-thread tick treats it.
    """

    _POLL_S = 0.02

    def get_nowait(self) -> ExecutionRequest:
        req, _status, lane = take_next()
        if req is None:
            raise queue.Empty
        switch_to(lane)
        return req

    def get(self, timeout: Optional[float] = None) -> ExecutionRequest:
        deadline = time.monotonic() + (timeout or 0.0)
        while True:
            try:
                return self.get_nowait()
            except queue.Empty:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(self._POLL_S)

    def empty(self) -> bool:
        return count() == 0
