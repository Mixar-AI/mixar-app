# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Async script execution queue for main thread execution.

Architecture:
- Request queue: ExecutionRequest values from the WebSocket thread
- Timer polls request queue, executes ONE script per tick
- Responses pushed directly to WebSocket client's outbound queue (thread-safe)

This approach is non-blocking and prevents UI freezes by:
1. WebSocket thread queues requests (never executes scripts)
2. Timer on main thread polls and executes ONE script per tick
3. Responses are sent directly via client.queue_response() to avoid
   cross-thread queue polling (which caused segfaults in Blender's embedded Python)

The take/execute/respond sequence lives in
``mixar.modules.common.agent_execution.pump`` and is shared with the headless
worker pump (``headless/headless_main.py``); scene routing and history live in
``main_thread_routing``.
"""

from collections.abc import Callable
from mixar.config.logging_config import get_logger
import queue
import threading
import time
from typing import Optional

import bpy

from mixar.modules.common.agent_execution import pump
from mixar.modules.common.agent_execution.request import ExecutionEnvelope, ExecutionRequest

from .executor import get_executor
from .main_thread_routing import archive_history, restore_after, route_request
from .script_prefetch import maybe_start_prefetch
from ..constants import TIMER_INTERVAL

logger = get_logger(__name__)

# Provenance-id resolution moved to the shared pump; kept importable here for
# existing callers/tests.
_resolve_agent_context_ids = pump.resolve_agent_context_ids

# One FIFO per scene tab (chat session), served round-robin one script per
# tick: a long build in one tab delays another tab's script by at most the
# script executing right now (parallel scene tabs, Phase 2). A worker lane's
# scripts queue under its tab (``agent_ctx.chat_session_id``). A request's
# `prefetch` is a ScriptAssetPrefetch handle (or None) — heavy texture-apply
# scripts start downloading their assets the moment they are queued, and the
# tick holds them at the head of THEIR tab's lane (UI responsive, other tabs
# unaffected) until the cache is warm.
class _Lane:
    __slots__ = ("queue", "held")

    def __init__(self) -> None:
        self.queue: queue.Queue = queue.Queue()
        # Head request waiting for its asset prefetch: dequeued, not executed;
        # FIFO within the lane is preserved.
        self.held: Optional[ExecutionRequest] = None

    def pending(self) -> bool:
        return self.held is not None or not self.queue.empty()


_lanes: dict[str, _Lane] = {}
# The WebSocket thread enqueues, the main thread serves and flushes.
_lanes_lock = threading.Lock()
_MAX_QUEUED = 1000
_queued = 0  # requests across every lane (queued + held), under _lanes_lock
# Lane served by the previous tick: round-robin starts after it, and a
# different lane next means no 0.5 s breather.
_last_lane: str = ""


def _lane_key(req: ExecutionRequest) -> str:
    """The tab a request queues under. Thread-safe: no bpy (the WebSocket
    thread enqueues), so a worker lane without an agent context keys by its
    own lane session — still one FIFO per agent."""
    return str((req.agent_ctx or {}).get("chat_session_id") or req.session_id or "")


def _enqueue(req: ExecutionRequest) -> bool:
    global _queued
    with _lanes_lock:
        if _queued >= _MAX_QUEUED:
            return False
        _lanes.setdefault(_lane_key(req), _Lane()).queue.put_nowait(req)
        _queued += 1
    return True


def _pending() -> bool:
    with _lanes_lock:
        return any(lane.pending() for lane in _lanes.values())


def _other_lane_pending(served: str) -> bool:
    with _lanes_lock:
        return any(key != served and lane.pending() for key, lane in _lanes.items())


def _take_next() -> tuple[Optional[ExecutionRequest], str, str]:
    """Advance the lanes by at most one request, round-robin from the lane
    after the last served one. Returns ``(request, status, lane)``: a request
    for READY / PREFETCH_*; HOLDING when every lane with work is waiting on
    a prefetch; EMPTY when nothing is queued. Main thread only."""
    global _queued
    holding = False
    with _lanes_lock:
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

# Timer state. _timer_active is read/written from both the WebSocket thread
# (queue_script_request) and the main thread (_process_one_request); every
# access must hold _timer_lock — an unsynchronized check-then-clear can
# strand a queued script, and its unsent tool response then hangs the
# backend's agent turn until timeout.
_timer_lock = threading.Lock()
_timer_active = False
_timer_fn = None  # the closure currently registered with bpy.app.timers
_shutdown_requested = False

# Execution gate: defer script running so the chat UI can render planning text
_execution_gate_until: float = 0.0

# Render jobs never gate scripts. The agent's preview render runs on Blender's
# job thread and evaluates its OWN depsgraph, so the agent keeps working (and
# the user keeps clicking) while it runs — exactly as a user's F12 does with
# Lock Interface off. The tool call that started it is held open by
# preview_deferral (a timer poller), never by this queue. A hold here (3.4.2) parked
# the head-of-queue script while Blender reported a RENDER job alive, for up
# to 20 s, then failed it — which stalled every turn for the whole render (the
# render lane's own post-render verification script included) and turned any
# render longer than a quick EEVEE preview into a guaranteed failed turn.
# Removed in 3.4.4; do not bring it back for ANY job type. Full write-up and
# the pinning tests: docs/render-job-contract.md.

# In-flight script marker for the blender.liveness probe. Set on the main
# thread around ScriptExecutor.execute() and read from the WebSocket thread:
# a long bpy op holds the GIL so the probe can ONLY be answered while the
# C-level call releases it — which is exactly what "busy, not frozen" means.
# Lock-guarded because it crosses threads.
_inflight_lock = threading.Lock()
_inflight: Optional[dict] = None


def _set_inflight(tool_name: str, request_id: str, session_id: str) -> None:
    global _inflight
    with _inflight_lock:
        _inflight = {
            "tool_name": tool_name,
            "request_id": request_id,
            "session_id": session_id,
            "_started": time.monotonic(),
        }


def _clear_inflight() -> None:
    global _inflight
    with _inflight_lock:
        _inflight = None


def get_inflight_script() -> Optional[dict]:
    """Snapshot of the currently executing agent script (thread-safe).

    Returns None when the main thread is idle; otherwise the tool name,
    request id, session id and elapsed seconds — consumed by the
    blender.liveness handler answered on the WebSocket thread.
    """
    with _inflight_lock:
        info = dict(_inflight) if _inflight else None
    if info is None:
        # A held-open preview tool call counts as busy too: the main thread is
        # idle, but the backend is still waiting on that request id.
        from .preview_deferral import get_pending_inflight
        return get_pending_inflight()
    info["elapsed_s"] = round(time.monotonic() - info.pop("_started"), 1)
    return info


def _send_error_response(request_id: str, error: str, error_type: str = "") -> None:
    """Reply to a script request with a failure result (mirrors the stale-session
    path). No-op for notifications or when no client is connected."""
    from .jsonrpc_client import get_jsonrpc_client
    result = {"success": False, "error": error}
    if error_type:
        result["error_type"] = error_type
    pump.respond(get_jsonrpc_client(), ExecutionRequest(request_id, ""), result)


def queue_script_request(
    script: str,
    request_id: str,
    tool_name: str = "unknown",
    session_id: str = "",
    agent_ctx: Optional[dict] = None,
    envelope: Optional[dict] = None,
) -> None:
    """
    Queue a script for execution on main thread (non-blocking).

    Called from WebSocket thread. The script will be executed on the
    main thread by the timer callback, and the response will be sent
    directly via the WebSocket client's outbound queue.

    Args:
        script: Python script to execute
        request_id: JSON-RPC request ID for response matching
        tool_name: Name of the tool being executed
        session_id: Target session ID for scene routing
        agent_ctx: Explicit backend chat session and turn identifiers, if sent
        envelope: Optional v3 task envelope (carried through; not admitted here)
    """
    global _execution_gate_until
    if _shutdown_requested:
        # Warning, not debug: if this fires outside real shutdown the backend
        # will time out waiting for the never-sent response.
        logger.warning(
            "Dropping script request during shutdown (%s, id: %s)",
            tool_name, request_id,
        )
        return

    # Gate: give SSE events (planning text) time to arrive before execution
    _execution_gate_until = max(_execution_gate_until, time.monotonic() + 0.05)
    logger.debug(f"Queuing script request (id: {request_id}), initial gate set")
    # Start downloading the script's texture assets NOW, on this (WebSocket)
    # thread's watch — by the time the script reaches the front of the queue
    # its images are usually already on disk, so execution never waits on the
    # network while holding the main thread.
    req = ExecutionRequest(
        request_id=request_id,
        script=script,
        tool_name=tool_name,
        session_id=session_id,
        agent_ctx=agent_ctx,
        prefetch=maybe_start_prefetch(script, tool_name),
        envelope=ExecutionEnvelope.parse(envelope),
    )
    if not _enqueue(req):
        logger.warning(f"Request queue full, dropping {tool_name} (id: {request_id})")
        return
    _ensure_timer_running()


def has_pending_requests() -> bool:
    """Check if there are pending script requests (queued or held, any tab)."""
    return _pending()


def gate_execution(delay: float = 0.05) -> None:
    """Defer script running so the chat UI can render planning text.

    Called from handle_tool_start after the EXECUTING state is set.
    50ms = ~3 frames at 60fps — enough for Blender to draw the
    finalized planning bubble before the executor blocks the main thread.
    """
    global _execution_gate_until
    _execution_gate_until = max(_execution_gate_until, time.monotonic() + delay)
    logger.debug(f"Script gate set for {delay:.3f}s")


def _ensure_timer_running() -> None:
    """Ensure the execution timer is running.

    A fresh closure is registered per start (instead of _process_one_request
    itself): bpy timers are keyed by the callback object, so re-registering
    the same function while a previous registration is still completing its
    final ``return None`` can be silently dropped — stranding the queued
    request and never sending its tool response.
    """
    global _timer_active, _timer_fn
    if _shutdown_requested:
        return

    with _timer_lock:
        if _timer_active:
            return

        def _tick():
            return _process_one_request()

        try:
            bpy.app.timers.register(_tick, first_interval=0.01)
            _timer_fn = _tick
            _timer_active = True
            logger.debug("Script execution timer started")
        except Exception as e:
            _timer_active = False
            logger.error(f"Failed to start timer: {e}")


def _stop_timer_if_idle() -> Optional[float]:
    """Atomically stop the timer when the queue is empty.

    The emptiness check and the flag clear must happen under _timer_lock so
    a producer enqueueing at the same instant either sees the flag already
    cleared (and re-arms the timer) or is seen by this check.

    Returns:
        None to stop the timer, or the next interval if work arrived.
    """
    global _timer_active
    with _timer_lock:
        if _pending():
            return TIMER_INTERVAL
        _timer_active = False
        return None


def _request_session_id(req) -> str:
    """The chat session a queued script belongs to: the agent context's chat
    session, else the routing key; a worker lane maps to its parent session
    (``mixar_workspace_main_session`` on the lane scene). Main thread only."""
    sid = str((req.agent_ctx or {}).get("chat_session_id") or req.session_id or "")
    if sid.startswith("agentlane:"):
        for scene in bpy.data.scenes:
            if getattr(scene, "mixie_session_id", "") == sid:
                parent = scene.get("mixar_workspace_main_session", "") if hasattr(scene, "get") else ""
                return str(parent or sid)
    return sid


def _reject_stale_session(req: ExecutionRequest) -> None:
    """Drop a script queued for a session that is no longer active."""
    logger.warning(
        "Dropping stale script %s (id: %s) — no active agent session",
        req.tool_name, req.request_id,
    )
    _send_error_response(req.request_id, "Agent session not active")
    # The dropped script may have been the backend's remove_scene cleanup
    # for an agentlane:* workspace — sweep leaked lane scenes ourselves.
    try:
        from .lane_scene_sweep import schedule_lane_scene_sweep
        schedule_lane_scene_sweep(parent_session_id=_request_session_id(req))
    except Exception:
        logger.debug("lane scene sweep scheduling skipped", exc_info=True)


def _note_output_landed() -> None:
    # Rejection-window tracking only — no event is emitted here (the backend
    # covers agent tool telemetry server-side).
    from mixar.modules.common.analytics import rejection_events
    rejection_events.note_output_landed("agent", None)


def _process_one_request() -> Optional[float]:
    """
    Timer callback - execute ONE queued script per tick.

    This runs on Blender's main thread. Executes one script per call
    to avoid blocking the UI, then re-schedules if more scripts pending.

    Returns:
        Interval for next call if more requests, None to stop timer
    """
    global _last_lane
    if not _pending():
        stop = _stop_timer_if_idle()
        if stop is None:
            return None  # No more requests, stop timer

    # Drain pending SSE events so planning text is finalized before
    # script execution blocks the main thread.
    from .queue_processor import drain_pending_events
    drain_pending_events()

    # Timestamp gate: wait for Blender to draw the finalized planning
    # bubble. Set by handle_tool_start -> gate_execution(50ms).
    if time.monotonic() < _execution_gate_until:
        return TIMER_INTERVAL

    req, status, lane = _take_next()
    if status == pump.EMPTY:
        return _stop_timer_if_idle()
    if status == pump.HOLDING:
        # Every tab with work is waiting on a texture prefetch. Keep holding
        # — this tick cost one flag check, so the UI stays fully responsive
        # — and check again shortly. FIFO within each tab is preserved.
        return TIMER_INTERVAL
    if lane != _last_lane:
        if _last_lane:
            from mixar.modules.common.scenes_log import slog
            slog("queue.switch", None, session_id=lane, previous=_last_lane[:8],
                 tool=req.tool_name)
        _last_lane = lane
    if status in (pump.PREFETCH_FAILED, pump.PREFETCH_EXPIRED):
        refusal = pump.prefetch_refusal(req, status)
        logger.warning("Refusing %s (id: %s): %s", req.tool_name, req.request_id, refusal["error"])
        _send_error_response(req.request_id, refusal["error"], refusal.get("error_type", ""))
        return _stop_timer_if_idle()

    # Safety net: reject scripts that were queued just before load_pre
    # flushed the queue (narrow race window).
    from .session import get_session_manager
    if not get_session_manager().has_active_session(_request_session_id(req)):
        _reject_stale_session(req)
        return _stop_timer_if_idle()

    logger.info(f"Executing {req.tool_name} (id: {req.request_id})")
    # Visible to the WebSocket thread's blender.liveness probe while this
    # tick's bpy work holds the main thread (busy != frozen).
    _set_inflight(req.tool_name, req.request_id, req.session_id)

    target_scene, did_switch, route_error = route_request(
        req.session_id, req.tool_name, req.request_id
    )
    if route_error is not None:
        _clear_inflight()
        _send_error_response(req.request_id, route_error)
        # Stop via the shared, lock-guarded helper. Assigning `_timer_active`
        # directly here binds a function-local (this function never declares
        # `global _timer_active`), leaving the module flag stuck True while
        # Blender unregisters the timer — so it is never re-armed and every
        # subsequent agent script silently stalls for the rest of the session.
        return _stop_timer_if_idle()

    # Record a RUNNING step row on the active agent bubble (steps block UI).
    from .steps_recorder import record_step_start, record_step_end
    chat_scene = target_scene if target_scene else getattr(bpy.context, "scene", None)
    if chat_scene:
        record_step_start(chat_scene, req.request_id, req.tool_name, req.script,
                          call_id=str((req.agent_ctx or {}).get("call_id") or ""))

    executor = get_executor()
    # Skip if previous script is still executing (should not normally happen
    # since the timer runs one-at-a-time, but guards against edge cases)
    if executor._execution_lock.locked():
        logger.warning(
            "Previous script still executing, skipping request (id: %s)", req.request_id
        )
        result_dict = {"success": False, "error": "Previous script still executing"}
    else:
        result_dict = pump.execute_request(req, executor, on_success=_note_output_landed)
        logger.debug(f"Script execution completed: success={result_dict.get('success')}")

    archive_history(req.tool_name, req.script, result_dict, target_scene, req.request_id)
    restore_after(did_switch)

    # Complete the step row with status / touched objects / output.
    if chat_scene:
        record_step_end(chat_scene, req.request_id, result_dict, req.session_id)

    # Main-thread work for this script is done — the liveness probe reports
    # idle from here on.
    _clear_inflight()

    # Send response directly via WebSocket client (thread-safe). This avoids
    # cross-thread queue polling which caused segfaults. A preview render
    # script asks to be held open instead: the reply goes out from the
    # deferral's timer when the native job ends, and this queue keeps draining.
    from .preview_deferral import defer_response, deferred_preview_key
    deferred_key = deferred_preview_key(result_dict)
    if deferred_key is None or not defer_response(req, deferred_key):
        from .jsonrpc_client import get_jsonrpc_client
        pump.respond(get_jsonrpc_client(), req, result_dict)

    # Continue timer if more requests pending. The same tab back-to-back
    # keeps the 500 ms breather (safe for edit mode operations); another
    # tab's script gets the next tick — round-robin serves it first.
    if _pending():
        return TIMER_INTERVAL if _other_lane_pending(lane) else 0.50

    return _stop_timer_if_idle()  # Stop timer when queue empty


def run_on_main_thread(fn: Callable[[], None]) -> None:
    """Schedule a callable to run once on Blender's main thread.

    Thread-safe: can be called from any thread (including the SSE handler).
    bpy.app.timers.register is one of the few Blender APIs safe to invoke
    from a background thread — the callback fires on the main thread.

    Args:
        fn: Zero-argument callable to execute on the main thread.
    """
    if _shutdown_requested:
        logger.debug("Dropping main-thread callback during shutdown")
        return

    def _wrapper():
        try:
            fn()
        except Exception as e:
            logger.warning(f"run_on_main_thread: callback raised: {e}")
        return None  # Return None to prevent rescheduling
    try:
        bpy.app.timers.register(_wrapper, first_interval=0.0)
    except Exception as e:
        logger.warning(f"run_on_main_thread: failed to register timer: {e}")


def resume() -> None:
    """Re-arm the executor after a ``cleanup(shutdown=True)``.

    ``cleanup(shutdown=True)`` runs when the agent connection is torn down
    via bootstrap unregister (Blender exit, but also "Reload Scripts").
    Module state survives the subsequent re-register, so without clearing
    the flag every later script request is silently dropped — no tool
    response is ever sent and the backend times out on EVERY command until
    Blender is fully restarted. ConnectionManager.connect() calls this so a
    new connection always starts with a live executor.
    """
    global _shutdown_requested
    _shutdown_requested = False


def flush_session(session_id: str) -> int:
    """Drop the queued scripts of ONE chat session (New Chat / Abort on that
    tab); every other tab's scripts stay queued. Main thread only. Returns
    the number dropped, each answered with an error so the backend never
    waits on it."""
    global _queued
    dropped = []

    def _mine(req) -> bool:
        return _lane_key(req) == session_id or _request_session_id(req) == session_id

    with _lanes_lock:
        for key, lane in list(_lanes.items()):
            kept = []
            while True:
                try:
                    req = lane.queue.get_nowait()
                except queue.Empty:
                    break
                (dropped if _mine(req) else kept).append(req)
            for req in kept:
                lane.queue.put(req)
            if lane.held is not None and _mine(lane.held):
                dropped.append(lane.held)
                lane.held = None
            if not lane.pending():
                _lanes.pop(key, None)
        _queued -= len(dropped)
    for req in dropped:
        try:
            _send_error_response(req.request_id, "Agent session not active")
        except Exception:  # noqa: BLE001
            pass
    if dropped:
        logger.info("Flushed %d queued script(s) of session %s", len(dropped), session_id[:8])
    return len(dropped)


def cleanup(shutdown: bool = False, session_id: Optional[str] = None) -> None:
    """
    Clean up executor state.

    Call on addon unregister or disconnect to clean up pending requests.
    With ``session_id``: only that session's queued scripts are dropped and
    the executor keeps running for the other tabs.
    """
    global _timer_active, _timer_fn, _execution_gate_until, _shutdown_requested, _queued, _last_lane

    if session_id:
        flush_session(session_id)
        return

    if shutdown:
        _shutdown_requested = True

    with _timer_lock:
        timer_fn = _timer_fn
        _timer_fn = None
        _timer_active = False

    try:
        if timer_fn is not None and bpy.app.timers.is_registered(timer_fn):
            bpy.app.timers.unregister(timer_fn)
    except Exception:
        pass

    _execution_gate_until = 0.0
    # A held-open preview tool call belongs to the flushed session/connection.
    try:
        from .preview_deferral import fail_pending
        fail_pending("executor_reset")
    except Exception:
        logger.debug("preview deferral flush skipped", exc_info=True)

    # Clear every tab's lane, prefetch-held requests included.
    with _lanes_lock:
        _lanes.clear()
        _queued = 0
        _last_lane = ""

    logger.debug("Main thread executor cleaned up")
