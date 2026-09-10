# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transport coverage for explicit agent script provenance and the v3 envelope."""

import os
import sys
from unittest.mock import MagicMock

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)
for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.common.agent_execution.request import ExecutionRequest  # noqa: E402
from mixar.modules.space_mixie_chat.core.jsonrpc_client import JSONRPCWebSocketClient  # noqa: E402
from mixar.modules.space_mixie_chat.core import main_thread_executor  # noqa: E402


def test_execute_script_handler_forwards_agent_ctx():
    received = {}
    client = object.__new__(JSONRPCWebSocketClient)

    def callback(script, request_id, tool_name, session_id, agent_ctx):
        received.update(
            script=script,
            request_id=request_id,
            tool_name=tool_name,
            session_id=session_id,
            agent_ctx=agent_ctx,
        )
        return None

    client._on_script_execute = callback
    agent_ctx = {"chat_session_id": "chat-1", "turn_id": "turn-1"}
    client._handle_execute_script(
        {
            "script": "print('ok')",
            "tool_name": "test_tool",
            "session_id": "scene-route-1",
            "agent_ctx": agent_ctx,
        },
        "transport-1",
    )

    assert received["agent_ctx"] == agent_ctx
    assert received["session_id"] == "scene-route-1"
    assert received["request_id"] == "transport-1"


def test_execute_script_handler_forwards_absent_agent_ctx():
    received = []
    client = object.__new__(JSONRPCWebSocketClient)
    client._on_script_execute = lambda *args: received.append(args)

    client._handle_execute_script(
        {"script": "pass", "session_id": "scene-route-2"}, "transport-2"
    )

    assert received[0][4] is None


def test_execute_script_handler_passes_envelope_only_when_present():
    received = []
    client = object.__new__(JSONRPCWebSocketClient)
    client._on_script_execute = lambda *args, **kw: received.append((args, kw))

    client._handle_execute_script({"script": "pass"}, "t-1")
    client._handle_execute_script(
        {"script": "pass", "envelope": {"run_id": "r", "task_id": "t"}}, "t-2"
    )

    assert received[0][1] == {}
    assert received[1][1] == {"envelope": {"run_id": "r", "task_id": "t"}}


def test_queue_holds_execution_request_with_agent_ctx(monkeypatch):
    while not main_thread_executor._request_queue.empty():
        main_thread_executor._request_queue.get_nowait()
    monkeypatch.setattr(main_thread_executor, "maybe_start_prefetch", lambda *_: None)
    monkeypatch.setattr(main_thread_executor, "_ensure_timer_running", lambda: None)
    agent_ctx = {"chat_session_id": "chat-3", "turn_id": "turn-3"}

    main_thread_executor.queue_script_request(
        "pass", "transport-3", "test_tool", "scene-route-3", agent_ctx
    )

    queued = main_thread_executor._request_queue.get_nowait()
    assert isinstance(queued, ExecutionRequest)
    assert queued.as_tuple()[:5] == (
        "transport-3",
        "pass",
        "test_tool",
        "scene-route-3",
        agent_ctx,
    )
