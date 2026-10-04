# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Correlate slow requests locally without recording script/output content."""

import json
import time
from types import SimpleNamespace

from mixar.modules.common.agent_execution import diagnostics, pump
from mixar.modules.common.agent_execution.request import ExecutionRequest
from mixar.modules.space_mixie_chat.core.socket_queue import SocketQueue
from mixar.modules.space_mixie_chat.core.socket_requests import SocketRequests


def test_durable_phases_measure_queue_and_execution_without_content(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXAR_SCENES_DOSSIER_DIR", str(tmp_path))
    req = ExecutionRequest("request", "secret script", "inspect_geometry", "agentlane:parent:task",
                           agent_ctx={"chat_session_id": "chat"}, queued_at=time.monotonic() - 2)
    diagnostics.record_phase(req, "received")
    result = pump.execute_request(req, SimpleNamespace(execute=lambda *a, **kw:
                                  SimpleNamespace(to_dict=lambda: {"success": True, "output": "private output"})))
    assert pump.respond(SimpleNamespace(is_connected=True, queue_response=lambda *a: True), req, result)
    records = [json.loads(line) for line in (tmp_path / "chat/events.jsonl").read_text().splitlines()]
    assert [item["event"] for item in records] == ["execution.received", "execution.started",
                                                  "execution.script_finished", "execution.response_queued"]
    assert all(item["request_id"] == "request" and item["ts"] > 0 for item in records)
    assert records[2]["queue_wait_ms"] >= 1900 and records[2]["exec_ms"] >= 0
    assert "private output" not in json.dumps(records) and "secret script" not in json.dumps(records)
    assert "timing" not in result and "ts" not in result


def test_full_writer_does_not_claim_response_accepted(monkeypatch):
    monkeypatch.setenv("MIXAR_SCENES_DOSSIER_DIR", "0")
    client = SocketRequests()
    client._ws = None
    client._outbound = SocketQueue(maxsize=1)
    client.is_connected = True
    req = ExecutionRequest("id", "")
    assert pump.respond(client, req, {"success": True})
    assert not pump.respond(client, ExecutionRequest("second", ""), {"success": True})
    assert client._outbound.qsize() == 1


def test_disconnected_and_throwing_writer_leave_diagnostic_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXAR_SCENES_DOSSIER_DIR", str(tmp_path))
    req = ExecutionRequest("id", "", session_id="chat")
    assert not pump.respond(None, req, {"success": True})
    def fail(*_args):
        raise RuntimeError("private exception")
    assert not pump.respond(SimpleNamespace(is_connected=True, queue_response=fail),
                            ExecutionRequest("next", "", session_id="chat"), {"success": True})
    records = [json.loads(line) for line in (tmp_path / "chat/events.jsonl").read_text().splitlines()]
    assert [r["event"] for r in records] == ["execution.response_unavailable", "execution.response_rejected"]
    assert "private exception" not in json.dumps(records)
