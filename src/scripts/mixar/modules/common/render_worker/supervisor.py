# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parent side: the background worker processes and the jobs they run.

One warm worker per job kind (``preview``, ``export``), started on the first
job and stopped after :data:`IDLE_TTL_S` without work, so a burst of agent
previews pays the process start once and an idle app holds no extra memory.
Jobs of one kind run in order on that kind's worker.

Failure model (every outcome is a fixed code, never a path or exception text):

- The worker dies AFTER it reported ``started`` for a job: a crash in the job.
  The job is sent again to a fresh worker once; a second crash fails it with
  ``worker_crashed``. The user's process never ran the job, so nothing of the
  user's is lost.
- The worker dies, or does not report ``ready`` within :data:`BOOT_TIMEOUT_S`,
  BEFORE it started the job: a boot failure. One more boot is tried; a second
  failure fails the job with ``worker_unavailable`` and, after
  :data:`MAX_BOOT_FAILURES` in a row, the session stops starting workers
  (:func:`available` is False) so every caller takes its in-process path.
- A job over its deadline is killed with its worker: ``worker_timeout``.
- :func:`cancel` kills the worker running the job (the only reliable way to
  stop native code); the next job starts a fresh one.

State is touched on the main thread only (:func:`submit`, :func:`poll`,
:func:`cancel`, :func:`maintain`); each worker's stdout reader thread only
fills a queue and a bounded log. :func:`shutdown_all` is safe from ``atexit``.
No ``bpy`` at module level.
"""

import itertools
import os
import queue
import subprocess
import tempfile
import threading
import time

from mixar.config.logging_config import get_logger

from . import protocol

logger = get_logger(__name__)

IDLE_TTL_S = 120.0
BOOT_TIMEOUT_S = 60.0
MAX_BOOT_FAILURES = 2
MAX_JOB_ATTEMPTS = 2
LOG_LIMIT_BYTES = 2 * 1024 * 1024
MAINTAIN_INTERVAL_S = 5.0

_lock = threading.Lock()
_workers = {}          # kind -> _Worker
_jobs = {}             # job id -> dict (main thread)
_queue = {}            # kind -> [job id, ...] waiting for that kind's worker
_ids = itertools.count(1)
_boot_failures = 0
_disabled_reason = ""
_crash_next = {}       # kind -> how many next jobs crash on purpose (QA)
_maintain_registered = False


_swept = False


def _parent_dir() -> str:
    return os.path.join(tempfile.gettempdir(), "mixar_render_worker")


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        return True  # stale folders there are left to the age rule below
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _sweep_stale() -> None:
    """Folders of app sessions that ended without cleaning up (a crash, a kill)."""
    import shutil
    parent = _parent_dir()
    try:
        names = os.listdir(parent)
    except OSError:
        return
    for name in names:
        if not name.isdigit() or int(name) == os.getpid():
            continue
        path = os.path.join(parent, name)
        try:
            old = time.time() - os.path.getmtime(path) > 86400
        except OSError:
            continue
        if old or not _pid_alive(int(name)):
            shutil.rmtree(path, ignore_errors=True)


def root_dir() -> str:
    """The folder that holds snapshots, job outputs, worker logs and the
    worker's own temp dir (so its crash report lands here, never beside the
    app's own ``mixar.crash.txt``)."""
    global _swept
    if not _swept:
        _swept = True
        _sweep_stale()
    base = os.path.join(_parent_dir(), str(os.getpid()))
    os.makedirs(base, exist_ok=True)
    return base


def _worker_main_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker_main.py")


def _argv() -> list:
    """The app's own binary, headless, with the user's preferences (same engines,
    add-ons and compute devices) and no audio device."""
    return [_binary_path(), "--background", "-noaudio", "--python", _worker_main_path()]


def _binary_path() -> str:
    try:
        import bpy
        if getattr(bpy.app, "background", False):
            return ""  # a worker never starts workers
        return str(bpy.app.binary_path or "")
    except Exception:
        return ""


def available() -> bool:
    """Whether jobs go to a worker. False on a binary we cannot find, inside a
    worker, or after repeated boot failures this session."""
    if _disabled_reason:
        return False
    path = _binary_path()
    return bool(path) and os.path.isfile(path)


def disabled_reason() -> str:
    return _disabled_reason


