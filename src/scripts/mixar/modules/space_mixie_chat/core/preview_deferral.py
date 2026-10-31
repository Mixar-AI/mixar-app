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
from mixar.modules.common.agent_execution.diagnostics import record_phase

from . import preview_render
from ..constants import PREVIEW_DEFERRED_MAX_S

logger = get_logger(__name__)

DEFERRED_KEY = "__deferred_preview__"
# A job in a background worker process (``common/render_worker``) other than a
# preview: an export package. Any number may be pending, each answered on its
# own request id when ``poll`` reports it terminal.
JOB_KEY = "__deferred_job__"
RESULT_PREFIX = "__RESULT__"
POLL_INTERVAL_S = 0.25

# Read from the WebSocket thread (liveness), written on the main thread.
_lock = threading.Lock()
_pending: Optional[dict] = None   # {"req", "key", "started", "timer"}
_jobs: dict = {}                   # worker-job key -> entry (also "poll", "cancel", "max_s")


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


def _deferred_key(result: dict, marker: str) -> Optional[str]:
    if not isinstance(result, dict) or not result.get("success"):
        return None
    key = result.get(marker)
    if key is None:
        key = _printed_result(result.get("output", "")).get(marker)
    return key if isinstance(key, str) and key else None


def deferred_job_key(result: dict) -> Optional[str]:
    """The worker-job key when a script result asks to be held open
    (``{"__deferred_job__": key}``, e.g. an export package), else None."""
    return _deferred_key(result, JOB_KEY)


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


def _take(expected=None, session_id=None) -> Optional[dict]:
    global _pending
    with _lock:
        if expected is not None and _pending is not expected:
            return None
        if session_id is not None and _pending is not None:
            req = _pending["req"]
            owner = str((req.agent_ctx or {}).get("chat_session_id") or _pending["scene_session"]
                        or req.session_id or "")
            if owner != session_id and req.session_id != session_id:
                return None
        pending, _pending = _pending, None
        if pending is not None:
            pending["req"].response_deferred = False
    return pending


def _tick(expected=None) -> Optional[float]:
    with _lock:
        pending = _pending
    if pending is None or (expected is not None and pending is not expected):
        return None
    key = pending["key"]
    try:
        value = preview_render.poll(key)
    except Exception:
        logger.exception("Preview poll failed for %s", key)
        value = {"job_id": key, "status": "failed", "error": "preview_poll_failed"}
    elapsed = time.monotonic() - pending["started"]
    if value.get("status") == "running":
        if elapsed < PREVIEW_DEFERRED_MAX_S:
            return POLL_INTERVAL_S
        # Leave the job to finish on its own (its settings restore then).
        result = dict(value, success=False, error="preview_timeout")
    else:
        result = dict(value, success=value.get("status") == "done")
        if not result["success"]:
            result.setdefault("error", "preview_" + str(value.get("status") or "unavailable"))
    if _take(pending) is not pending:
        return None  # already failed/superseded by another path
    logger.info("%s %s: %s after %.1fs", pending["req"].tool_name, key,
                result.get("status"), elapsed)
    _complete(pending, result)
    return None


def _origin_scene(pending):
    """Resolve the original scene after tab switches/renames, never the active tab."""
    scene = bpy.data.scenes.get(pending["scene_name"])
    sid = pending["scene_session"]
    if scene is not None and getattr(scene, "mixie_session_id", "") == sid:
        return scene
    if sid:
        matches = [scene for scene in bpy.data.scenes
                   if getattr(scene, "mixie_session_id", "") == sid]
        if len(matches) == 1:
            return matches[0]
    return None


