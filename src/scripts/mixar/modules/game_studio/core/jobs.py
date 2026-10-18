# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Build / export / publish job registry (contract §5 ``game_job_status``).

Workers write state under a lock and never touch ``bpy``. Anything that
must reach Blender data (storing the published game id on the scene) is
queued with ``call_on_main`` and drained on the main thread — by the UI
pump timer in the app, and by every ``agent_api`` call, so a
``--background`` session (where timers never fire mid-script) still sees
it. The pump only tags the View3D sidebar for redraw when state changed,
and stops once nothing runs.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections import OrderedDict

from ..constants import JOB_DONE, JOB_FAILED, JOB_RUNNING, MAX_JOBS, PUMP_SECONDS

_lock = threading.Lock()
_jobs: "OrderedDict[str, dict]" = OrderedDict()
_cancel: dict[str, threading.Event] = {}
_last: dict[str, str] = {}
_main_queue: list = []
_watchers: list = []
_state = {"dirty": False, "pump": False}


class JobHandle:
    """What a worker sees of its job."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.cancel_event = _cancel[job_id]
        self._last_report = 0.0

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def progress(self, pct: float, message: str = "", force: bool = False) -> None:
        """Throttled to ~10 updates a second unless ``force``."""
        now = time.monotonic()
        if not force and now - self._last_report < 0.1:
            return
        self._last_report = now
        update(self.job_id, pct=pct, message=message)


def _public(job: dict) -> dict:
    return {key: job[key] for key in ("job_id", "kind", "state", "pct", "message",
                                      "result", "error", "error_code")}


def create(kind: str) -> str:
    job_id = uuid.uuid4().hex
    now = time.time()
    with _lock:
        _jobs[job_id] = {"job_id": job_id, "kind": kind, "state": JOB_RUNNING, "pct": 0.0,
                         "message": "", "result": None, "error": None, "error_code": None,
                         "created": now, "updated": now}
        _cancel[job_id] = threading.Event()
        _last[kind] = job_id
        while len(_jobs) > MAX_JOBS:
            old_id, old = next(iter(_jobs.items()))
            if old["state"] == JOB_RUNNING:
                break
            _jobs.pop(old_id)
            _cancel.pop(old_id, None)
        _state["dirty"] = True
    return job_id


def update(job_id: str, pct=None, message=None) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job["state"] != JOB_RUNNING:
            return
        if pct is not None:
            job["pct"] = round(max(job["pct"], min(100.0, float(pct))), 1)
        if message is not None:
            job["message"] = str(message)
        job["updated"] = time.time()
        _state["dirty"] = True


def finish(job_id: str, result=None, error=None, error_code=None) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job["state"] != JOB_RUNNING:
            return
        failed = bool(error or error_code)
        job.update(state=JOB_FAILED if failed else JOB_DONE, result=result,
                   error=str(error) if error else None,
                   error_code=str(error_code or "failed") if failed else None,
                   pct=job["pct"] if failed else 100.0, updated=time.time())
        _state["dirty"] = True


def get(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(str(job_id or ""))
        return _public(job) if job else None


def last(kind: str) -> dict | None:
    with _lock:
        job = _jobs.get(_last.get(kind, ""))
        return _public(job) if job else None


def latest_settled() -> dict | None:
    """The most recently created job that has finished (done or failed)."""
    with _lock:
        for job in reversed(_jobs.values()):
            if job["state"] != JOB_RUNNING:
                return _public(job)
    return None


def running(kind: str | None = None) -> dict | None:
    with _lock:
        for job in reversed(_jobs.values()):
            if job["state"] == JOB_RUNNING and (kind is None or job["kind"] == kind):
                return _public(job)
    return None


def cancel(job_id: str) -> bool:
    with _lock:
        event = _cancel.get(str(job_id or ""))
        job = _jobs.get(str(job_id or ""))
        if event is None or job is None or job["state"] != JOB_RUNNING:
            return False
        event.set()
        return True


def start(kind: str, work) -> str:
    """Run ``work(handle)`` on a daemon thread. Its return value is the job
    result; raising ``JobError`` (or anything) fails the job."""
    job_id = create(kind)
    handle = JobHandle(job_id)

    def body():
        try:
            result = work(handle)
        except JobError as exc:
            finish(job_id, result=exc.result, error=exc.message, error_code=exc.code)
        except Exception as exc:  # noqa: BLE001 — a worker must always settle its job
            traceback.print_exc()
            finish(job_id, error=f"{exc.__class__.__name__}: {exc}"[:300], error_code="internal_error")
        else:
            if handle.cancelled:
                finish(job_id, result=result, error="Cancelled.", error_code="cancelled")
            else:
                finish(job_id, result=result)

    threading.Thread(target=body, name=f"mixar-game-{kind}", daemon=True).start()
    ensure_pump()
    return job_id


class JobError(Exception):
    def __init__(self, message: str, code: str = "failed", result=None):
        super().__init__(message)
        self.message, self.code, self.result = message, code, result


def call_on_main(callback) -> None:
    """Queue ``callback()`` for the main thread (drained by ``drain``)."""
    with _lock:
        _main_queue.append(callback)
        _state["dirty"] = True


def drain() -> None:
    """Run queued main-thread callbacks. Main thread only."""
    with _lock:
        pending = list(_main_queue)
        _main_queue.clear()
    for callback in pending:
        try:
            callback()
        except Exception:  # noqa: BLE001 — one bad callback must not strand the rest
            traceback.print_exc()


def watch(predicate) -> None:
    """Keep the UI pump alive while ``predicate()`` is true (a background
    Godot locate), then redraw once. Main thread only."""
    with _lock:
        _watchers.append(predicate)
    ensure_pump()


def _tag_sidebars() -> None:
    import bpy
    wm = getattr(bpy.context, "window_manager", None)
    for window in getattr(wm, "windows", ()) or ():
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'UI':
                        region.tag_redraw()


def _pump():
    drain()
    with _lock:
        dirty = _state["dirty"]
        _state["dirty"] = False
        watching = []
        for predicate in _watchers:
            try:
                if predicate():
                    watching.append(predicate)
            except Exception:
                pass
        if len(watching) != len(_watchers):
            dirty = True
        _watchers[:] = watching
        busy = (any(job["state"] == JOB_RUNNING for job in _jobs.values())
                or bool(_main_queue) or bool(watching))
        if not busy:
            _state["pump"] = False
    if dirty:
        try:
            _tag_sidebars()
        except Exception:
            pass
    return PUMP_SECONDS if busy else None


def ensure_pump() -> None:
    """Start the UI pump (no-op in ``--background``, where nothing draws)."""
    try:
        import bpy
        if bpy.app.background:
            return
        with _lock:
            if _state["pump"]:
                return
            _state["pump"] = True
        bpy.app.timers.register(_pump, first_interval=PUMP_SECONDS, persistent=True)
    except Exception:
        with _lock:
            _state["pump"] = False


def reset_for_tests() -> None:
    with _lock:
        _jobs.clear()
        _cancel.clear()
        _last.clear()
        _main_queue.clear()
        _watchers.clear()
        _state.update(dirty=False, pump=False)