def _popen_kwargs(env, log_dir):
    kwargs = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
              "env": env, "cwd": log_dir, "close_fds": True, "text": True, "bufsize": 1,
              "encoding": "utf-8", "errors": "replace"}
    if os.name == "nt":
        # No console window; below-normal priority so the user's app stays first.
        kwargs["creationflags"] = 0x08000000 | 0x00000200 | 0x00004000
    else:
        kwargs["start_new_session"] = True
    return kwargs


class _Worker:
    """One child process and the thread that reads its stdout."""

    def __init__(self, kind):
        self.kind = kind
        self.ready = False
        self.job = None            # the job id sent to it, until its result
        self.started_job = False   # the worker reported ``started`` for self.job
        self.spawned_at = time.monotonic()
        self.last_used = self.spawned_at
        self.boot_s = None
        self.messages = queue.Queue()
        folder = os.path.join(root_dir(), "worker-" + kind)
        os.makedirs(os.path.join(folder, "tmp"), exist_ok=True)
        self.folder = folder
        env = dict(os.environ)
        env.update({"MIXAR_RENDER_WORKER": "1", "MIXAR_RENDER_WORKER_KIND": kind,
                    "MIXAR_RENDER_WORKER_PARENT_PID": str(os.getpid()),
                    # Blender's temp dir, crash report included, stays in the worker folder.
                    "TMPDIR": os.path.join(folder, "tmp"), "TEMP": os.path.join(folder, "tmp"),
                    "TMP": os.path.join(folder, "tmp")})
        argv = _argv()
        self.log_path = os.path.join(folder, "worker.log")
        self.proc = subprocess.Popen(argv, **_popen_kwargs(env, folder))
        self.pid = self.proc.pid
        self._reader = threading.Thread(target=self._read, name="mixar-render-worker-" + kind,
                                        daemon=True)
        self._reader.start()

    def _read(self):
        written = 0
        try:
            log = open(self.log_path, "a", encoding="utf-8", errors="replace")
        except OSError:
            log = None
        try:
            for line in self.proc.stdout:
                message = protocol.decode(line)
                if message is not None:
                    self.messages.put(message)
                elif log is not None and written < LOG_LIMIT_BYTES:
                    log.write(line)
                    written += len(line)
        except (OSError, ValueError):
            pass
        finally:
            if log is not None:
                log.close()

    def alive(self) -> bool:
        return self.proc.poll() is None

    def send(self, message) -> bool:
        try:
            self.proc.stdin.write(protocol.encode(message))
            self.proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def kill(self):
        proc = self.proc
        if proc.poll() is not None:
            return
        try:
            proc.kill()
        except OSError:
            pass
        threading.Thread(target=_reap, args=(proc,), daemon=True).start()

    def stop(self):
        """Polite stop of an idle worker: ``quit``, then a kill if it lingers."""
        if not self.send({"type": "quit"}):
            self.kill()
            return
        threading.Thread(target=_reap, args=(self.proc, 10.0), daemon=True).start()


def _reap(proc, grace=5.0):
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    except Exception:
        pass
    for stream in (proc.stdin, proc.stdout):
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass


def crash_next(kind: str, count: int = 1) -> None:
    """QA hook: the next ``count`` jobs of ``kind`` crash their worker with a
    native SIGSEGV after they started, to prove the app survives and retries."""
    _crash_next[kind] = max(0, int(count))


def _new_job_id() -> str:
    return "j%d-%d" % (os.getpid(), next(_ids))


def submit(kind: str, message: dict, *, timeout_s: float) -> str:
    """Queue ``message`` (a protocol ``job`` without ``type``/``job``) for the
    ``kind`` worker; returns the job id. Never blocks on the worker."""
    if kind not in protocol.JOB_KINDS:
        raise ValueError("unknown worker job kind")
    job_id = _new_job_id()
    _jobs[job_id] = {"id": job_id, "kind": kind, "message": dict(message), "attempts": 0,
                     "boots": 0, "state": "queued", "error": "", "out": "",
                     "submitted": time.monotonic(), "timeout_s": float(timeout_s),
                     "deadline": None, "seconds": {}, "pid": None}
    _queue.setdefault(kind, []).append(job_id)
    _ensure_maintenance()
    _dispatch(kind)
    return job_id


def _spawn(kind):
    global _boot_failures, _disabled_reason
    try:
        worker = _Worker(kind)
    except Exception as exc:
        _boot_failures += 1
        logger.warning("Render worker %s could not start (%s)", kind, exc.__class__.__name__)
        if _boot_failures >= MAX_BOOT_FAILURES:
            _disabled_reason = "spawn_failed"
        return None
    with _lock:
        _workers[kind] = worker
    logger.info("Render worker %s started pid=%s", kind, worker.pid)
    return worker