def _complete(pending, result: dict, *, update_scene=True) -> None:
    """Finish the original row and operation exactly once, on every exit path."""
    req = pending["req"]
    merged = dict(pending["initial_result"])
    merged.pop(DEFERRED_KEY, None)
    merged.pop(JOB_KEY, None)
    # A printed deferral marker must not override the actual terminal result
    # when the backend parses stdout's __RESULT__ convention.
    merged.pop("output", None)
    merged.update(result)
    req.timing["render_wait_ms"] = round((time.monotonic() - pending["started"]) * 1000, 1)
    record_phase(req, "render_finished", merged)
    if not update_scene:
        pass  # bpy data can already be freed during app_exit unregister.
    elif threading.current_thread() is threading.main_thread():
        _record_completion(pending, merged)
    else:
        # Disconnect/abort can arrive on the socket thread. Resolve scene RNA
        # only when this runs on main; shutdown deliberately drops UI work.
        from .main_thread_executor import run_on_main_thread
        run_on_main_thread(lambda: _record_completion(pending, merged))
    _respond(req, merged)


def _record_completion(pending, merged):
    req = pending["req"]
    try:
        scene = _origin_scene(pending)
    except Exception:
        scene = None
    if scene is None:
        return
    try:
        from .steps_recorder import record_step_end
        record_step_end(scene, req.request_id, merged, pending["scene_session"])
    except Exception:
        logger.debug("Preview step recording skipped", exc_info=True)
    try:
        from .main_thread_routing import archive_history
        archive_history(req.tool_name, req.script, merged, scene, req.request_id)
    except Exception:
        logger.debug("Preview terminal history recording skipped", exc_info=True)


def defer_response(req, key: str, *, scene=None, initial_result=None) -> bool:
    """Park ``req`` until preview ``key`` reaches a terminal state.

    Returns True when the caller must NOT respond itself. A second deferral
    supersedes the first (the backend retried the tool and abandoned the old
    request id).
    """
    global _pending
    previous = _take()
    if previous is not None:
        _complete(previous, {"success": False, "error": "preview_superseded",
                             "job_id": previous["key"]})
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    entry = {"req": req, "key": key, "started": time.monotonic(),
             "scene_name": str(getattr(scene, "name", "") or ""),
             "scene_session": str(getattr(scene, "mixie_session_id", "") or ""),
             "initial_result": dict(initial_result or {})}
    # A fresh callback prevents a superseded timer's return None from
    # unregistering the replacement deferral during a reconnect/retry.
    entry["timer"] = lambda: _tick(entry)
    with _lock:
        _pending = entry
        req.response_deferred = True
    record_phase(req, "render_wait")
    try:
        _install_load_pre()
        if previous is not None and bpy.app.timers.is_registered(previous["timer"]):
            bpy.app.timers.unregister(previous["timer"])
        bpy.app.timers.register(entry["timer"], first_interval=POLL_INTERVAL_S)
    except Exception:
        logger.exception("%s %s: poller registration failed", req.tool_name, key)
        if _take(entry) is entry:
            _complete(entry, {"success": False, "error": "async_render_unavailable", "job_id": key})
        return True
    return True


def fail_pending(error: str, session_id: str | None = None, *, update_scene=True) -> bool:
    """Reply to a pending deferral with a fixed error code. True if one existed."""
    failed_jobs = _fail_jobs(error, session_id, update_scene=update_scene)
    pending = _take(session_id=session_id)
    if pending is None:
        return failed_jobs
    try:
        if (threading.current_thread() is threading.main_thread()
                and bpy.app.timers.is_registered(pending["timer"])):
            bpy.app.timers.unregister(pending["timer"])
    except Exception:
        pass
    _complete(pending, {"success": False, "error": error, "job_id": pending["key"]},
              update_scene=update_scene)
    return True


def get_pending_inflight() -> Optional[dict]:
    """Liveness view of the held tool call (thread-safe, no bpy)."""
    with _lock:
        pending = _pending or next(iter(_jobs.values()), None)
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


# ---------------------------------------------------------------------------
# Worker jobs (export packages): any number held open at once
# ---------------------------------------------------------------------------

def _owner(entry) -> str:
    req = entry["req"]
    return str((req.agent_ctx or {}).get("chat_session_id") or entry["scene_session"]
               or req.session_id or "")


