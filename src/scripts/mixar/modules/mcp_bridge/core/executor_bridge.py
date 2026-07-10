# SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main-thread execution bridge for MCP requests.

Runs scripts through the exact same sandboxed ScriptExecutor the hosted
Mixie agent uses (`space_mixie_chat.core.executor`), but synchronously from
the bridge's HTTP thread: the work is marshalled onto Blender's main thread
via the bridge's own `_schedule_on_main_thread` (a direct, thread-safe
`bpy.app.timers.register`, independent of the hosted-agent WS scheduler) and
the HTTP thread blocks on an event until the result is ready (or the timeout
fires).

This deliberately bypasses the WebSocket transport, the chat-session gate
and Mixar auth — the trust boundary is the loopback HTTP server. The sandbox
itself (AST validation, restricted builtins, no os/pathlib) still applies to
every script, identical to hosted-agent execution.
"""

import json
import threading
from typing import Any, Optional

from mixar.config.logging_config import get_logger

from ..constants import EXECUTE_TIMEOUT_DEFAULT_S, EXECUTE_TIMEOUT_MAX_S

logger = get_logger(__name__)

# Serialize bridge-driven main-thread jobs. Blender's main thread runs one
# script at a time; without this, a timed-out HTTP request could return
# "failed" while a second request's script is already queued behind the first,
# so a client that retries a non-idempotent script would run it twice. The lock
# is held from acquire until the scheduled job TRULY completes (not merely until
# the caller's wait elapses), so a retry after a client-side timeout gets a
# fail-fast "busy" answer instead of stacking a duplicate main-thread job.
_EXEC_LOCK = threading.Lock()
_LOCK_ACQUIRE_TIMEOUT_S = 2.0

# Set when the bridge is shutting down (Reload Scripts / addon disable / exit).
# A job that will never complete because the app is going away must not hold the
# lock forever — the releaser wakes on this and frees it (logged). A job that is
# merely running long (render/bake) is NOT abandoned: it keeps the lock until it
# truly finishes, so a retry is always answered "busy", never a duplicate run.
_ABANDON = threading.Event()


def signal_shutdown() -> None:
    """Tell in-flight releasers to stop waiting (the bridge is shutting down)."""
    _ABANDON.set()


def clear_shutdown() -> None:
    """Re-arm for a fresh bridge lifecycle (called when the server (re)starts)."""
    _ABANDON.clear()


def _schedule_on_main_thread(fn) -> None:
    """Schedule `fn` to run once on Blender's main thread (bridge-owned).

    Uses ``bpy.app.timers.register`` directly (one of the few thread-safe bpy
    calls) instead of routing through ``space_mixie_chat.main_thread_executor``.
    That deliberately decouples the bridge from that module's process-global
    ``_shutdown_requested`` latch, which belongs to the hosted-agent WS
    lifecycle — the bridge no longer reads or mutates it. Raises if scheduling
    fails so the caller can release the lock and report the error.
    """
    import bpy

    def _wrapper():
        try:
            fn()
        except Exception as exc:  # never let a callback break the timer loop
            logger.error("MCP bridge main-thread callback raised: %s", exc, exc_info=True)
        return None  # one-shot timer

    bpy.app.timers.register(_wrapper, first_interval=0.0)


def build_script(script: str, params: Optional[dict] = None) -> str:
    """Prepend the agent's `__PARAMS__` convention to a script.

    The hosted backend embeds params as a literal assignment at the top of
    every tool script; we reproduce that contract so agent-authored script
    templates work unmodified. The JSON is passed through json.loads from a
    Python string literal so arbitrary content can never break out of the
    assignment expression.
    """
    if params is None:
        return script
    payload = json.dumps(params, ensure_ascii=True)
    return "__PARAMS__ = json.loads({0!r})\n{1}".format(payload, script)


def _clamp_timeout(timeout: Optional[float]) -> float:
    try:
        value = float(timeout) if timeout is not None else EXECUTE_TIMEOUT_DEFAULT_S
    except (TypeError, ValueError):
        value = EXECUTE_TIMEOUT_DEFAULT_S
    return max(1.0, min(value, EXECUTE_TIMEOUT_MAX_S))


def run_on_main_thread_sync(fn, timeout: Optional[float] = None) -> dict:
    """Run `fn` on Blender's main thread and wait for its dict result.

    Returns `fn()`'s result, or an error envelope on timeout/exception. The
    callable keeps running to completion on the main thread even if the caller's
    wait elapses — Blender scripts cannot be safely interrupted — and the
    serialization lock is held until it truly finishes, so a retry after a
    client-side timeout is answered "busy" rather than running a duplicate.
    """
    if not _EXEC_LOCK.acquire(timeout=_LOCK_ACQUIRE_TIMEOUT_S):
        return {
            "success": False,
            "error": "Mixar is busy running another MCP request; retry shortly.",
            "busy": True,
        }

    started = threading.Event()  # set once the job actually begins on the main thread
    done = threading.Event()
    holder: dict = {}

    # Release the lock exactly once, from whichever path first observes the job
    # as finished (or the safety cap). Guarded so the prompt-return path and the
    # background releaser can never double-release.
    release_guard = threading.Lock()
    released = {"done": False}

    def _release_once():
        with release_guard:
            if not released["done"]:
                released["done"] = True
                _EXEC_LOCK.release()

    def _job():
        started.set()
        try:
            holder["result"] = fn()
        except Exception as exc:  # surface, never swallow
            logger.error("MCP bridge main-thread job failed: %s", exc, exc_info=True)
            holder["result"] = {"success": False, "error": str(exc)}
        finally:
            done.set()
            _release_once()  # lock freed only when the job truly completes

    try:
        _schedule_on_main_thread(_job)
    except Exception as exc:
        _release_once()  # scheduling failed; we still own the lock
        logger.error("MCP bridge: failed to schedule main-thread job: %s", exc, exc_info=True)
        return {
            "success": False,
            "error": "Could not schedule work on Blender's main thread: {0}".format(exc),
        }

    # Hold the lock until the job TRULY completes — however long a legitimate
    # render/bake runs — so a retry is always answered "busy", never a duplicate.
    # The only escape is bridge shutdown (_ABANDON): a job that can never finish
    # because the app is going away must not deadlock the lock forever. Both
    # exits are the sole timer-free release paths, and the shutdown exit is
    # logged so an abandoned job is diagnosable (never silent).
    def _releaser():
        while not done.wait(1.0):
            if _ABANDON.is_set():
                logger.error(
                    "MCP bridge: releasing the exec lock during shutdown while a "
                    "main-thread job was in flight (started=%s); its result is discarded.",
                    started.is_set(),
                )
                break
        _release_once()

    threading.Thread(target=_releaser, name="Mixar-MCP-LockReleaser", daemon=True).start()

    wait_s = _clamp_timeout(timeout)
    if done.wait(wait_s):
        _release_once()  # completed within the wait — free the slot promptly
        return holder.get("result", {"success": False, "error": "No result produced"})

    # Timed out. The lock stays held (job still owns it) so a retry gets "busy".
    # Distinguish "still running" from "never started" so the caller knows
    # whether a retry is safe.
    if started.is_set():
        message = (
            "Timed out after {0:.0f}s; the script is still running on Blender's main "
            "thread. Do not blindly retry a non-idempotent operation — inspect the "
            "scene first (the bridge answers 'busy' until it finishes).".format(wait_s)
        )
    else:
        message = (
            "Timed out after {0:.0f}s; the job has not started yet (main thread busy "
            "or the bridge is mid-shutdown). Safe to retry shortly.".format(wait_s)
        )
    logger.warning(
        "MCP bridge: main-thread job timed out after %.1fs (started=%s)", wait_s, started.is_set()
    )
    return {"success": False, "error": message, "timed_out": True, "started": started.is_set()}


def execute_script(
    script: str,
    params: Optional[dict] = None,
    push_undo: bool = True,
    timeout: Optional[float] = None,
) -> dict:
    """Execute a sandboxed bpy script exactly like the hosted agent does.

    Returns the ExecutionResult envelope (`success`, `output`,
    created/modified/deleted objects, flattened `__RESULT__` dict, ...).
    """
    if not isinstance(script, str) or not script.strip():
        return {"success": False, "error": "'script' must be a non-empty string"}
    if params is not None and not isinstance(params, dict):
        return {"success": False, "error": "'params' must be an object/dict when provided"}

    full_script = build_script(script, params)

    def _run() -> dict:
        from mixar.modules.space_mixie_chat.core.executor import get_executor

        result = get_executor().execute(full_script, push_undo=bool(push_undo))
        return result.to_dict()

    return run_on_main_thread_sync(_run, timeout=timeout)


def run_local_tool(
    domain: str,
    name: str,
    params: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> dict:
    """Dispatch a read-only client-side tool (scene graph / operation history).

    Both registries take an explicit scene; the bridge resolves the active
    scene on the main thread, mirroring the agent's non-scene-routing path.
    """
    from ..constants import (
        TOOL_DOMAIN_OPERATION_HISTORY,
        TOOL_DOMAIN_SCENE_GRAPH,
        TOOL_DOMAINS,
    )

    if domain not in TOOL_DOMAINS:
        return {
            "success": False,
            "error": "unknown tool domain '{0}'".format(domain),
            "available_domains": list(TOOL_DOMAINS),
        }

    def _run() -> dict:
        import bpy

        scene = bpy.context.scene
        if domain == TOOL_DOMAIN_SCENE_GRAPH:
            from mixar.modules.scene_graph.core.tools import run_tool
        else:  # TOOL_DOMAIN_OPERATION_HISTORY
            from mixar.modules.operation_history.core.tools import run_tool

        payload: Any = run_tool(scene, name, params or {})
        if isinstance(payload, dict) and "error" in payload:
            return {"success": False, **payload}
        return {"success": True, "result": payload}

    return run_on_main_thread_sync(_run, timeout=timeout)
