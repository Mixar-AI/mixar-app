# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Async script execution queue for main thread execution.

The WebSocket thread queues ExecutionRequests (never executes scripts); a
main-thread timer executes ONE script per tick; long scripts must bound their
own work because synchronous bpy still blocks the UI. The
response goes straight to the WebSocket client's outbound queue
(``client.queue_response``) — cross-thread queue polling segfaulted
Blender's embedded Python.

Per-tab lanes (one FIFO per chat session, round-robin, prefetch holds) live
in ``script_lanes``. The take/execute/respond sequence lives in
``mixar.modules.common.agent_execution.pump`` and is shared with the headless
worker pump (``headless/headless_main.py``); scene routing and history live in
``main_thread_routing``.
"""

from collections.abc import Callable
from mixar.config.logging_config import get_logger
import threading
import time
from typing import Optional

import bpy

from mixar.modules.common.agent_execution import pump
from mixar.modules.common.agent_execution.diagnostics import record_phase
from mixar.modules.common.agent_execution.request import ExecutionEnvelope, ExecutionRequest

from .executor import get_executor
from .main_thread_routing import archive_history, restore_after, route_request
from . import script_lanes as lanes
from .script_prefetch import maybe_start_prefetch
from ..constants import TIMER_INTERVAL

logger = get_logger(__name__)

# Provenance-id resolution moved to the shared pump; kept importable here for
# existing callers/tests.
_resolve_agent_context_ids = pump.resolve_agent_context_ids

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

# A render on Blender's job thread REFUSES scripts at once (render_gate); it
# never holds this queue. The 3.4.2 hold stalled every turn for the whole
# render — do not bring a hold back (docs/render-job-contract.md).

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


def _send_error_response(request_id: str, error: str, error_type: str = "", req=None) -> None:
    """Reply to a script request with a failure result (mirrors the stale-session
    path). No-op for notifications or when no client is connected."""
    from .jsonrpc_client import get_jsonrpc_client
    result = {"success": False, "error": error}
    if error_type:
        result["error_type"] = error_type
    pump.respond(get_jsonrpc_client(), req or ExecutionRequest(request_id, ""), result)


def queue_script_request(
    script: str,
    request_id: str,
    tool_name: str = "unknown",
    session_id: str = "",
    agent_ctx: Optional[dict] = None,
    envelope: Optional[dict] = None,
) -> None:
    """Receive on the socket thread; execute on main with the same RPC id.

    agent_ctx carries chat/turn provenance; the optional v3 envelope is
    parsed and carried through, not admitted here.
    """
    global _execution_gate_until
    if _shutdown_requested:
        # Warning, not debug: if this fires outside real shutdown the backend
        # will time out waiting for the never-sent response.
        logger.warning(
            "Dropping script request during shutdown (%s, id: %s)",
            tool_name, request_id,
        )
        _send_error_response(request_id, "Executor is shutting down", "executor_shutdown")
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
        envelope=ExecutionEnvelope.parse(envelope),
    )
    record_phase(req, "received")
    try:
        req.prefetch = maybe_start_prefetch(script, tool_name)
    except Exception:
        logger.exception("Asset prefetch setup failed (id: %s)", request_id)
        _send_error_response(request_id, "Asset prefetch setup failed; nothing was executed",
                             "prefetch_failed", req)
        return
    if not lanes.enqueue(req):
        logger.warning(f"Request queue full, dropping {tool_name} (id: {request_id})")
        _send_error_response(request_id, "Script queue is full; nothing was executed", "queue_full", req)
        record_phase(req, "queue_rejected")
        return
    record_phase(req, "queued")
    _ensure_timer_running()


def has_pending_requests() -> bool:
    """Check if there are pending script requests (queued or held, any tab)."""
    return lanes.pending()


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
            try:
                return _process_one_request()
            except Exception:
                # Blender unregisters a timer whose callback raises. Keep the
                # flag and callback alive together so later requests can run.
                logger.exception("Executor timer tick failed")
                return _stop_timer_if_idle()

        try:
            bpy.app.timers.register(_tick, first_interval=0.01)
            _timer_fn = _tick
            _timer_active = True
            logger.debug("Script execution timer started")
        except Exception as e:
            _timer_active = False
            logger.error(f"Failed to start timer: {e}")
            for req in lanes.drain(lambda _req: True):
                _send_error_response(req.request_id, "Executor timer unavailable; nothing was executed",
                                     "executor_unavailable", req)


def _stop_timer_if_idle() -> Optional[float]:
    """Stop atomically when idle; a concurrent producer must see the cleared
    flag and re-arm, or this check must see its work. Return the next interval
    while pending, otherwise None."""
    global _timer_active
    with _timer_lock:
        if lanes.pending():
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
    _send_error_response(req.request_id, "Agent session not active", req=req)
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
    """Run one queued script on main; yield to the UI between requests."""
    if not lanes.pending():
        stop = _stop_timer_if_idle()
        if stop is None:
            return None  # No more requests, stop timer

    # Drain pending SSE events so planning text is finalized before
    # script execution blocks the main thread.
    from .queue_processor import drain_pending_events
    try:
        drain_pending_events()
    except Exception:
        logger.exception("Agent event drain failed; continuing the script queue")

    # Timestamp gate: wait for Blender to draw the finalized planning
    # bubble. Set by handle_tool_start -> gate_execution(50ms).
    if time.monotonic() < _execution_gate_until:
        return TIMER_INTERVAL

    req, status, lane = lanes.take_next()
    if status == pump.EMPTY:
        return _stop_timer_if_idle()
    if status == pump.HOLDING:
        # Every tab with work is waiting on a texture prefetch. Keep holding
        # — this tick cost one flag check, so the UI stays fully responsive
        # — and check again shortly. FIFO within each tab is preserved.
        return TIMER_INTERVAL
    try:
        return _execute_dequeued_request(req, status, lane)
    except Exception:
        logger.exception("Failed to dispatch request %s", req.request_id)
        if req.response_deferred or req.response_attempted:
            return _stop_timer_if_idle()
        from .jsonrpc_client import get_jsonrpc_client
        pump.respond(get_jsonrpc_client(), req, {"success": False,
                     "error": "Executor dispatch failed; inspect state before retrying",
                     "error_type": "executor_dispatch_failed", "effects_uncertain": True})
        return _stop_timer_if_idle()


def _execute_dequeued_request(req, status, lane) -> Optional[float]:
    """Dispatch a taken request; execution failures never strand the next one."""
    previous = lanes.switch_to(lane)
    if previous is not None:
        from mixar.modules.common.scenes_log import slog
        slog("queue.switch", None, session_id=lane, previous=previous[:8],
             tool=req.tool_name)
    if status in (pump.PREFETCH_FAILED, pump.PREFETCH_EXPIRED):
        refusal = pump.prefetch_refusal(req, status)
        logger.warning("Refusing %s (id: %s): %s", req.tool_name, req.request_id, refusal["error"])
        _send_error_response(req.request_id, refusal["error"], refusal.get("error_type", ""), req)
        return _stop_timer_if_idle()

    from mixar.modules.mcp_bridge.core.lease import authorize_script
    refusal = authorize_script(req.session_id, req.agent_ctx)
    if refusal is not None:
        _send_error_response(req.request_id, refusal["error"], refusal["error_type"])
        return _stop_timer_if_idle()

    # Safety net: reject scripts that were queued just before load_pre
    # flushed the queue (narrow race window).
    from .session import get_session_manager
    if not get_session_manager().has_active_session(_request_session_id(req)):
        _reject_stale_session(req)
        return _stop_timer_if_idle()

    from .render_gate import refuse_during_render
    if refuse_during_render(req):
        return _stop_timer_if_idle()

    logger.info(f"Executing {req.tool_name} (id: {req.request_id})")
    # Visible to the WebSocket thread's blender.liveness probe while this
    # tick's bpy work holds the main thread (busy != frozen).
    _set_inflight(req.tool_name, req.request_id, req.session_id)

    target_scene = chat_scene = None
    did_switch = execution_started = False
    result_dict = None
    try:
        from .steps_recorder import record_step_start, record_step_end
        target_scene, did_switch, route_error = route_request(
            req.session_id, req.tool_name, req.request_id
        )
        if route_error is not None:
            result_dict = {"success": False, "error": route_error, "error_type": "route_failed"}
        else:
            chat_scene = target_scene if target_scene else getattr(bpy.context, "scene", None)
            if chat_scene:
                record_step_start(chat_scene, req.request_id, req.tool_name, req.script,
                                  call_id=str((req.agent_ctx or {}).get("call_id") or ""))
            executor = get_executor()
            if executor._execution_lock.locked():
                result_dict = {"success": False, "error": "Previous script still executing"}
            else:
                execution_started = True
                result_dict = pump.execute_request(req, executor, on_success=_note_output_landed)
    except Exception:
        logger.exception("Executor request failed (id: %s)", req.request_id)
        result_dict = {"success": False, "error": "Executor request failed",
                       "error_type": "executor_failed", "effects_uncertain": execution_started}
    finally:
        try:
            restore_after(did_switch)
        except Exception:
            logger.exception("Executor scene restore failed (id: %s)", req.request_id)
        _clear_inflight()

    # Send response directly via WebSocket client (thread-safe). This avoids
    # cross-thread queue polling which caused segfaults. A preview render
    # script asks to be held open instead: the reply goes out from the
    # deferral's timer when the native job ends, and this queue keeps draining.
    from .preview_deferral import defer_response, deferred_preview_key
    deferred_key = deferred_preview_key(result_dict)
    if deferred_key is None or not defer_response(req, deferred_key, scene=chat_scene,
                                                  initial_result=result_dict):
        try:
            archive_history(req.tool_name, req.script, result_dict, chat_scene, req.request_id)
            if chat_scene:
                record_step_end(chat_scene, req.request_id, result_dict, req.session_id)
        except Exception:
            logger.exception("Executor history failed (id: %s)", req.request_id)
        from .jsonrpc_client import get_jsonrpc_client
        pump.respond(get_jsonrpc_client(), req, result_dict)

    # Continue timer if more requests pending. The same tab back-to-back
    # keeps the 500 ms breather (safe for edit mode operations); another
    # tab's script gets the next tick — round-robin serves it first.
    if lanes.pending():
        return TIMER_INTERVAL if lanes.other_pending(lane) else 0.50

    return _stop_timer_if_idle()  # Stop timer when queue empty


def run_on_main_thread(fn: Callable[[], None]) -> bool:
    """Schedule once on main; return False on shutdown or registration failure."""
    if _shutdown_requested:
        logger.debug("Dropping main-thread callback during shutdown")
        return False

    def _wrapper():
        try:
            fn()
        except Exception as e:
            logger.warning(f"run_on_main_thread: callback raised: {e}")
        return None  # Return None to prevent rescheduling
    try:
        bpy.app.timers.register(_wrapper, first_interval=0.0)
        return True
    except Exception as e:
        logger.warning(f"run_on_main_thread: failed to register timer: {e}")
        return False


def resume() -> None:
    """Re-arm after unregister/reload; module state survives re-registration."""
    global _shutdown_requested
    _shutdown_requested = False


def flush_session(session_id: str) -> int:
    """Drop the queued scripts of ONE chat session (New Chat / Abort on that
    tab); every other tab's scripts stay queued. Main thread only. Returns
    the number dropped, each answered with an error so the backend never
    waits on it."""

    def _mine(req) -> bool:
        return lanes.lane_key(req) == session_id or _request_session_id(req) == session_id

    dropped = lanes.drain(_mine)
    from .preview_deferral import fail_pending
    fail_pending("executor_reset", session_id=session_id)
    for req in dropped:
        try:
            _send_error_response(req.request_id, "Agent session not active", req=req)
        except Exception:  # noqa: BLE001
            pass
    if dropped:
        logger.info("Flushed %d queued script(s) of session %s", len(dropped), session_id[:8])
    return len(dropped)


def cleanup(shutdown: bool = False, session_id: Optional[str] = None) -> None:
    """Fail pending requests on reset, or flush only the named session.

    An empty id owns no work. Only None resets all tabs. Shutdown must not
    inspect scene RNA: Blender may already have freed its data.
    """
    global _timer_active, _timer_fn, _execution_gate_until, _shutdown_requested

    if session_id is not None:
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
        fail_pending("executor_reset", update_scene=not shutdown)
    except Exception:
        logger.debug("preview deferral flush skipped", exc_info=True)

    # Fail every queued request; clearing silently leaves the backend waiting
    # for its full timeout even though nothing is executing anymore.
    for req in lanes.drain(lambda _req: True):
        _send_error_response(req.request_id, "Executor reset; nothing was executed", "executor_reset", req)
    lanes.clear()

    logger.debug("Main thread executor cleaned up")
