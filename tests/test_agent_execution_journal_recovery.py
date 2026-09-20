# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Recovery distinguishes an abandoned publisher from another live instance."""

import sqlite3
import subprocess
import sys
from pathlib import Path

from mixar.modules.common.agent_execution.journal import APPLIED, RUNNING, UNKNOWN, Journal


def _running(journal, operation_id):
    journal.op_prepare(
        operation_id, run_id="run", task_id=operation_id, generation=0, fence=1,
        payload_hash="hash", document_id="doc", document_epoch=1, artifact_id="artifact",
    )
    journal.op_set_state(operation_id, RUNNING)


def test_open_preserves_live_publishers_and_recovers_only_closed_owners(tmp_path):
    path = str(tmp_path / "journal.sqlite")
    first = Journal(path)
    second = third = None
    try:
        _running(first, "first")
        second = Journal(path)
        assert second.op_get("first")["state"] == RUNNING
        _running(second, "second")
        first.close()

        third = Journal(path)
        assert third.op_get("first")["state"] == UNKNOWN
        assert third.op_get("second")["state"] == RUNNING
        second.op_set_state("second", APPLIED, {"created_object_names": ["Cube"]})
        assert third.op_get("second")["receipt"] == {"created_object_names": ["Cube"]}
    finally:
        for journal in (first, second, third):
            if journal:
                journal.close()


def test_crashed_process_releases_its_owner_lock(tmp_path):
    path = str(tmp_path / "journal.sqlite")
    scripts = str(Path(__file__).resolve().parents[1] / "src" / "scripts")
    child = """
import logging, os, sys, types
sys.path.insert(0, sys.argv[1])
for name in ('mixar', 'mixar.modules', 'mixar.modules.common'):
    package = types.ModuleType(name)
    package.__path__ = [os.path.join(sys.argv[1], *name.split('.'))]
    sys.modules[name] = package
sys.modules['mixar.config.logging_config'] = types.SimpleNamespace(get_logger=logging.getLogger)
from mixar.modules.common.agent_execution.journal import Journal, RUNNING
j = Journal(sys.argv[2])
j.op_prepare('crashed', run_id='r', task_id='t', generation=0, fence=1,
             payload_hash='h', document_id='d', document_epoch=1, artifact_id='a')
j.op_set_state('crashed', RUNNING)
os._exit(17)  # no close(), finalizers, or atexit cleanup
"""
    live = Journal(path)
    recovered = None
    try:
        _running(live, "live")
        result = subprocess.run([sys.executable, "-c", child, scripts, path],
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 17, result.stderr
        assert live.op_get("live")["state"] == RUNNING
        assert live.op_get("crashed")["state"] == RUNNING
        recovered = Journal(path)
        assert recovered.op_get("crashed")["state"] == UNKNOWN
        assert recovered.op_get("live")["state"] == RUNNING
    finally:
        live.close()
        if recovered:
            recovered.close()


def test_migration_preserves_unowned_v1_running_ops(tmp_path):
    from mixar.modules.common.agent_execution.journal import _SCHEMA

    path = str(tmp_path / "journal.sqlite")
    with sqlite3.connect(path) as conn:
        for statement in _SCHEMA:
            conn.execute(statement)
        conn.execute("PRAGMA user_version=1")
        conn.execute(
            "INSERT INTO ops VALUES ('legacy','r','t',0,1,'h','running','d',1,'a','{}',0)"
        )
    journal = Journal(path)
    try:
        # An older client may still be publishing. No owner means no proof
        # of death; the migration must preserve the row for reconciliation.
        assert journal.op_get("legacy")["state"] == RUNNING
        assert journal.op_get("legacy")["owner_id"] is None
        _running(journal, "current")
    finally:
        journal.close()
    reopened = Journal(path)
    try:
        assert reopened.op_get("legacy")["state"] == RUNNING
        assert reopened.op_get("current")["state"] == UNKNOWN
    finally:
        reopened.close()


def test_an_unreadable_owner_is_not_assumed_dead(tmp_path, monkeypatch):
    path = str(tmp_path / "journal.sqlite")
    first = Journal(path)
    second = None
    try:
        _running(first, "live")
        original = Path.open

        def deny_probe(self, mode="r", *args, **kwargs):
            if mode == "r+b":
                raise PermissionError("cannot inspect owner")
            return original(self, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "open", deny_probe)
        second = Journal(path)
        assert second.op_get("live")["state"] == RUNNING
    finally:
        first.close()
        if second:
            second.close()
