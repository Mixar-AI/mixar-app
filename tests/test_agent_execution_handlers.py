# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""agent.execution.* dispatch: main-thread scheduling + deferred replies."""

import json
import os
import sys
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)
for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.common.agent_execution import bindings, document, handlers  # noqa: E402
from mixar.modules.common.agent_execution import journal as jmod  # noqa: E402
from mixar.modules.space_mixie_chat.constants import JSONRPCMethod  # noqa: E402
from mixar.modules.space_mixie_chat.core.jsonrpc_client import JSONRPCWebSocketClient  # noqa: E402

IDENTITY = {"document_id": "doc", "document_epoch": 0, "scene_id": "sc", "scene_name": "Scene"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXAR_AGENT_CACHE_DIR", str(tmp_path))
    jmod.set_journal(jmod.Journal(str(tmp_path / "j.sqlite")))
    bindings.reset()
    monkeypatch.setattr(document, "set_run_active", lambda f: None)
    monkeypatch.setattr(document, "document_identity", lambda scene=None, bpy=None: dict(IDENTITY))
    yield
    jmod.set_journal(None)
    bindings.reset()


def _drive(method, params, request_id="req-1"):
    scheduled, replies = [], []
    handlers.handle_execution_request(
        method, params, request_id,
        schedule=lambda fn: scheduled.append(fn),
        respond=lambda rid, res: replies.append((rid, res)),
    )
    assert len(scheduled) == 1 and replies == []  # nothing ran on the WS thread
    scheduled[0]()
    return replies


def test_all_five_methods_reply_on_same_request_id(env):
    act = _drive(JSONRPCMethod.AGENT_EXECUTION_PREFIX + "activate",
                 {"run_id": "r1", "session_id": "s1", "turn_epoch": 1}, "a1")
    assert act == [("a1", act[0][1])] and act[0][1]["ack"] is True
    bind = _drive("agent.execution.bind_task",
                  {"run_id": "r1", "turn_epoch": 1, "task_id": "t1", "generation": 0,
                   "attempt": 1, "fence_token": 1, "worker_connection_id": "w"}, "b1")
    assert bind[0] == ("b1", {"success": True, "execution_class": "worker", "foreground_tasks": 0})
    status = _drive("agent.execution.status", {"run_id": "r1", "operation_ids": ["nope"]}, "s1")
    assert status[0][0] == "s1" and status[0][1]["operations"]["nope"]["state"] == "unknown"
    commit = _drive("agent.execution.commit", {"run_id": "r1", "turn_epoch": 1, "task_id": "t1",
                                               "fence_token": 1, "operation_id": "o",
                                               "payload_hash": "h", "collection_name": "c",
                                               "artifact_id": "bad"}, "c1")
    assert commit[0][0] == "c1" and commit[0][1]["error_type"] == "artifact_missing"
    rev = _drive("agent.execution.revoke", {"run_id": "r1", "turn_epoch": 1}, "r1")
    assert rev[0] == ("r1", {"success": True, "known": True, "foreground_tasks": 0})
    unknown = _drive("agent.execution.dance", {}, "u1")
    assert unknown[0][1]["error_type"] == "unknown_method"


def test_notification_gets_no_reply_and_handler_crash_is_reported(env, monkeypatch):
    assert _drive("agent.execution.revoke", {"run_id": "r1"}, request_id=None) == []
    monkeypatch.setattr(handlers.bindings, "revoke", lambda p: 1 / 0)
    out = _drive("agent.execution.revoke", {"run_id": "r1"})
    assert out[0][1]["error_type"] == "handler_error"


def test_jsonrpc_client_routes_prefix_to_callback_or_refuses():
    seen = []
    client = object.__new__(JSONRPCWebSocketClient)
    client._on_execution_request = lambda m, p, rid: seen.append((m, p, rid)) or None
    client._outbound = MagicMock()
    client._handle_execution_request("agent.execution.activate", {"run_id": "r"}, "x")
    assert seen == [("agent.execution.activate", {"run_id": "r"}, "x")]
    client._outbound.put.assert_not_called()  # deferred reply
    worker = object.__new__(JSONRPCWebSocketClient)
    worker._on_execution_request = None
    worker._outbound = MagicMock()
    worker._handle_execution_request("agent.execution.commit", {}, "y")
    payload = json.loads(worker._outbound.put.call_args.args[0])
    assert payload["id"] == "y" and payload["result"]["error_type"] == "capability_unavailable"
