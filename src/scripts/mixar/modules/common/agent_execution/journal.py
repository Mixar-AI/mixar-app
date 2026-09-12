# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Durable client operation journal (SQLite, WAL, synchronous=FULL).

Lives in the per-user cache — never beside a possibly unsaved or read-only
project file. Records what this client has PREPARED / APPLIED for each
logical operation so a backend retry or a duplicated RPC returns the recorded
receipt instead of re-executing, and so a lost reply can be answered by
``agent.execution.status``.

MAIN THREAD ONLY: every caller runs on Blender's main thread (the execution
handlers schedule there); sqlite connections are not shared across threads.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Iterable, Optional

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

SCHEMA_VERSION = 1

# Operation states (see the v3 plan): a script failure is NOT
# failed_no_effect unless a typed handler proved it.
PREPARED = "prepared"
RUNNING = "running"
STAGED = "staged"
APPLIED = "applied"
FAILED_NO_EFFECT = "failed_no_effect"
UNKNOWN = "unknown"
SUPERSEDED = "superseded"

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS ops (
        operation_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        generation INTEGER NOT NULL,
        fence INTEGER NOT NULL DEFAULT 0,
        payload_hash TEXT NOT NULL,
        state TEXT NOT NULL,
        document_id TEXT,
        document_epoch INTEGER,
        artifact_id TEXT,
        receipt_json TEXT,
        updated_at REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS bindings (
        run_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        generation INTEGER NOT NULL,
        worker_connection_id TEXT,
        fence INTEGER NOT NULL DEFAULT 0,
        updated_at REAL NOT NULL,
        PRIMARY KEY (run_id, task_id, generation)
    )""",
    # Keyed by run_id (not session) so a superseded run keeps its own revoked
    # row after the session moves on to a newer run.
    """CREATE TABLE IF NOT EXISTS runs (
        run_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        turn_epoch INTEGER NOT NULL,
        revoked INTEGER NOT NULL DEFAULT 0,
        updated_at REAL NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS runs_session ON runs(session_id, turn_epoch)",
)


class Journal:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(path, isolation_level=None)  # autocommit; explicit BEGIN below
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._migrate()
        self._abandon_crashed_ops()

    # --- schema ---------------------------------------------------------
    def _migrate(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            with self._tx():
                for stmt in _SCHEMA:
                    self._conn.execute(stmt)
                self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _abandon_crashed_ops(self) -> None:
        """A leftover ``RUNNING`` row cannot still be in flight: this journal
        is main-thread-only and a new connection means a new process (or a
        test reopen). Replay as ``UNKNOWN`` so a retry never sits on
        ``deferred`` forever after a crash between RUNNING and APPLIED.
        """
        with self._tx():
            self._conn.execute(
                "UPDATE ops SET state=?, updated_at=? WHERE state=?",
                (UNKNOWN, time.time(), RUNNING),
            )

    def _tx(self):
        """BEGIN IMMEDIATE ... COMMIT/ROLLBACK context manager."""
        conn = self._conn

        class _Tx:
            def __enter__(self_inner):
                conn.execute("BEGIN IMMEDIATE")
                return conn

            def __exit__(self_inner, exc_type, exc, tb):
                if exc_type is None:
                    conn.execute("COMMIT")
                else:
                    conn.execute("ROLLBACK")
                return False

        return _Tx()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # --- runs -------------------------------------------------------------
    def run_epoch(self, session_id: str) -> int:
        """Highest turn epoch this client ever accepted for the session.

        ``-1`` when the session has no accepted run yet, matching the
        "no prior run" sentinel :func:`bindings.activate` starts from: epoch
        0 is a real epoch, so 0 must not double as "never activated".
        """
        row = self._conn.execute(
            "SELECT MAX(turn_epoch) AS e FROM runs WHERE session_id=?", (session_id,)
        ).fetchone()
        return int(row["e"]) if row and row["e"] is not None else -1

    def record_run(self, session_id: str, run_id: str, turn_epoch: int) -> None:
        with self._tx():
            self._conn.execute(
                "INSERT INTO runs(run_id, session_id, turn_epoch, revoked, updated_at) "
                "VALUES(?,?,?,0,?) ON CONFLICT(run_id) DO UPDATE SET "
                "session_id=excluded.session_id, turn_epoch=excluded.turn_epoch, "
                "revoked=0, updated_at=excluded.updated_at",
                (run_id, session_id, int(turn_epoch), time.time()),
            )

    def revoke_run(self, run_id: str) -> None:
        """Mark a run revoked; an unknown run gets a revoked row so a later
        commit for it is still refused after a restart."""
        with self._tx():
            self._conn.execute(
                "INSERT INTO runs(run_id, session_id, turn_epoch, revoked, updated_at) "
                "VALUES(?, '', 0, 1, ?) ON CONFLICT(run_id) DO UPDATE SET "
                "revoked=1, updated_at=excluded.updated_at",
                (run_id, time.time()),
            )

    def run_revoked(self, run_id: str) -> bool:
        row = self._conn.execute("SELECT revoked FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return bool(row and row["revoked"])

    # --- bindings -----------------------------------------------------------
    def record_binding(self, run_id: str, task_id: str, generation: int,
                       worker_connection_id: str, fence: int) -> None:
        with self._tx():
            self._conn.execute(
                "INSERT INTO bindings(run_id, task_id, generation, worker_connection_id, fence, updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(run_id, task_id, generation) DO UPDATE SET "
                "worker_connection_id=excluded.worker_connection_id, fence=excluded.fence, "
                "updated_at=excluded.updated_at",
                (run_id, task_id, int(generation), worker_connection_id, int(fence), time.time()),
            )

    def get_binding(self, run_id: str, task_id: str, generation: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM bindings WHERE run_id=? AND task_id=? AND generation=?",
            (run_id, task_id, int(generation)),
        ).fetchone()
        return dict(row) if row else None

    def get_latest_binding(self, run_id: str, task_id: str) -> Optional[dict]:
        """Highest-fence binding for the task, any generation (restart path)."""
        row = self._conn.execute(
            "SELECT * FROM bindings WHERE run_id=? AND task_id=? "
            "ORDER BY fence DESC, generation DESC LIMIT 1",
            (run_id, task_id),
        ).fetchone()
        return dict(row) if row else None

    # --- operations -----------------------------------------------------------
    def op_get(self, operation_id: str) -> Optional[dict]:
        row = self._conn.execute("SELECT * FROM ops WHERE operation_id=?", (operation_id,)).fetchone()
        if not row:
            return None
        rec = dict(row)
        rec["receipt"] = json.loads(rec.pop("receipt_json") or "{}")
        return rec

    def op_prepare(self, operation_id: str, *, run_id: str, task_id: str, generation: int,
                   fence: int, payload_hash: str, document_id: Optional[str],
                   document_epoch: Optional[int], artifact_id: Optional[str]) -> dict:
        """Durably record intent BEFORE the effect. Idempotent for the same hash."""
        with self._tx():
            self._conn.execute(
                "INSERT INTO ops(operation_id, run_id, task_id, generation, fence, payload_hash, "
                "state, document_id, document_epoch, artifact_id, receipt_json, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,'{}',?) ON CONFLICT(operation_id) DO NOTHING",
                (operation_id, run_id, task_id, int(generation), int(fence), payload_hash,
                 PREPARED, document_id, document_epoch, artifact_id, time.time()),
            )
        return self.op_get(operation_id)

    def op_set_state(self, operation_id: str, state: str, receipt: Optional[dict] = None) -> dict:
        with self._tx():
            if receipt is None:
                self._conn.execute(
                    "UPDATE ops SET state=?, updated_at=? WHERE operation_id=?",
                    (state, time.time(), operation_id),
                )
            else:
                self._conn.execute(
                    "UPDATE ops SET state=?, receipt_json=?, updated_at=? WHERE operation_id=?",
                    (state, json.dumps(receipt, default=str), time.time(), operation_id),
                )
        return self.op_get(operation_id)

    def ops_status(self, operation_ids: Iterable[str]) -> dict:
        out: dict = {}
        for op_id in operation_ids:
            if not isinstance(op_id, str):
                continue
            rec = self.op_get(op_id)
            out[op_id] = (
                {"state": rec["state"], "receipt": rec["receipt"]}
                if rec else {"state": UNKNOWN, "receipt": {}}
            )
        return out

    def supersede_run(self, run_id: str) -> int:
        with self._tx():
            cur = self._conn.execute(
                "UPDATE ops SET state=?, updated_at=? WHERE run_id=? AND state IN (?,?)",
                (SUPERSEDED, time.time(), run_id, PREPARED, RUNNING),
            )
            return cur.rowcount


_journal: Optional[Journal] = None


def get_journal() -> Journal:
    global _journal
    if _journal is None:
        from .paths import journal_path

        _journal = Journal(journal_path())
    return _journal


def set_journal(journal: Optional[Journal]) -> None:
    global _journal
    if _journal is not None and _journal is not journal:
        _journal.close()
    _journal = journal
