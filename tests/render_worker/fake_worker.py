# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""A stand-in render worker for the supervisor tests: speaks the real protocol
(``common/render_worker/protocol.py``) from a plain Python process.

Env ``FAKE_BOOT``: ``ok`` (default) | ``fail`` (exit before ``ready``) |
``hang`` (never ready). A job's ``params.mode``: ``ok`` | ``hang`` | ``fail``;
the supervisor's crash hook (``"crash": "segv"``) kills the process with SIGSEGV
after ``started``, as a native crash would.
"""

import json
import os
import signal
import sys
import time

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("protocol", sys.argv[1])
protocol = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(protocol)


def emit(message):
    os.write(1, protocol.encode(message).encode("utf-8"))


boot = os.environ.get("FAKE_BOOT", "ok")
if boot == "fail":
    sys.exit(3)
if boot == "hang":
    time.sleep(60)
print("Blender-like noise without a newline", end="", flush=True)
emit({"type": "ready", "pid": os.getpid(), "boot_s": 0.01})
for line in sys.stdin:
    message = protocol.decode(line)
    if message is None:
        continue
    if message["type"] == "quit":
        break
    emit({"type": "started", "job": message["job"]})
    if message.get("crash") == "segv":
        os.kill(os.getpid(), signal.SIGSEGV)
    mode = (message.get("params") or {}).get("mode", "ok")
    if mode == "hang":
        time.sleep(60)
    if mode == "fail":
        emit({"type": "result", "job": message["job"], "ok": False, "error": "worker_job_failed"})
        continue
    with open(message["out"], "w", encoding="utf-8") as handle:
        json.dump({"echo": message.get("params"), "pid": os.getpid()}, handle)
    emit({"type": "result", "job": message["job"], "ok": True, "out": message["out"],
          "seconds": {"run": 0.0}})
emit({"type": "exit", "reason": "quit"})
