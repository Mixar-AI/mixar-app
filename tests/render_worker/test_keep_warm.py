# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The preview worker stays warm while the agent works (``keep_warm``).

A render on a fresh worker pays its engines' first use (PR #1955: heavy
inspection 42.8 s cold against 5.7 s warm), and the 120 s idle stop killed
the worker between most of an agent's verification renders. Real child
processes (``fake_worker.py``) through the supervisor fixture.
"""

import ast
import time
from pathlib import Path

from mixar.modules.common.render_worker import keep_warm

from test_supervisor import _dead, _job, _wait, sup  # noqa: F401 (fixture re-export)

ROOT = Path(__file__).resolve().parents[2] / "src/scripts/mixar/modules/space_mixie_chat/core"

def test_idle_expiry_without_agent_activity_is_the_plain_ttl():
    keep_warm.reset_for_tests()
    assert not keep_warm.idle_expired(0.0, 100.0, 120.0)
    assert keep_warm.idle_expired(0.0, 121.0, 120.0)


def test_agent_activity_keeps_an_idle_worker_up_to_the_active_ttl():
    keep_warm.reset_for_tests()
    keep_warm.note_agent_activity(now=500.0)
    assert not keep_warm.idle_expired(0.0, 560.0, 120.0)
    assert keep_warm.idle_expired(0.0, keep_warm.ACTIVE_IDLE_TTL_S + 1.0, 120.0)
    # The agent stopped more than one TTL ago: back to the plain idle stop.
    assert keep_warm.idle_expired(0.0, 640.0, 120.0)
    keep_warm.reset_for_tests()


def test_an_active_agent_keeps_the_idle_worker_alive(sup, tmp_path, monkeypatch):
    first = sup.submit("preview", _job(tmp_path, "a"), timeout_s=10)
    pid = _wait(sup, first)["pid"]
    monkeypatch.setattr(sup, "IDLE_TTL_S", 0.0)
    keep_warm.note_agent_activity(now=time.monotonic() + 3600)  # activity "now" for the test
    monkeypatch.setattr(keep_warm, "ACTIVE_IDLE_TTL_S", 3600.0)
    sup.maintain()
    assert sup.workers()["preview"]["pid"] == pid
    keep_warm.reset_for_tests()
    sup.maintain()
    assert "preview" not in sup.workers()
    assert _dead(pid)


def test_the_executor_notes_activity_after_the_reply_went_out():
    tree = ast.parse((ROOT / "main_thread_executor.py").read_text())
    func = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "_execute_dequeued_request")
    lines = {}
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            lines.setdefault(name, node.lineno)
    assert lines["execute_request"] < lines["respond"] < lines["note_agent_activity"]
