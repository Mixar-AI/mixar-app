# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crash-reporting state on disk: ``<user config>/mixar/crash_reports/``.

- ``sent.json``: report id -> when it was handled (sent, or refused for good by
  the server). A crash file is never deleted by Mixar; the ledger is what keeps
  it from being sent twice.
- ``pending.json``: uncaught Python exceptions (already scrubbed) waiting for a
  signed-in, consented session.
- ``session-<pid>.json``: the running session's breadcrumb (versions, GPU,
  Cycles device, open tabs, agent session/run ids), refreshed by the heartbeat
  and removed on a clean quit. A crash file written while a session's
  breadcrumb was live inherits its context on the next launch.

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
        try:
            os.unlink(self.session_path(pid))
        except OSError:
            pass

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
                try:
                    os.unlink(path)
                except OSError:
                    pass
                continue
            out.append(data)
        return out
