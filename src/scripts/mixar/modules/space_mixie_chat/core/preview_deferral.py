# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hold a ``render_viewport(quality="final")`` tool call open until its native
render finishes.

The sandbox script starts the preview (``preview_render.start``) and returns
``{"__deferred_preview__": key}`` as its ``__RESULT__``. Instead of replying,
the executor parks the ORIGINAL request here and a ``bpy.app.timers`` poller
asks ``preview_render.poll`` every 0.25 s; the first terminal state is sent
back on the original request id as an ordinary (flattened) script result. The
main thread is free the whole time — other queued scripts keep executing — and
the WebSocket thread's ``blender.liveness`` probe reports the pending preview
so the backend sees "busy, not frozen". At most ONE deferral exists, because
at most one preview job runs.
"""

import json
import threading
import time
from typing import Optional

import bpy
from bpy.app.handlers import persistent

from mixar.config.logging_config import get_logger
from mixar.modules.common.agent_execution import pump

from . import preview_render
from ..constants import PREVIEW_DEFERRED_MAX_S

logger = get_logger(__name__)

DEFERRED_KEY = "__deferred_preview__"
RESULT_PREFIX = "__RESULT__"
POLL_INTERVAL_S = 0.25

# Read from the WebSocket thread (liveness), written on the main thread.
_lock = threading.Lock()
_pending: Optional[dict] = None   # {"req", "key", "started", "timer"}


def _printed_result(output: str) -> dict:
    """The dict a script printed as ``__RESULT__<json>`` (the backend's own
    convention, parsed from stdout by its tool decorator), else {}."""
    for line in (output or "").splitlines():
        if line.startswith(RESULT_PREFIX):
            try:
                parsed = json.loads(line[len(RESULT_PREFIX):])
            except ValueError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
    return {}


def deferred_preview_key(result: dict) -> Optional[str]:
    """The job key when a script result asks to be held open, else None.

    Both result shapes count: a ``__RESULT__`` variable (flattened into the
    result by ``ExecutionResult.to_dict``) and a printed ``__RESULT__`` line.
    """
    if not isinstance(result, dict) or not result.get("success"):
        return None
    key = result.get(DEFERRED_KEY)
    if key is None:
        key = _printed_result(result.get("output", "")).get(DEFERRED_KEY)
    return key if isinstance(key, str) and key else None


def _respond(req, result: dict) -> None:
    from .jsonrpc_client import get_jsonrpc_client
    pump.respond(get_jsonrpc_client(), req, result)


def _take() -> Optional[dict]:
    global _pending
    with _lock:
        pending, _pending = _pending, None
    return pending


def _tick() -> Optional[float]:
    with _lock:
        pending = _pending
    if pending is None:
        return None
    key = pending["key"]
    value = preview_render.poll(key)
    elapsed = time.monotonic() - pending["started"]
    if value.get("status") == "running":
        if elapsed < PREVIEW_DEFERRED_MAX_S:
            return POLL_INTERVAL_S
        # Leave the job to finish on its own (its settings restore then).
        result = dict(value, success=False, error="preview_timeout")
    else:
        result = dict(value, success=True)
    if _take() is not pending:
        return None  # already failed/superseded by another path
    logger.info("%s %s: %s after %.1fs", pending["req"].tool_name, key,
                result.get("status"), elapsed)
    _respond(pending["req"], result)
    _record_late_capture(pending["req"], result)
    return None


def _record_late_capture(req, result: dict) -> None:
    """The finished final render becomes a capture tile under its step row
    (steps_recorder) — the row itself closed when the request was parked."""
    if not result.get("success"):
        return
    try:
        scene = getattr(bpy.context, "scene", None)
        if scene is None:
            return
        from .steps_recorder import record_step_captures
        record_step_captures(scene, req.request_id, result, req.session_id)
    except Exception:
        logger.debug("late capture tile skipped", exc_info=True)


def defer_response(req, key: str) -> bool:
    """Park ``req`` until preview ``key`` reaches a terminal state.

    Returns True when the caller must NOT respond itself. A second deferral
    supersedes the first (the backend retried the tool and abandoned the old
    request id).
    """
    global _pending
    previous = _take()
    if previous is not None:
        _respond(previous["req"], {"success": False, "error": "preview_superseded",
                                   "job_id": previous["key"]})
    entry = {"req": req, "key": key, "started": time.monotonic(), "timer": _tick}
    with _lock:
        _pending = entry
    _install_load_pre()
    try:
        # One poller only: a superseding deferral must not double-register it.
        if bpy.app.timers.is_registered(_tick):
            bpy.app.timers.unregister(_tick)
        bpy.app.timers.register(_tick, first_interval=POLL_INTERVAL_S)
    except Exception:
        logger.exception("%s %s: poller registration failed", req.tool_name, key)
        if _take() is entry:
            _respond(req, {"success": False, "error": "async_render_unavailable", "job_id": key})
        return True
    return True


def fail_pending(error: str) -> bool:
    """Reply to a pending deferral with a fixed error code. True if one existed."""
    pending = _take()
    if pending is None:
        return False
    try:
        if bpy.app.timers.is_registered(_tick):
            bpy.app.timers.unregister(_tick)
    except Exception:
        pass
    _respond(pending["req"], {"success": False, "error": error, "job_id": pending["key"]})
    return True


def get_pending_inflight() -> Optional[dict]:
    """Liveness view of the held tool call (thread-safe, no bpy)."""
    with _lock:
        pending = _pending
    if pending is None:
        return None
    req = pending["req"]
    return {"tool_name": req.tool_name, "request_id": req.request_id,
            "session_id": req.session_id, "job_id": pending["key"],
            "elapsed_s": round(time.monotonic() - pending["started"], 1)}


@persistent
def _on_load_pre(_unused=None, _extra=None):
    # The scene the render targets is about to be replaced.
    fail_pending("scene_unavailable")


def _install_load_pre() -> None:
    handlers = bpy.app.handlers.load_pre
    if _on_load_pre not in handlers:
        handlers.append(_on_load_pre)
