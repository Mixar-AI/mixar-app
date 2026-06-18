# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Async script execution queue for main thread execution.

Architecture:
- Request queue: (request_id, script) from WebSocket thread
- Timer polls request queue, executes ONE script per tick
- Responses pushed directly to WebSocket client's outbound queue (thread-safe)

This approach is non-blocking and prevents UI freezes by:
1. WebSocket thread queues requests (never executes scripts)
2. Timer on main thread polls and executes ONE script per tick
3. Responses are sent directly via client.queue_response() to avoid
   cross-thread queue polling (which caused segfaults in Blender's embedded Python)
"""

from collections.abc import Callable
from mixar.config.logging_config import get_logger
import queue
import time
from typing import Optional

import bpy

from .executor import get_executor
from ..constants import SessionState, TIMER_INTERVAL

logger = get_logger(__name__)

# Request queue: (request_id, script, tool_name, session_id) from WebSocket thread
_request_queue: queue.Queue = queue.Queue(maxsize=1000)

# Timer state
_timer_active = False
_shutdown_requested = False

# Execution gate: defer script running so the chat UI can render planning text
_execution_gate_until: float = 0.0


def queue_script_request(script: str, request_id: str, tool_name: str = "unknown", session_id: str = "") -> None:
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
    """
    global _execution_gate_until
    if _shutdown_requested:
        logger.debug("Dropping script request during shutdown")
        return

    # Gate: give SSE events (planning text) time to arrive before execution
    _execution_gate_until = max(_execution_gate_until, time.monotonic() + 0.05)
    logger.debug(f"Queuing script request (id: {request_id}), initial gate set")
    try:
        _request_queue.put_nowait((request_id, script, tool_name, session_id))
    except queue.Full:
        logger.warning(f"Request queue full, dropping {tool_name} (id: {request_id})")
        return
    _ensure_timer_running()


def has_pending_requests() -> bool:
    """Check if there are pending script requests."""
    return not _request_queue.empty()


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
    """Ensure the execution timer is running."""
    global _timer_active
    if _shutdown_requested:
        return

    if not _timer_active:
        try:
            if not bpy.app.timers.is_registered(_process_one_request):
                bpy.app.timers.register(_process_one_request, first_interval=0.01)
                _timer_active = True
                logger.debug("Script execution timer started")
        except Exception as e:
            logger.error(f"Failed to start timer: {e}")


def _process_one_request() -> Optional[float]:
    """
    Timer callback - execute ONE queued script per tick.

    This runs on Blender's main thread. Executes one script per call
    to avoid blocking the UI, then re-schedules if more scripts pending.

    Returns:
        Interval for next call (0.20s) if more requests, None to stop timer
    """
    global _timer_active

    if _request_queue.empty():
        _timer_active = False
        return None  # No more requests, stop timer

    # Drain pending SSE events so planning text is finalized before
    # script execution blocks the main thread.
    from .queue_processor import drain_pending_events
    drain_pending_events()

    # Timestamp gate: wait for Blender to draw the finalized planning
    # bubble. Set by handle_tool_start -> gate_execution(50ms).
    if time.monotonic() < _execution_gate_until:
        return TIMER_INTERVAL

    try:
        request_id, script, tool_name, session_id = _request_queue.get_nowait()
    except queue.Empty:
        _timer_active = False
        return None

    # Safety net: reject scripts that were queued just before load_pre
    # flushed the queue (narrow race window). If the session is no longer
    # active, drop the script and send an error response.
    from .session import get_session_manager
    session = get_session_manager()
    if not session.has_active_session():
        logger.warning(
            "Dropping stale script %s (id: %s) — no active agent session",
            tool_name, request_id,
        )
        from .jsonrpc_client import get_jsonrpc_client
        client = get_jsonrpc_client()
        if client and client.is_connected and request_id != "notification":
            client.queue_response(request_id, {"success": False, "error": "Agent session not active"})
        if not _request_queue.empty():
            return TIMER_INTERVAL
        _timer_active = False
        return None

    logger.info(f"Executing {tool_name} (id: {request_id})")

    # --- Scene context routing ---
    # Find the target scene by session_id and switch context so the
    # script executes against the correct scene's objects.
    # The switch + execute + restore all happen within this single timer
    # tick — Blender does not redraw, so the user sees no visual change.
    original_scene = None
    target_scene = None
    if session_id:
        for s in bpy.data.scenes:
            if getattr(s, 'mixie_session_id', '') == session_id:
                target_scene = s
                break

    if target_scene and bpy.context.window and bpy.context.window.scene != target_scene:
        original_scene = bpy.context.window.scene
        bpy.context.window.scene = target_scene
        logger.debug(f"Switched to scene '{target_scene.name}' for script execution")

    executor = get_executor()

    # Skip if previous script is still executing (should not normally happen
    # since the timer runs one-at-a-time, but guards against edge cases)
    if executor._execution_lock.locked():
        logger.warning(
            "Previous script still executing, skipping request (id: %s)", request_id
        )
        result_dict = {"success": False, "error": "Previous script still executing"}
    else:
        try:
            result = executor.execute(script)
            result_dict = result.to_dict()
            logger.debug(f"Script execution completed: success={result.success}")
        except Exception as e:
            logger.error(f"Script execution failed: {e}")
            result_dict = {"success": False, "error": str(e)}

    # --- Operation history: archive every agent script/tool execution ---
    try:
        from mixar.modules.operation_history.core import store as _op_store
        from mixar.modules.operation_history.core.record import build_agent_record
        _hist_scene = target_scene if target_scene is not None else (
            bpy.context.window.scene if bpy.context.window else None)
        _hist_sid = getattr(_hist_scene, "mixie_session_id", "") if _hist_scene else ""
        _wm = getattr(bpy.context, "window_manager", None)
        _iid = getattr(_wm, "mixie_instance_id", "") if _wm else ""
        _op_store.append_operation(
            build_agent_record(tool_name=tool_name, result_dict=result_dict,
                               session_id=_hist_sid, instance_id=_iid, request_id=request_id),
            script_text=script,
        )
    except Exception as _op_exc:  # never break execution/response on history failure
        logger.debug("operation_history: failed to record agent op: %s", _op_exc)

    # Restore original scene after execution
    if original_scene is not None and bpy.context.window:
        try:
            bpy.context.window.scene = original_scene
        except Exception:
            pass  # Scene may have been deleted by the script

    # Send response directly via WebSocket client (thread-safe)
    # This avoids cross-thread queue polling which caused segfaults
    from .jsonrpc_client import get_jsonrpc_client
    client = get_jsonrpc_client()
    if client and client.is_connected:
        client.queue_response(request_id, result_dict)
    else:
        logger.warning(f"No active client, dropping response (id: {request_id})")

    # Continue timer if more requests pending
    if not _request_queue.empty():
        return 0.50  # 500ms between executions (safe for edit mode operations)

    _timer_active = False
    return None  # Stop timer when queue empty


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


def cleanup(shutdown: bool = False) -> None:
    """
    Clean up executor state.

    Call on addon unregister or disconnect to clean up pending requests.
    """
    global _timer_active, _execution_gate_until, _shutdown_requested

    if shutdown:
        _shutdown_requested = True

    try:
        if bpy.app.timers.is_registered(_process_one_request):
            bpy.app.timers.unregister(_process_one_request)
    except Exception:
        pass

    _timer_active = False
    _execution_gate_until = 0.0

    # Clear request queue
    while not _request_queue.empty():
        try:
            _request_queue.get_nowait()
        except queue.Empty:
            break

    logger.debug("Main thread executor cleaned up")