def _take_job(key, expected=None) -> Optional[dict]:
    with _lock:
        entry = _jobs.get(key)
        if entry is None or (expected is not None and entry is not expected):
            return None
        del _jobs[key]
        entry["req"].response_deferred = False
    return entry


def _tick_job(entry) -> Optional[float]:
    key = entry["key"]
    with _lock:
        if _jobs.get(key) is not entry:
            return None
    try:
        value = entry["poll"](key)
    except Exception:
        logger.exception("Worker job poll failed for %s", key)
        value = {"status": "failed", "result": {"success": False, "error": "worker_poll_failed"}}
    elapsed = time.monotonic() - entry["started"]
    if value.get("status") == "running":
        if elapsed < entry["max_s"]:
            return POLL_INTERVAL_S
        _cancel_job(entry)
        result = {"success": False, "error": "worker_job_timeout", "job_id": key}
    else:
        result = dict(value.get("result") or {"success": False, "error": "worker_job_failed"})
    if _take_job(key, entry) is not entry:
        return None
    logger.info("%s %s: %s after %.1fs", entry["req"].tool_name, key,
                "ok" if result.get("success") else result.get("error"), elapsed)
    _complete(entry, result)
    return None


def _cancel_job(entry) -> None:
    cancel, key = entry.get("cancel"), entry["key"]
    if cancel is None:
        return

    def _run():
        try:
            cancel(key)
        except Exception:
            logger.debug("Worker job cancel failed", exc_info=True)

    if threading.current_thread() is threading.main_thread():
        _run()
    else:  # an abort on the socket thread: the worker pool is main-thread state
        from .main_thread_executor import run_on_main_thread
        run_on_main_thread(_run)


def defer_job(req, key: str, *, poll, cancel=None, max_s: float, scene=None,
              initial_result=None) -> bool:
    """Park ``req`` until worker job ``key`` is terminal. ``poll(key)`` returns
    ``{"status": "running"}`` or ``{"status": "done", "result": <reply dict>}``;
    ``cancel(key)`` stops it when the call is abandoned. Returns True when the
    caller must NOT respond itself. A second deferral of the same key (the
    backend retried the call) supersedes the first."""
    previous = _take_job(key)
    if previous is not None:
        _complete(previous, {"success": False, "error": "job_superseded", "job_id": key})
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    entry = {"req": req, "key": key, "started": time.monotonic(), "poll": poll,
             "cancel": cancel, "max_s": float(max_s),
             "scene_name": str(getattr(scene, "name", "") or ""),
             "scene_session": str(getattr(scene, "mixie_session_id", "") or ""),
             "initial_result": dict(initial_result or {})}
    entry["timer"] = lambda: _tick_job(entry)
    with _lock:
        _jobs[key] = entry
        req.response_deferred = True
    record_phase(req, "worker_wait")
    try:
        _install_load_pre()
        bpy.app.timers.register(entry["timer"], first_interval=POLL_INTERVAL_S)
    except Exception:
        logger.exception("%s %s: poller registration failed", req.tool_name, key)
        if _take_job(key, entry) is entry:
            _cancel_job(entry)
            _complete(entry, {"success": False, "error": "worker_job_unavailable", "job_id": key})
    return True


def _fail_jobs(error: str, session_id: str | None, *, update_scene=True) -> bool:
    with _lock:
        keys = [key for key, entry in _jobs.items()
                if session_id is None or _owner(entry) == session_id
                or entry["req"].session_id == session_id]
    failed = False
    for key in keys:
        entry = _take_job(key)
        if entry is None:
            continue
        failed = True
        try:
            if (threading.current_thread() is threading.main_thread()
                    and bpy.app.timers.is_registered(entry["timer"])):
                bpy.app.timers.unregister(entry["timer"])
        except Exception:
            pass
        _cancel_job(entry)
        _complete(entry, {"success": False, "error": error, "job_id": key},
                  update_scene=update_scene)
    return failed
