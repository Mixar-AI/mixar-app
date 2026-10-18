# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Find the Mixar Godot fork (contract §3) — always off the main thread.

Discovery order: config ``godot_path`` → env ``MIXAR_GODOT_BIN`` → the
installed ``Mixar Godot.app`` (user, then system) → the dev checkout's
``bin/godot.macos.editor.*`` → Windows ``%LOCALAPPDATA%\\Mixar\\godot`` →
Linux ``~/.local/share/mixar/godot``. Each candidate must answer
``--mixar-version`` with the fork marker; stock Godot is refused with a
message saying so. The verdict is cached per (path, mtime).
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import threading

from ..constants import FORK_MARKER, GODOT_ENV_VAR, VERSION_TIMEOUT_S

_lock = threading.Lock()
_cache: dict = {}          # (path, mtime) -> verdict
_status: dict | None = None  # last locate() verdict
_worker: threading.Thread | None = None


def candidates(config_path: str = "", environ=None, home: str = "",
               platform: str = "") -> list[tuple[str, str]]:
    """``[(source, path)]`` in discovery order; globs are expanded, missing
    files are dropped except the explicit config/env ones (so a typo is
    reported instead of silently skipped)."""
    environ = os.environ if environ is None else environ
    home = home or os.path.expanduser("~")
    platform = platform or sys.platform
    found: list[tuple[str, str]] = []

    def explicit(source, value):
        if value:
            found.append((source, os.path.expanduser(str(value))))

    def pattern(source, value):
        for path in sorted(glob.glob(value)):
            if os.path.isfile(path) and not path.endswith((".dSYM", ".pdb", ".txt")):
                found.append((source, path))

    explicit("config", config_path)
    explicit("env", environ.get(GODOT_ENV_VAR, ""))
    if platform == "darwin":
        pattern("app", os.path.join(home, "Applications", "Mixar Godot.app", "Contents", "MacOS", "*"))
        pattern("app", os.path.join("/Applications", "Mixar Godot.app", "Contents", "MacOS", "*"))
        pattern("dev", os.path.join(home, "Work", "Mixar", "mixar-godot", "bin", "godot.macos.editor.*"))
    elif platform.startswith("win"):
        local = environ.get("LOCALAPPDATA", "")
        if local:
            pattern("app", os.path.join(local, "Mixar", "godot", "mixar-godot*.exe"))
    else:
        pattern("app", os.path.join(home, ".local", "share", "mixar", "godot", "mixar-godot*"))
        pattern("dev", os.path.join(home, "Work", "Mixar", "mixar-godot", "bin", "godot.linuxbsd.editor.*"))
    seen, ordered = set(), []
    for source, path in found:
        if path not in seen:
            seen.add(path)
            ordered.append((source, path))
    return ordered


def parse_version_output(text: str) -> dict | None:
    """The fork's ``--mixar-version`` JSON from mixed stdout, or None."""
    for line in reversed(str(text or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0


def validate(path: str, runner=None) -> dict:
    """Run ``<path> --mixar-version`` and judge it. Never call on the main
    thread: it starts a process."""
    if not path or not os.path.isfile(path):
        return {"found": False, "path": path, "error": "not_found",
                "message": "No file at the configured Godot path."}
    if not os.access(path, os.X_OK):
        return {"found": False, "path": path, "error": "not_executable",
                "message": "The Godot file is not executable."}
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        key = (path, 0.0)
    with _lock:
        if key in _cache:
            return dict(_cache[key])
    run = runner or subprocess.run
    try:
        done = run([path, "--mixar-version"], capture_output=True, text=True,
                   timeout=VERSION_TIMEOUT_S, creationflags=_no_window_flags())
        output = (done.stdout or "") + "\n" + (done.stderr or "")
    except subprocess.TimeoutExpired:
        verdict = {"found": False, "path": path, "error": "version_timeout",
                   "message": "Godot did not answer --mixar-version in time; it is probably "
                              "stock Godot, not the Mixar Godot fork."}
    except OSError as exc:
        verdict = {"found": False, "path": path, "error": "launch_failed",
                   "message": f"Godot could not be started ({exc.__class__.__name__})."}
    else:
        data = parse_version_output(output)
        if not data or data.get("fork") != FORK_MARKER:
            verdict = {"found": False, "path": path, "error": "not_mixar_fork",
                       "message": "This is stock Godot, not the Mixar Godot fork. "
                                  "Install Mixar Godot or point Locate Godot at it."}
        else:
            verdict = {"found": True, "path": path, "error": None, "message": "",
                       "version": str(data.get("fork_version") or ""),
                       "godot": str(data.get("godot") or ""),
                       "capabilities": [str(c) for c in data.get("capabilities") or ()
                                        if isinstance(c, str)]}
    with _lock:
        _cache[key] = dict(verdict)
    return verdict


def locate(config_path: str = "", environ=None, runner=None, **kwargs) -> dict:
    """First valid candidate's verdict; otherwise the most telling refusal."""
    global _status
    refusal = None
    for source, path in candidates(config_path, environ, **kwargs):
        verdict = validate(path, runner=runner)
        verdict["source"] = source
        if verdict.get("found"):
            refusal = verdict
            break
        if refusal is None or (refusal.get("error") == "not_found" and verdict.get("error") != "not_found"):
            refusal = verdict
    if refusal is None:
        refusal = {"found": False, "path": "", "error": "not_found", "source": "",
                   "message": "Mixar Godot is not installed. Install it or use Locate Godot."}
    with _lock:
        _status = dict(refusal)
    return refusal


def locate_async(config_path: str = "", on_done=None) -> None:
    """Start one background locate unless one is running. ``on_done(verdict)``
    runs on the worker thread (it must not touch ``bpy``)."""
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return

        def work():
            verdict = locate(config_path)
            if on_done is not None:
                on_done(verdict)

        _worker = threading.Thread(target=work, name="mixar-godot-locate", daemon=True)
        _worker.start()


def cached_status() -> dict | None:
    """The last verdict without blocking, or None before the first locate."""
    with _lock:
        return dict(_status) if _status is not None else None


def is_locating() -> bool:
    with _lock:
        return _worker is not None and _worker.is_alive()


def forget() -> None:
    """Drop every verdict (after the user picks a new path)."""
    global _status
    with _lock:
        _cache.clear()
        _status = None
