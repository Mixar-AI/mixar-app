# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crash-reporting state on disk: ``<user config>/mixar/crash_reports/``.

- ``sent.json``: report id -> when it was handled (sent, or refused for good by
  the server). The ledger is what keeps a crash file from being sent twice;
  Mixar never deletes one, except its own render-worker copies in
  ``mixar_render_worker_crashes`` once handled.
- ``pending.json``: uncaught Python exceptions (already scrubbed) waiting for a
  signed-in, consented session.
- ``session-<pid>.json``: the running session's breadcrumb (versions, GPU,
  Cycles device, open tabs, agent session/run ids), refreshed by the heartbeat
  and removed on a clean quit. A crash file written while a session's
  breadcrumb was live inherits its context on the next launch.
- ``pyfault-<pid>.txt``: the session's faulthandler dump (``pyfault.py``),
  removed with its breadcrumb (a clean quit, pruning), once the crash report
  it belongs to is handled, or when no breadcrumb is left to pair it with.

Every function here does file I/O and runs on the reporter's worker thread;
writes are atomic (temp file + replace).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone

from ..constants import (
    MAX_PENDING_EXCEPTIONS,
    PENDING_FILE,
    PYFAULT_PREFIX,
    PYFAULT_SUFFIX,
    SENT_LEDGER,
    SENT_LEDGER_DAYS,
    SESSION_MAX_AGE_DAYS,
    SESSION_PREFIX,
)


def _read_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(temp, path)
    except Exception:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


class Store:
    def __init__(self, directory: str):
        self.directory = directory

    def _path(self, name: str) -> str:
        return os.path.join(self.directory, name)

    # Sent ledger ---------------------------------------------------------
    def sent_ids(self) -> dict:
        data = _read_json(self._path(SENT_LEDGER), {})
        return data if isinstance(data, dict) else {}

    def is_sent(self, report_id: str) -> bool:
        return report_id in self.sent_ids()

    def mark_sent(self, report_id: str, outcome: str = "sent") -> None:
        ledger = self.sent_ids()
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=SENT_LEDGER_DAYS)).isoformat()
        ledger = {key: value for key, value in ledger.items()
                  if isinstance(value, dict) and value.get("at", "") >= cutoff}
        ledger[report_id] = {"at": now.isoformat(), "outcome": outcome}
        _write_json(self._path(SENT_LEDGER), ledger)

    # Pending exceptions ----------------------------------------------------
    def pending(self) -> list[dict]:
        data = _read_json(self._path(PENDING_FILE), [])
        return data if isinstance(data, list) else []

    def add_pending(self, reports: list[dict]) -> None:
        if not reports:
            return
        known = {item.get("report_id") for item in self.pending()}
        merged = self.pending() + [r for r in reports if r.get("report_id") not in known]
        _write_json(self._path(PENDING_FILE), merged[-MAX_PENDING_EXCEPTIONS:])

    def remove_pending(self, report_ids: set[str]) -> None:
        if not report_ids:
            return
        remaining = [item for item in self.pending() if item.get("report_id") not in report_ids]
        _write_json(self._path(PENDING_FILE), remaining)

    # Session breadcrumbs ---------------------------------------------------
    def session_path(self, pid: int) -> str:
        return self._path(f"{SESSION_PREFIX}{pid}.json")

    def write_session(self, pid: int, data: dict) -> None:
        _write_json(self.session_path(pid), data)

    def remove_session(self, pid: int) -> None:
        for path in (self.session_path(pid), self.pyfault_path(pid)):
            try:
                os.unlink(path)
            except OSError:
                pass

    # faulthandler dumps ----------------------------------------------------
    def pyfault_path(self, pid: int) -> str:
        return self._path(f"{PYFAULT_PREFIX}{pid}{PYFAULT_SUFFIX}")

    def trim_pyfault(self, pid: int, max_bytes: int) -> None:
        """Empty the running session's dump once it outgrows ``max_bytes``
        (faulthandler appends: its next dump starts the file again)."""
        path = self.pyfault_path(pid)
        try:
            if os.path.getsize(path) > max_bytes:
                os.truncate(path, 0)
        except OSError:
            pass

    def prune_orphan_pyfaults(self, own_pid: int, settled_s: float) -> None:
        """Dumps of other sessions with no breadcrumb left (it ended before its
        first heartbeat, or was pruned) and untouched for ``settled_s``."""
        cutoff = time.time() - settled_s
        try:
            names = os.listdir(self.directory)
        except OSError:
            return
        for name in names:
            if not (name.startswith(PYFAULT_PREFIX) and name.endswith(PYFAULT_SUFFIX)):
                continue
            pid_text = name[len(PYFAULT_PREFIX):-len(PYFAULT_SUFFIX)]
            if not pid_text.isdigit() or int(pid_text) == own_pid:
                continue
            if os.path.exists(self.session_path(int(pid_text))):
                continue
            path = self._path(name)
            try:
                if os.stat(path).st_mtime < cutoff:
                    os.unlink(path)
            except OSError:
                continue

    def prune_ended_sessions(self, own_pid: int, settled_s: float) -> None:
        """Drop other sessions' breadcrumbs once every crash file they could
        match has been harvested: those that ended more than ``settled_s`` ago."""
        cutoff = time.time() - settled_s
        for data in self.sessions(own_pid):
            pid = data.get("pid")
            if isinstance(pid, int) and float(data.get("updated_at") or 0) < cutoff:
                self.remove_session(pid)

    def sessions(self, own_pid: int) -> list[dict]:
        """Breadcrumbs of other (ended) sessions; stale ones are pruned."""
        out = []
        try:
            names = os.listdir(self.directory)
        except OSError:
            return out
        now = time.time()
        for name in names:
            if not (name.startswith(SESSION_PREFIX) and name.endswith(".json")):
                continue
            pid_text = name[len(SESSION_PREFIX):-len(".json")]
            if not pid_text.isdigit() or int(pid_text) == own_pid:
                continue
            path = self._path(name)
            data = _read_json(path, None)
            updated = data.get("updated_at", 0) if isinstance(data, dict) else 0
            if not isinstance(data, dict) or now - float(updated or 0) > SESSION_MAX_AGE_DAYS * 86400:
                self.remove_session(int(pid_text))
                continue
            out.append(data)
        return out
