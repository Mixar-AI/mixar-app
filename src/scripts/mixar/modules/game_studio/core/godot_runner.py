# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run the Mixar Godot fork headless (contract §3) on a worker thread.

``run`` streams stdout, turns each ``MIXAR_PROGRESS {json}`` line into an
``on_progress(pct, step, message)`` call, honours a cancel event and a
timeout, and returns the ``mixar_godot_result_v1`` dict — read from the
result file the fork always writes, or synthesised from the exit code
when the process died before writing it. Never touches ``bpy``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections import deque

from ..constants import BUILD_TIMEOUT_S, EXIT_CODES, PROGRESS_PREFIX, RESULT_SCHEMA

TAIL_LINES = 30


def parse_progress(line: str) -> dict | None:
    """``{"step", "pct", "message"}`` from one stdout line, or None."""
    line = str(line or "").strip()
    if not line.startswith(PROGRESS_PREFIX.strip()):
        return None
    try:
        data = json.loads(line[len(PROGRESS_PREFIX.strip()):].strip())
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        pct = max(0.0, min(100.0, float(data.get("pct", 0))))
    except (TypeError, ValueError):
        pct = 0.0
    return {"step": str(data.get("step") or ""), "pct": pct,
            "message": str(data.get("message") or "")}


def read_result(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != RESULT_SCHEMA:
        return None
    return data


def synthesize_result(action: str, returncode, tail, reason: str = "") -> dict:
    code = EXIT_CODES.get(returncode, "failed") if returncode is not None else "failed"
    if reason:
        code = reason
    message = {
        "cancelled": "Cancelled.",
        "timeout": "Godot took too long and was stopped.",
        "launch_failed": "Godot could not be started.",
    }.get(code, "")
    if not message:
        last = next((line for line in reversed(list(tail)) if line.strip()), "")
        message = f"Godot exited with code {returncode}" + (f": {last.strip()[:240]}" if last else ".")
    return {"schema": RESULT_SCHEMA, "ok": False, "action": action, "project_dir": None,
            "artifact": None, "platform": None, "warnings": [], "error": message,
            "error_code": code or "failed", "duration_s": None, "stats": {}}


def _popen_kwargs() -> dict:
    if sys.platform.startswith("win"):
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def run(binary: str, args: list, result_path: str, action: str, on_progress=None,
        cancel: threading.Event | None = None, timeout: float = BUILD_TIMEOUT_S,
        popen=subprocess.Popen) -> dict:
    """Blocking: run ``binary args… --mixar-result result_path``. Worker
    threads only."""
    try:
        os.remove(result_path)  # never mistake a previous run's file for this one
    except OSError:
        pass
    command = [binary, *args, "--mixar-result", result_path]
    tail: deque = deque(maxlen=TAIL_LINES)
    started = time.monotonic()
    try:
        process = popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                        errors="replace", bufsize=1, **_popen_kwargs())
    except OSError:
        return synthesize_result(action, None, tail, "launch_failed")
    stopped = {"reason": ""}
    done = threading.Event()

    def watchdog():
        while not done.wait(0.2):
            reason = ""
            if cancel is not None and cancel.is_set():
                reason = "cancelled"
            elif time.monotonic() - started > timeout:
                reason = "timeout"
            if reason:
                stopped["reason"] = reason
                try:
                    process.terminate()
                    process.wait(5)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
                return

    guard = threading.Thread(target=watchdog, name="mixar-godot-watchdog", daemon=True)
    guard.start()
    try:
        for line in process.stdout:
            progress = parse_progress(line)
            if progress is not None:
                if on_progress is not None:
                    on_progress(progress["pct"], progress["step"], progress["message"])
            else:
                tail.append(line.rstrip("\n"))
        returncode = process.wait()
    finally:
        done.set()
        try:
            process.stdout.close()
        except Exception:
            pass
    if stopped["reason"]:
        return synthesize_result(action, returncode, tail, stopped["reason"])
    result = read_result(result_path)
    if result is None:
        return synthesize_result(action, returncode, tail)
    if returncode != 0 and result.get("ok"):
        result["ok"] = False
        result["error_code"] = result.get("error_code") or EXIT_CODES.get(returncode, "failed")
    if not result.get("ok") and not result.get("error_code"):
        result["error_code"] = EXIT_CODES.get(returncode, "failed") or "failed"
    result.setdefault("duration_s", round(time.monotonic() - started, 2))
    return result


def launch(binary: str, args: list, popen=subprocess.Popen) -> bool:
    """Start Godot detached (Play); the game window outlives nothing of ours."""
    kwargs = _popen_kwargs()
    if not sys.platform.startswith("win"):
        kwargs["start_new_session"] = True
    try:
        popen([binary, *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, **kwargs)
    except OSError:
        return False
    return True
