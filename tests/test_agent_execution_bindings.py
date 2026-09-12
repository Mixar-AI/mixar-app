# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Run activation / turn epochs / task bindings / revocation (harness v3)."""

import os
import sys
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)
for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.common.agent_execution import bindings, document  # noqa: E402
from mixar.modules.common.agent_execution.journal import Journal  # noqa: E402

IDENTITY = {"document_id": "doc-1", "document_epoch": 3, "scene_id": "scene-1", "scene_name": "Scene"}


@pytest.fixture
def journal(tmp_path, monkeypatch):
    j = Journal(str(tmp_path / "j.sqlite"))
    bindings.reset()
    # Never touch the (stubbed, shared) WindowManager flag from these tests —
    # a literal True left on the MagicMock would leak into other suites.
    monkeypatch.setattr(document, "set_run_active", lambda f: None)
    yield j
    j.close()
    bindings.reset()


def _activate(journal, run_id, epoch, session="s1", **extra):
    params = {"run_id": run_id, "session_id": session, "turn_epoch": epoch, "protocol_version": "v3"}
    params.update(extra)
    return bindings.activate(params, journal=journal, identity_fn=lambda: IDENTITY)


def test_activate_acks_identity_and_capabilities(journal, monkeypatch):
    flags = []
    monkeypatch.setattr(document, "set_run_active", lambda f: flags.append(f))
    out = _activate(journal, "r1", 1)
    assert out["success"] and out["ack"] is True
    assert out["document_id"] == "doc-1" and out["document_epoch"] == 3
    assert out["scene_id"] == "scene-1" and out["scene_name"] == "Scene"
    assert "native_artifacts_v1" in out["capabilities"] and "exec_envelope_v3" in out["capabilities"]
    assert flags == [True]
    assert journal.run_epoch("s1") == 1


def test_epoch_monotonic_and_stale_refused(journal):
    assert _activate(journal, "r1", 2)["success"]
    stale = _activate(journal, "r0", 2)
    assert stale["success"] is False and stale["error_type"] == "stale_epoch"
    older = _activate(journal, "r0", 1)
    assert older["error_type"] == "stale_epoch"
    # Same run re-activated (transport retry) is acknowledged, not refused.
    again = _activate(journal, "r1", 2)
    assert again["success"] and again["ack"]


def test_journal_epoch_survives_memory_reset(journal):
    _activate(journal, "r1", 5)
    bindings.reset()  # simulate an add-on reload
    assert _activate(journal, "r2", 5)["error_type"] == "stale_epoch"
    assert _activate(journal, "r2", 6)["success"]


def test_newer_run_revokes_prior_and_commit_checks(journal):
    _activate(journal, "r1", 1)
    bindings.bind_task({"run_id": "r1", "turn_epoch": 1, "task_id": "t1", "generation": 0,
                        "attempt": 1, "fence_token": 0}, journal=journal)
    assert bindings.check_commit_allowed("r1", 1, "t1", 0, journal) is None
    _activate(journal, "r2", 2)
    assert bindings.check_commit_allowed("r1", 1, "t1", 0, journal)[0] == "stale_epoch"
    assert bindings.check_commit_allowed("r2", 1, "t1", 0, journal)[0] == "stale_epoch"
    assert bindings.check_commit_allowed("nope", 2, "t1", 0, journal)[0] == "unknown_run"
    assert journal.run_revoked("r1")


def test_revoke_run_and_task(journal, monkeypatch):
    flags = []
    monkeypatch.setattr(document, "set_run_active", lambda f: flags.append(f))
    _activate(journal, "r1", 1)
    bindings.bind_task({"run_id": "r1", "turn_epoch": 1, "task_id": "t1", "generation": 0,
                        "attempt": 1, "fence_token": 0}, journal=journal)
    bindings.bind_task({"run_id": "r1", "turn_epoch": 1, "task_id": "t9", "generation": 0,
                        "attempt": 1, "fence_token": 0}, journal=journal)
    assert bindings.revoke({"run_id": "r1", "turn_epoch": 1, "task_id": "t9"}, journal=journal)["success"]
    assert bindings.check_commit_allowed("r1", 1, "t9", 0, journal)[0] == "stale_fence"
    assert bindings.check_commit_allowed("r1", 1, "t1", 0, journal) is None
    assert bindings.revoke({"run_id": "r1", "turn_epoch": 1}, journal=journal)["known"]
    assert bindings.check_commit_allowed("r1", 1, "t1", 0, journal)[0] == "stale_epoch"
    assert flags[-1] is False
    # Unknown run: still recorded as revoked for a later restart.
    assert bindings.revoke({"run_id": "ghost"}, journal=journal)["known"] is False
    assert journal.run_revoked("ghost")


