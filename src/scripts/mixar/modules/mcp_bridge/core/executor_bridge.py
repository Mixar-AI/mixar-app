# SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main-thread execution bridge for MCP requests.

Runs scripts through the exact same sandboxed ScriptExecutor the hosted
Mixie agent uses (`space_mixie_chat.core.executor`), but synchronously from
the bridge's HTTP thread: the work is marshalled onto Blender's main thread
via `main_thread_executor.run_on_main_thread` and the HTTP thread blocks on
an event until the result is ready (or the timeout fires).

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
# so a client that retries a non-idempotent script would run it twice. Holding
# this lock across schedule+wait guarantees at most one bridge job is in flight,
# and a request that can't get the lock quickly gets a clear "busy" answer
# instead of silently stacking a duplicate.
_EXEC_LOCK = threading.Lock()
_LOCK_ACQUIRE_TIMEOUT_S = 2.0


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

    Returns `fn()`'s result, or an error envelope on timeout/exception.
    The callable keeps running to completion on the main thread even if the
    waiter times out — Blender scripts cannot be safely interrupted — but the
    late result is discarded.
    """
    from mixar.modules.space_mixie_chat.core import main_thread_executor

    # The `_shutdown_requested` latch is a process-global shared with the WS
    # agent path; it stays set after a "Reload Scripts" / disconnect and is
    # only cleared by ConnectionManager.connect(). The bridge's lifecycle is
    # independent of the hosted agent, so clear it ourselves — otherwise every
    # job is silently dropped and the request hangs until timeout.
    main_thread_executor.resume()

    if not _EXEC_LOCK.acquire(timeout=_LOCK_ACQUIRE_TIMEOUT_S):
        return {
            "success": False,
            "error": "Mixar is busy running another MCP request; retry shortly.",
            "busy": True,
        }

    done = threading.Event()
    holder: dict = {}

    def _job():
        try:
            holder["result"] = fn()
        except Exception as exc:  # surface, never swallow
            logger.error("MCP bridge main-thread job failed: %s", exc, exc_info=True)
            holder["result"] = {"success": False, "error": str(exc)}
        finally:
            done.set()

    try:
        main_thread_executor.run_on_main_thread(_job)

        wait_s = _clamp_timeout(timeout)
        if not done.wait(wait_s):
            logger.warning("MCP bridge: main-thread job timed out after %.1fs", wait_s)
            return {
                "success": False,
                "error": "Timed out after {0:.0f}s waiting for Blender's main thread. "
                "The script may still be running; check the scene before retrying.".format(wait_s),
                "timed_out": True,
            }
        return holder.get("result", {"success": False, "error": "No result produced"})
    finally:
        _EXEC_LOCK.release()


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