def _dispatch(kind):
    pending = _queue.get(kind) or []
    if not pending:
        return
    worker = _workers.get(kind)
    if worker is not None and not worker.alive():
        _on_death(worker)
        worker = _workers.get(kind)
    if worker is None:
        worker = _spawn(kind)
        if worker is None:
            for job_id in list(pending):
                _fail(job_id, "worker_unavailable")
            pending.clear()
            return
    if worker.job is not None:
        return
    job_id = pending.pop(0)
    job = _jobs.get(job_id)
    if job is None:
        return _dispatch(kind)
    message = dict(job["message"], type="job", job=job_id)
    if _crash_next.get(kind, 0) > 0:
        _crash_next[kind] -= 1
        message["crash"] = "segv"
    job["attempts"] += 1
    job["state"] = "running"
    job["pid"] = worker.pid
    job["sent"] = time.monotonic()
    worker.job, worker.started_job = job_id, False
    worker.last_used = time.monotonic()
    if not worker.send(message):
        # A worker that cannot take input is dead or dying: settle it now.
        worker.kill()
        _on_death(worker)


def _requeue(job_id):
    job = _jobs.get(job_id)
    if job is None:
        return
    job["state"] = "queued"
    _queue.setdefault(job["kind"], []).insert(0, job_id)


def _fail(job_id, code):
    job = _jobs.get(job_id)
    if job is not None and job["state"] not in ("done", "failed", "cancelled"):
        job["state"], job["error"] = "failed", code


def _crash_summary(worker) -> str:
    """First lines of the worker's own crash report (local log only)."""
    try:
        folder = os.path.join(worker.folder, "tmp")
        reports = sorted((os.path.join(folder, name) for name in os.listdir(folder)
                          if name.endswith(".crash.txt")), key=os.path.getmtime)
        if not reports:
            return ""
        with open(reports[-1], encoding="utf-8", errors="replace") as handle:
            lines = handle.read(4000).splitlines()
        return " | ".join(line.strip() for line in lines[:12] if line.strip())
    except OSError:
        return ""


def _on_death(worker):
    """A worker process ended: settle its job (retry, fail) and forget it."""
    global _boot_failures, _disabled_reason
    with _lock:
        if _workers.get(worker.kind) is worker:
            del _workers[worker.kind]
    job_id, started = worker.job, worker.started_job
    worker.job = None
    code = worker.proc.returncode
    if job_id is None:
        return
    job = _jobs.get(job_id)
    if job is None or job["state"] != "running":
        return
    if not started and not worker.ready:
        _boot_failures += 1
        job["boots"] += 1
        job["attempts"] -= 1  # the job never ran
        logger.warning("Render worker %s exited before it was ready (code %s)", worker.kind, code)
        if _boot_failures >= MAX_BOOT_FAILURES:
            _disabled_reason = "boot_failed"
        if job["boots"] >= MAX_BOOT_FAILURES:
            _fail(job_id, "worker_unavailable")
        else:
            _requeue(job_id)
        return
    logger.warning("Render worker %s crashed in job %s (code %s, attempt %d): %s",
                   worker.kind, job_id, code, job["attempts"], _crash_summary(worker))
    if job["attempts"] >= MAX_JOB_ATTEMPTS:
        _fail(job_id, "worker_crashed")
    else:
        job["retried_after_crash"] = True
        _requeue(job_id)


def _handle(worker, message):
    global _boot_failures
    kind = message.get("type")
    if kind == "ready":
        worker.ready = True
        worker.boot_s = message.get("boot_s")
        _boot_failures = 0
    elif kind == "started" and message.get("job") == worker.job:
        worker.started_job = True
        job = _jobs.get(worker.job)
        if job is not None:
            job["deadline"] = time.monotonic() + job["timeout_s"]
    elif kind == "result" and message.get("job") == worker.job:
        job = _jobs.get(worker.job)
        worker.job, worker.started_job = None, False
        worker.last_used = time.monotonic()
        if job is not None and job["state"] == "running":
            job["seconds"] = dict(message.get("seconds") or {}, boot=worker.boot_s)
            if message.get("ok"):
                job["state"], job["out"] = "done", str(message.get("out") or "")
            else:
                job["state"], job["error"] = "failed", str(message.get("error") or "worker_failed")