def test_bind_task_fences(journal):
    _activate(journal, "r1", 1)
    ok = bindings.bind_task({"run_id": "r1", "turn_epoch": 1, "task_id": "t1", "generation": 0,
                             "attempt": 1, "fence_token": 7, "worker_connection_id": "p-sbx-0"},
                            journal=journal)
    assert ok["success"]
    assert journal.get_binding("r1", "t1", 0)["fence"] == 7
    older = bindings.bind_task({"run_id": "r1", "turn_epoch": 1, "task_id": "t1", "generation": 0,
                                "attempt": 0, "fence_token": 3}, journal=journal)
    assert older["error_type"] == "stale_fence"
    assert bindings.check_commit_allowed("r1", 1, "t1", 3, journal)[0] == "stale_fence"
    assert bindings.check_commit_allowed("r1", 1, "t1", 7, journal) is None
    assert bindings.bind_task({"run_id": "r1", "turn_epoch": 9, "task_id": "t1"}, journal=journal)["error_type"] == "stale_epoch"
    assert bindings.bind_task({"run_id": "zz", "turn_epoch": 1, "task_id": "t1"}, journal=journal)["error_type"] == "unknown_run"


def test_invalid_activate_params(journal):
    assert bindings.activate({"run_id": "r"}, journal=journal)["error_type"] == "invalid_params"
    bad = _activate(journal, "r1", 1, protocol_version="v2")
    assert bad["error_type"] == "unsupported_protocol"


def test_first_turn_epoch_zero_activates(journal):
    """Epoch 0 is a real epoch: the first accepted run must not be refused
    merely because no run was accepted before it."""
    first = _activate(journal, "r1", 0)
    assert first["success"] and first["turn_epoch"] == 0
    assert _activate(journal, "r1", 0)["success"]          # transport retry
    assert _activate(journal, "r2", 0)["error_type"] == "stale_epoch"
    assert _activate(journal, "r2", 1)["success"]


def test_reactivated_run_id_clears_the_prior_revocation(journal):
    """A run re-accepted at a newer epoch stays committable after its earlier
    revocation; activate acks an ack that every commit would then refuse."""
    _activate(journal, "r1", 1)
    assert bindings.revoke({"run_id": "r1", "turn_epoch": 1}, journal=journal)["known"]
    assert bindings.check_commit_allowed("r1", 1, "t1", 0, journal)[0] == "stale_epoch"
    again = _activate(journal, "r1", 2)
    assert again["success"] and again["ack"] is True
    bindings.bind_task({"run_id": "r1", "turn_epoch": 2, "task_id": "t1", "generation": 0,
                        "attempt": 1, "fence_token": 0}, journal=journal)
    assert bindings.check_commit_allowed("r1", 2, "t1", 0, journal) is None


def test_revoke_unknown_run_supersedes_its_open_ops(journal):
    """After a restart the run is not in memory but its journal row is: a
    revoke must refuse later commits AND close the ops it left open."""
    journal.op_prepare("op-x", run_id="ghost", task_id="t1", generation=0, fence=0,
                       payload_hash="h", document_id="d", document_epoch=0, artifact_id=None)
    assert journal.op_get("op-x")["state"] == "prepared"
    assert bindings.revoke({"run_id": "ghost"}, journal=journal)["known"] is False
    assert journal.run_revoked("ghost")
    assert journal.op_get("op-x")["state"] == "superseded"


# --- FOREGROUND execution class (lock + capture stand up per task) ------------

def _bind(journal, task_id, execution_class=None, fence=1, run_id="r1", epoch=1):
    params = {"run_id": run_id, "turn_epoch": epoch, "task_id": task_id, "generation": 0,
              "attempt": 1, "fence_token": fence, "worker_connection_id": "p-sbx-0"}
    if execution_class is not None:
        params["execution_class"] = execution_class
    return bindings.bind_task(params, journal=journal)


