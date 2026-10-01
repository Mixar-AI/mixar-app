# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded local request pump. Network threads enqueue; Blender stays main-thread."""

from dataclasses import dataclass, field
from pathlib import Path
import queue
import threading
import time
import uuid

import bpy

from ..constants import ACTION_TIMEOUT, MAX_PENDING, UIError
from . import input as native_input, observe, ownership, schema
from .receipts import Receipts


@dataclass
class Request:
    owner: str
    name: str
    args: dict
    call_id: str
    session: str
    deadline: float
    done: threading.Event = field(default_factory=threading.Event)
    cancelled: threading.Event = field(default_factory=threading.Event)
    result: dict | None = None
    claimed: bool = False


_queue = queue.Queue(MAX_PENDING)
_active = None
_registered = False
_receipts = None
_requests = {}
_request_lock = threading.Lock()
_disconnected = set()


def submit(owner, name, args, call_id, session=""):
    """Called off the main thread; no bpy access, automatic retries or eval."""
    schema.validate(name, args)
    owner, call_id = str(uuid.UUID(owner)), str(uuid.UUID(call_id))
    if not _registered or _receipts is None:
        raise UIError("not_ready", "Mixar UI controller is starting")
    if name == "mixar_ui_call_status":
        return envelope(_receipts.status(str(uuid.UUID(args["call_id"]))), call_id)
    if name == "mixar_ui_act":
        digest = _receipts.digest(session, name, args)
        prior = _receipts.prior(call_id, digest)
        if prior:
            return envelope(prior, call_id, failed=prior["status"] != "succeeded")
    timeout = args.get("timeout", ACTION_TIMEOUT) + 2 if name == "mixar_ui_wait" else ACTION_TIMEOUT
    req = Request(owner, name, args, call_id, session, time.monotonic()+timeout)
    with _request_lock:
        if (owner, call_id) in _requests:
            raise UIError("call_pending", "This UI call is already pending; inspect its receipt")
        _requests[owner, call_id] = req
    try:
        _queue.put_nowait(req)
    except queue.Full:
        with _request_lock:
            _requests.pop((owner, call_id), None)
        raise UIError("ui_busy", "UI request queue is full; no action accepted") from None
    if not req.done.wait(timeout+1):
        req.cancelled.set()
        return envelope({"error_type": "outcome_unknown", "call_id": call_id,
                         "error": "UI response timed out; inspect the receipt and current UI before further action"},
                        call_id, failed=True)
    return req.result


def cancel(owner, call_id=None):
    """Thread-safe cancellation, including requests not yet admitted."""
    with _request_lock:
        if call_id is None and len(_disconnected) < MAX_PENDING:
            _disconnected.add(owner)
        for (principal, identity), req in _requests.items():
            if principal == owner and (call_id is None or identity == call_id):
                req.cancelled.set()


def envelope(result, call_id, *, failed=False, blocks=()):
    import json
    usage = {"request_id": call_id, "surface": "local_ui", "invocation_credits": 0,
             "credits_charged": 0, "generation_credits": None,
             "generation_billing": "existing_job_queue"}
    payload = {"result": result, "usage": usage}
    return {"content": [{"type": "text", "text": json.dumps(payload)}, *blocks],
            "structuredContent": payload, "isError": failed,
            "_meta": {"mixar/request-id": call_id, "mixar/usage": usage}}


def _eligible():
    from mixar.modules.mcp_bridge.core import runtime, eligibility
    if not runtime.enabled():
        raise UIError("mcp_disabled", "Mixar MCP is disabled")
    wm = bpy.context.window_manager
    if (not getattr(wm, "mixie_chat_is_logged_in", False)
            or getattr(wm, "mixie_chat_session_expired", False) or not eligibility.valid()):
        raise UIError("account_not_ready", "Wait for Mixar sign-in and UI eligibility renewal")


