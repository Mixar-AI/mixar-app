# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Child entry point: ``<Mixar binary> --background -noaudio --python worker_main.py``.

Started by :mod:`supervisor` with the app's own binary and user preferences, so
the worker has the same engines, add-ons, colour management and compute
devices. It never connects to the backend: Mixar's connection starts from
timers and the login UI, and ``--background`` runs neither.

Boot: every Mixar UI module is registered at once (``bootstrap`` defers them to
timers, which a background process never runs; paint export needs
``ShaderNodeTree.mp``), every app handler is dropped (a worker reacts to no
file load, save or depsgraph event), the Cycles compute device the user enabled
is switched on, and the process lowers its own priority so the user's app is
served first. Then it reports ``ready`` and reads jobs from stdin, one at a time.

Exit: stdin closing (the app quit or died), a ``quit`` message, or memory
above :data:`RECYCLE_RSS_MB` after a job (the supervisor starts a fresh one on
the next job). ``os._exit`` skips Blender's exit path: nothing of the user's
(preferences, recent files) is written by a worker.
"""

import os
import sys
import time

_BOOT_STARTED = time.monotonic()
RECYCLE_RSS_MB = 3072


def _emit(message):
    from mixar.modules.common.render_worker import protocol
    data = protocol.encode(message).encode("utf-8")
    # One write per line: a pipe write under PIPE_BUF is atomic, so Blender's own
    # stdout cannot split a message (the parent also finds the marker mid-line).
    os.write(1, data)


def _rss_mb() -> float:
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak / (1048576.0 if sys.platform == "darwin" else 1024.0)
    except Exception:
        return 0.0


def _register_ui_modules():
    bootstrap = sys.modules.get("bootstrap")
    if bootstrap is None:
        try:
            import bootstrap  # noqa: F401 — Blender's startup package
            bootstrap = sys.modules.get("bootstrap")
        except Exception:
            return
    tick = getattr(bootstrap, "_load_ui_batch_tick", None)
    if tick is None or getattr(bootstrap, "_ui_loading_complete", False):
        return
    bootstrap._UI_BATCH_BUDGET_MS = 10 ** 9
    for _ in range(10000):
        if tick() is None:
            break


def _drop_handlers():
    import bpy
    for name in dir(bpy.app.handlers):
        handlers = getattr(bpy.app.handlers, name, None)
        if isinstance(handlers, list):
            handlers.clear()


def _lower_priority():
    try:
        if hasattr(os, "nice"):
            os.nice(5)
    except OSError:
        pass


def _enable_compute_device():
    try:
        from mixar.modules.space_mixie_chat.core import render_device
        if render_device.preference() != "CPU":
            render_device.enable_gpu_device()
    except Exception:
        pass


def main():
    _lower_priority()
    _register_ui_modules()
    _drop_handlers()
    _enable_compute_device()
    from mixar.modules.common.render_worker import protocol, worker_jobs
    _emit({"type": "ready", "pid": os.getpid(),
           "boot_s": round(time.monotonic() - _BOOT_STARTED, 3)})
    reason = "stdin_closed"
    for line in sys.stdin:
        message = protocol.decode(line)
        if message is None:
            continue
        if message.get("type") == "quit":
            reason = "quit"
            break
        if message.get("type") != "job":
            continue
        _emit({"type": "started", "job": message.get("job")})
        outcome = worker_jobs.run(message)
        _emit(dict(outcome, type="result", job=message.get("job")))
        if _rss_mb() > RECYCLE_RSS_MB:
            reason = "recycle"
            break
    _emit({"type": "exit", "reason": reason})
    try:
        import bpy
        import shutil
        shutil.rmtree(bpy.app.tempdir, ignore_errors=True)
    except Exception:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