def test_foreground_bind_counts_and_revoke_task_clears(journal):
    document.clear_foreground_tasks()
    _activate(journal, "r1", 1)
    assert document.foreground_tasks_active() == 0
    out = _bind(journal, "t1", "foreground")
    assert out["success"] and out["execution_class"] == "foreground"
    assert out["foreground_tasks"] == 1 and document.foreground_tasks_active() == 1
    # A rebind (new attempt) of the same task keeps the count at one.
    assert _bind(journal, "t1", "foreground", fence=2)["foreground_tasks"] == 1
    # A second foreground task counts separately.
    assert _bind(journal, "t2", "foreground")["foreground_tasks"] == 2
    done = bindings.revoke({"run_id": "r1", "turn_epoch": 1, "task_id": "t1"}, journal=journal)
    assert done["success"] and done["foreground_tasks"] == 1
    assert bindings.revoke({"run_id": "r1", "turn_epoch": 1, "task_id": "t2"}, journal=journal)["foreground_tasks"] == 0
    assert document.foreground_tasks_active() == 0
    # Revoking a task twice (or a never-foreground task) is harmless.
    assert bindings.revoke({"run_id": "r1", "turn_epoch": 1, "task_id": "t2"}, journal=journal)["foreground_tasks"] == 0


def test_worker_class_does_not_count(journal):
    document.clear_foreground_tasks()
    _activate(journal, "r1", 1)
    assert _bind(journal, "t1")["foreground_tasks"] == 0                 # default = worker
    assert _bind(journal, "t2", "worker")["execution_class"] == "worker"
    assert document.foreground_tasks_active() == 0
    bad = _bind(journal, "t3", "gpu")
    assert bad["success"] is False and bad["error_type"] == "invalid_params"


def test_new_run_and_whole_run_revoke_reset_counter(journal):
    document.clear_foreground_tasks()
    _activate(journal, "r1", 1)
    _bind(journal, "t1", "foreground")
    assert document.foreground_tasks_active() == 1
    # A newer run supersedes r1: its foreground flag must not survive.
    _activate(journal, "r2", 2)
    assert document.foreground_tasks_active() == 0
    assert _bind(journal, "t9", "foreground", run_id="r2", epoch=2)["success"]
    assert document.foreground_tasks_active() == 1
    whole = bindings.revoke({"run_id": "r2", "turn_epoch": 2}, journal=journal)
    assert whole["known"] and whole["foreground_tasks"] == 0
    # Unknown run revoke (after a restart) reports the live counter too.
    assert bindings.revoke({"run_id": "ghost"}, journal=journal)["foreground_tasks"] == 0


def test_unbound_task_cannot_commit(journal):
    _activate(journal, "r1", 1)
    refused = bindings.check_commit_allowed("r1", 1, "t1", 0, journal)
    assert refused is not None and refused[0] == "stale_fence"
    bindings.bind_task({"run_id": "r1", "turn_epoch": 1, "task_id": "t1", "generation": 0,
                        "attempt": 1, "fence_token": 4}, journal=journal)
    assert bindings.check_commit_allowed("r1", 1, "t1", 4, journal) is None


def test_restart_consults_the_journal_binding(journal):
    _activate(journal, "r1", 1)
    bindings.bind_task({"run_id": "r1", "turn_epoch": 1, "task_id": "t1", "generation": 0,
                        "attempt": 1, "fence_token": 7}, journal=journal)
    binding = bindings.for_run("r1")
    binding.tasks.clear()  # memory lost; journal still has the row
    assert bindings.check_commit_allowed("r1", 1, "t1", 7, journal) is None
    assert bindings.check_commit_allowed("r1", 1, "t1", 3, journal)[0] == "stale_fence"


def test_duplicate_activate_of_a_revoked_run_is_refused(journal):
    _activate(journal, "r1", 1)
    assert bindings.revoke({"run_id": "r1", "turn_epoch": 1}, journal=journal)["known"]
    again = _activate(journal, "r1", 1)
    assert again["success"] is False and again["error_type"] == "stale_epoch"