def _pump(worker):
    while True:
        try:
            message = worker.messages.get_nowait()
        except queue.Empty:
            break
        _handle(worker, message)
    now = time.monotonic()
    job = _jobs.get(worker.job) if worker.job else None
    if not worker.alive():
        # Drain what it wrote before it died (a result can race the exit).
        while True:
            try:
                _handle(worker, worker.messages.get_nowait())
            except queue.Empty:
                break
        _on_death(worker)
        return
    if not worker.ready and not worker.started_job and now - worker.spawned_at > BOOT_TIMEOUT_S:
        logger.warning("Render worker %s did not start within %.0fs", worker.kind, BOOT_TIMEOUT_S)
        worker.kill()
        _on_death(worker)
        return
    if job is not None and job.get("deadline") and now > job["deadline"]:
        logger.warning("Render worker %s job %s timed out", worker.kind, worker.job)
        _fail(worker.job, "worker_timeout")
        worker.job = None
        worker.kill()
        with _lock:
            if _workers.get(worker.kind) is worker:
                del _workers[worker.kind]
        return
    if worker.job is None and now - worker.last_used > IDLE_TTL_S:
        logger.info("Render worker %s idle for %.0fs; stopping", worker.kind, IDLE_TTL_S)
        with _lock:
            if _workers.get(worker.kind) is worker:
                del _workers[worker.kind]
        worker.stop()


def maintain():
    """Advance every worker: messages, deaths, timeouts, idle stops, dispatch."""
    for worker in list(_workers.values()):
        _pump(worker)
    for kind in list(_queue):
        _dispatch(kind)


def poll(job_id: str) -> dict:
    """``{"state": "queued"|"running"|"done"|"failed"|"cancelled", "error",
    "out", "seconds", "attempts"}``; an unknown id reads as ``failed``."""
    maintain()
    job = _jobs.get(job_id)
    if job is None:
        return {"state": "failed", "error": "worker_job_unknown"}
    return {"state": job["state"], "error": job["error"], "out": job["out"],
            "seconds": dict(job["seconds"]), "attempts": job["attempts"],
            "retried_after_crash": bool(job.get("retried_after_crash")), "pid": job["pid"]}


def forget(job_id: str) -> None:
    _jobs.pop(job_id, None)


def cancel(job_id: str) -> None:
    """Stop a job: drop it from the queue, or kill the worker running it."""
    job = _jobs.get(job_id)
    if job is None or job["state"] in ("done", "failed", "cancelled"):
        return
    pending = _queue.get(job["kind"]) or []
    if job_id in pending:
        pending.remove(job_id)
    job["state"] = "cancelled"
    worker = _workers.get(job["kind"])
    if worker is not None and worker.job == job_id:
        worker.job = None
        with _lock:
            if _workers.get(worker.kind) is worker:
                del _workers[worker.kind]
        worker.kill()


def _maintain_tick():
    global _maintain_registered
    try:
        maintain()
    except Exception:
        logger.exception("Render worker maintenance failed")
    if _workers or any(_queue.values()):
        return MAINTAIN_INTERVAL_S
    _maintain_registered = False
    return None


def _ensure_maintenance():
    """Idle reaping needs a tick even when no caller polls."""
    global _maintain_registered
    if _maintain_registered:
        return
    try:
        import bpy
        bpy.app.timers.register(_maintain_tick, first_interval=MAINTAIN_INTERVAL_S, persistent=True)
        _maintain_registered = True
    except Exception:
        pass


def workers() -> dict:
    """Live workers for diagnostics: kind -> {pid, ready, job, boot_s}."""
    return {kind: {"pid": w.pid, "ready": w.ready, "job": w.job, "boot_s": w.boot_s,
                   "alive": w.alive()} for kind, w in list(_workers.items())}


def shutdown_all(remove_files: bool = False) -> None:
    """Kill every worker (and, at app exit, this session's snapshot folder).
    Process and file teardown only, no ``bpy``: safe from atexit."""
    with _lock:
        live = list(_workers.values())
        _workers.clear()
    for worker in live:
        worker.kill()
    if remove_files:
        import shutil
        shutil.rmtree(os.path.join(_parent_dir(), str(os.getpid())), ignore_errors=True)


def reset_for_tests() -> None:
    global _boot_failures, _disabled_reason, _maintain_registered
    shutdown_all()
    _jobs.clear()
    _queue.clear()
    _crash_next.clear()
    _boot_failures = 0
    _disabled_reason = ""
    _maintain_registered = False