def _run(req):
    from mixar.modules.mcp_bridge.core import eligibility
    win = observe.main_window()
    if req.session and win.scene.mixie_session_id != req.session:
        raise UIError("context_changed", "The selected scene is no longer active; inspect the current context")
    if req.name == "mixar_ui_context":
        if req.args.get("release"):
            ownership.release(req.owner, require_settled=True)
        return {"contract": "mixar_ui_v1", "session_id": win.scene.mixie_session_id,
                "scene_name": win.scene.name, "eligible": eligibility.valid(),
                "input_busy": ownership.active(), "event_simulate": bpy.app.use_event_simulate}, []
    if req.name == "mixar_ui_observe":
        if req.args.get("image"):
            # Let cached window buffers catch up before returning pixels. Merely
            # tagging one redraw can still expose the previous frame on Metal.
            for _ in range(3):
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        area.tag_redraw()
                yield 0.05
        return observe.observe(req.owner, req.args)
    if req.name == "mixar_ui_act":
        _eligible()
        digest = _receipts.digest(req.session, req.name, req.args)
        prior = _receipts.prior(req.call_id, digest)
        if prior:
            return prior, []
        observe.resolve(req.owner, req.args["context"], req.args["target"])
        ownership.available()
        _receipts.claim(req.call_id, digest)
        req.claimed = True
        return (yield from native_input.run(req.owner, req.args)), []
    if req.name == "mixar_ui_wait":
        end = time.monotonic()+req.args.get("timeout", 10)
        while True:
            found = any(observe.matches(w, req.args["query"]) for w in observe.widgets())
            if found == req.args.get("present", True):
                return {"condition_met": True}, []
            if time.monotonic() >= end:
                return {"condition_met": False}, []
            yield 0.05


def _finish(req, result, *, failed=False, status="succeeded", blocks=()):
    if req.name == "mixar_ui_act":
        if req.claimed:
            # Even geometry edits that leave the view matrix unchanged consume
            # their observation. Receipt replay is resolved before target lookup.
            observe.invalidate()
        if failed:
            ownership.release(req.owner)
        try:
            if req.claimed:
                _receipts.finish(req.call_id, status)
        except Exception:
            failed = True
            result = {**result, "error_type": "outcome_unknown", "receipt_status": "outcome_unknown"}
    req.result = envelope(result, req.call_id, failed=failed, blocks=blocks)
    req.done.set()
    with _request_lock:
        _requests.pop((req.owner, req.call_id), None)


def _pump():
    global _active
    if not _registered:
        return None
    with _request_lock:
        disconnected = list(_disconnected)
        _disconnected.clear()
    for owner in disconnected:
        ownership.release(owner)
    ownership.active()  # Also expires an idle native lease and releases held input.
    if _active is None:
        try:
            req = _queue.get_nowait()
        except queue.Empty:
            return 0.05
        _active = (req, _run(req))
    req, gen = _active
    try:
        if req.cancelled.is_set() or time.monotonic() >= req.deadline:
            raise UIError("outcome_unknown", "Action interrupted; partial effects may remain")
        if req.name == "mixar_ui_act":
            _eligible()
        delay = next(gen)
        return min(0.1, max(0.02, float(delay or 0.02)))
    except StopIteration as done:
        result, blocks = done.value
        _finish(req, result, blocks=blocks)
    except UIError as exc:
        _finish(req, exc.result(), failed=True,
                status="outcome_unknown" if req.claimed else "failed")
    except Exception:
        _finish(req, {"error_type": "outcome_unknown", "error": "UI operation could not complete; inspect the current UI"},
                failed=True, status="outcome_unknown")
    finally:
        if req.done.is_set():
            gen.close()
            _active = None
    return 0.02


@bpy.app.handlers.persistent
def invalidate(*_args):
    observe.invalidate()
    ownership.release()
    if _active:
        _active[0].cancelled.set()
    # Existing observations can never resolve in the replacement document.


def register():
    global _registered, _receipts
    if _registered:
        return
    if not hasattr(bpy.context.window_manager, "mixar_ui_enable"):
        return
    path = Path(bpy.utils.user_resource('CONFIG')) / "mixar" / "ui-control" / "receipts.sqlite"
    _receipts = Receipts(path)
    _registered = True
    for name in ("load_pre", "undo_pre", "redo_pre"):
        handlers = getattr(bpy.app.handlers, name)
        if invalidate not in handlers:
            handlers.append(invalidate)
    bpy.app.timers.register(_pump, first_interval=0.1, persistent=True)


def unregister(shutdown=False):
    global _registered, _receipts
    _registered = False
    if not shutdown and _receipts is not None:
        invalidate()
        bpy.context.window_manager.mixar_ui_enable(enabled=False)
        for name in ("load_pre", "undo_pre", "redo_pre"):
            handlers = getattr(bpy.app.handlers, name)
            if invalidate in handlers:
                handlers.remove(invalidate)
        if bpy.app.timers.is_registered(_pump):
            bpy.app.timers.unregister(_pump)
    else:
        ownership.forget()
    if _receipts:
        _receipts.close()
        _receipts = None
