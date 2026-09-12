# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SQLite operation journal (harness v3) against a real file in tmp_path."""

import os
import sqlite3
import sys
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)
for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.common.agent_execution import journal as jmod  # noqa: E402
from mixar.modules.common.agent_execution.journal import Journal  # noqa: E402


@pytest.fixture
def journal(tmp_path):
    j = Journal(str(tmp_path / "sub" / "agent_journal.sqlite"))
    yield j
    j.close()


def _prepare(j, op="op-1", h="h1"):
    return j.op_prepare(op, run_id="r1", task_id="t1", generation=0, fence=2, payload_hash=h,
                        document_id="d", document_epoch=1, artifact_id="a")


def test_schema_wal_and_version(journal):
    conn = sqlite3.connect(journal.path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA user_version").fetchone()[0] == jmod.SCHEMA_VERSION
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"ops", "bindings", "runs"} <= names
    conn.close()


def test_prepared_then_applied_returns_receipt(journal):
    rec = _prepare(journal)
    assert rec["state"] == jmod.PREPARED and rec["receipt"] == {}
    journal.op_set_state("op-1", jmod.RUNNING)
    done = journal.op_set_state("op-1", jmod.APPLIED, {"created_object_names": ["Cube"]})
    assert done["state"] == jmod.APPLIED and done["receipt"]["created_object_names"] == ["Cube"]
    # Re-preparing the same id/hash is a no-op that keeps the applied state.
    again = _prepare(journal)
    assert again["state"] == jmod.APPLIED and again["payload_hash"] == "h1"


def test_status_unknown_by_default_and_ignores_non_strings(journal):
    _prepare(journal)
    out = journal.ops_status(["op-1", "op-9", 42])
    assert out["op-1"]["state"] == jmod.PREPARED
    assert out["op-9"] == {"state": jmod.UNKNOWN, "receipt": {}}
    assert 42 not in out


def test_bindings_and_runs(journal):
    journal.record_binding("r1", "t1", 0, "p-sbx-0", 5)
    journal.record_binding("r1", "t1", 0, "p-sbx-1", 6)
    b = journal.get_binding("r1", "t1", 0)
    assert b["worker_connection_id"] == "p-sbx-1" and b["fence"] == 6
    assert journal.get_binding("r1", "t2", 0) is None
    # No accepted run yet is -1, not 0: epoch 0 is a real epoch.
    assert journal.run_epoch("s1") == -1
    journal.record_run("s1", "r1", 3)
    journal.record_run("s1", "r2", 4)
    assert journal.run_epoch("s1") == 4
    assert not journal.run_revoked("r2")
    journal.revoke_run("r2")
    assert journal.run_revoked("r2")


def test_record_run_clears_a_prior_revocation(journal):
    """Re-activating the same run id at a newer epoch must not inherit the
    old revoke, or every later commit for it is refused while the activate
    itself was acknowledged."""
    journal.record_run("s1", "r1", 4)
    journal.revoke_run("r1")
    assert journal.run_revoked("r1")
    journal.record_run("s1", "r1", 5)
    assert not journal.run_revoked("r1")
    assert journal.run_epoch("s1") == 5


def test_supersede_run_only_touches_open_ops(journal):
    _prepare(journal, "a", "h")
    _prepare(journal, "b", "h")
    journal.op_set_state("b", jmod.APPLIED, {})
    assert journal.supersede_run("r1") == 1
    assert journal.op_get("a")["state"] == jmod.SUPERSEDED
    assert journal.op_get("b")["state"] == jmod.APPLIED


def test_durability_across_reopen(tmp_path):
    path = str(tmp_path / "j.sqlite")
    j = Journal(path)
    _prepare(j)
    j.op_set_state("op-1", jmod.APPLIED, {"x": 1})
    j.close()
    j2 = Journal(path)
    assert j2.op_get("op-1")["receipt"] == {"x": 1}
    j2.close()


def test_singleton_set_and_get(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXAR_AGENT_CACHE_DIR", str(tmp_path))
    jmod.set_journal(None)
    j = jmod.get_journal()
    assert j.path.startswith(str(tmp_path))
    jmod.set_journal(None)


def test_reopen_abandons_a_crashed_running_op(tmp_path):
    """RUNNING that survives a process death must not stay deferred."""
    path = str(tmp_path / "j.sqlite")
    j = Journal(path)
    _prepare(j)
    j.op_set_state("op-1", jmod.RUNNING)
    assert j.op_get("op-1")["state"] == jmod.RUNNING
    j.close()
    j2 = Journal(path)
    assert j2.op_get("op-1")["state"] == jmod.UNKNOWN
    j2.close()


def test_get_latest_binding_picks_the_highest_fence(journal):
    journal.record_binding("r1", "t1", 0, "p-sbx-0", 3)
    journal.record_binding("r1", "t1", 1, "p-sbx-1", 9)
    journal.record_binding("r1", "t1", 2, "p-sbx-2", 4)
    rec = journal.get_latest_binding("r1", "t1")
    assert rec["fence"] == 9 and rec["generation"] == 1
    assert journal.get_latest_binding("r1", "missing") is None
