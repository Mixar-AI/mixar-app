# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Stage-2 wiring pins for local model support.

Functional where the code runs under mocked bpy (the JSON-RPC client's
llm.request dispatch + deferred-response contract, the handshake
capability); source-level where it cannot (the ConnectionManager closure's
threading contract, shutdown hooks, the logout path) — the repo's
established pattern (tests/moodboard, tests/test_job_queue_download.py).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.space_mixie_chat.constants import JSONRPCMethod
from mixar.modules.space_mixie_chat.core.jsonrpc_client import (
    JSONRPCWebSocketClient,
)

_CHAT_CORE = SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "core"
_BOOTSTRAP = SCRIPTS / "mixar" / "bootstrap"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Method constant + dispatch
# ---------------------------------------------------------------------------


def test_llm_request_method_constant():
    assert JSONRPCMethod.LLM_REQUEST == "llm.request"


def _client(**kwargs) -> JSONRPCWebSocketClient:
    return JSONRPCWebSocketClient("https://api.test", "conn-1", **kwargs)


def _drain(client):
    out = []
    while not client._outbound.empty():
        out.append(json.loads(client._outbound.get_nowait()))
    return out


def test_llm_request_deferred_sends_nothing_until_queue_response():
    seen = {}

    def on_llm_request(params, request_id):
        seen["params"] = params
        seen["request_id"] = request_id
        return None  # deferred — respond later from a worker thread

    client = _client(on_llm_request=on_llm_request)
    client._handle_message({
        "jsonrpc": "2.0",
        "method": "llm.request",
        "id": "srv_9",
        "params": {"method": "POST", "url": "http://127.0.0.1:11500/v1/chat/completions"},
    })

    assert seen["request_id"] == "srv_9"
    assert _drain(client) == []  # nothing sent synchronously

    # The worker replies later through the thread-safe outbound queue.
    client.queue_response("srv_9", {"status_code": 200, "headers": {}, "body": "{}"})
    responses = _drain(client)
    assert len(responses) == 1
    assert responses[0]["id"] == "srv_9"
    assert responses[0]["result"]["status_code"] == 200


def test_llm_request_synchronous_result_is_sent():
    client = _client(
        on_llm_request=lambda params, request_id: {
            "error": {"code": "relay_denied", "message": "nope"},
        }
    )
    client._handle_message({"method": "llm.request", "id": "srv_2", "params": {}})
    responses = _drain(client)
    assert len(responses) == 1
    assert responses[0]["result"]["error"]["code"] == "relay_denied"


def test_llm_request_without_handler_reports_relay_unavailable():
    client = _client()
    client._handle_message({"method": "llm.request", "id": "srv_3", "params": {}})
    responses = _drain(client)
    assert len(responses) == 1
    assert responses[0]["id"] == "srv_3"
    assert responses[0]["result"]["error"]["code"] == "relay_unavailable"


def test_llm_request_handler_exception_becomes_relay_internal():
    def boom(params, request_id):
        raise RuntimeError("kaput")

    client = _client(on_llm_request=boom)
    client._handle_message({"method": "llm.request", "id": "srv_4", "params": {}})
    responses = _drain(client)
    assert responses[0]["result"]["error"]["code"] == "relay_internal"


# ---------------------------------------------------------------------------
# Handshake capability
# ---------------------------------------------------------------------------


class _FakeWS:
    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(data)

    def recv(self):
        return json.dumps({"result": {"success": True}})

    def settimeout(self, _timeout):
        pass


def test_handshake_advertises_local_llm_capability():
    client = _client()
    client._ws = _FakeWS()
    assert client._perform_handshake() is True
    handshake = json.loads(client._ws.sent[0])
    assert handshake["method"] == JSONRPCMethod.SYSTEM_HANDSHAKE
    capabilities = handshake["params"]["capabilities"]
    assert "local_llm" in capabilities
    # The existing capabilities must survive the addition.
    assert "script_execution" in capabilities
    assert "notifications" in capabilities


# ---------------------------------------------------------------------------
# ConnectionManager closure — threading contract (source-level: the closure
# only runs inside a live connect())
# ---------------------------------------------------------------------------


def test_connection_manager_wires_deferred_llm_relay():
    source = _read(_CHAT_CORE / "connection_manager.py")
    assert "def on_llm_request(" in source
    assert "on_llm_request=on_llm_request" in source

    closure = source.split("def on_llm_request(", 1)[1]
    closure = closure.split("\n        # Create JSON-RPC WebSocket client", 1)[0]
    # Daemon worker named per convention; replies via queue_response.
    assert "MixarLocalLLMRelay" in closure
    assert "daemon=True" in closure
    assert "queue_response" in closure
    # Deferred contract: the WS-thread callback returns None.
    assert "return None" in closure
    # The worker relays through the Stage-1 executor.
    assert "local_models.core.relay import handle_llm_request" in closure
    # Background threads never touch bpy (the docstring may mention it,
    # but no code in the closure imports or dereferences it).
    assert "import bpy" not in closure
    assert "bpy." not in closure


def test_jsonrpc_handler_defers_when_callback_returns_none():
    source = _read(_CHAT_CORE / "jsonrpc_client.py")
    handler = source.split("def _handle_llm_request(", 1)[1]
    handler = handler.split("def _handle_sandbox_control(", 1)[0]
    assert "if result is None:" in handler
    after = handler.split("if result is None:", 1)[1]
    # The deferred branch returns without queueing anything.
    assert after.lstrip().startswith(
        "# Deferred — the handler responds via queue_response later.\n"
        "                    return"
    )
    assert "queue_response" in handler


# ---------------------------------------------------------------------------
# Shutdown + logout wiring (source-level)
# ---------------------------------------------------------------------------


def test_shutdown_hooks_stop_the_local_server():
    source = _read(_BOOTSTRAP / "shutdown_hooks.py")
    assert "local_models.core.server_supervisor import stop_all" in source
    assert '_safe("stop_local_model_server", stop_all)' in source


def test_bootstrap_module_registers_and_stops():
    source = _read(_BOOTSTRAP / "local_models_module.py")
    assert "paths.initialize()" in source
    assert "orchestrator.resume_registered()" in source
    assert "orchestrator.watch_tick()" in source
    assert "orchestrator.shutdown()" in source


def test_logout_clears_local_state_and_stops_server():
    source = _read(
        SCRIPTS / "mixar" / "modules" / "space_mixie_chat" / "ui"
        / "operators" / "auth_ops.py"
    )
    body = source.split("def _clear_byok_state_on_logout(", 1)[1]
    body = body.split("\ndef ", 1)[0]
    assert "byok_form_local_custom_key" in body
    assert "orchestrator.on_logout()" in body
    assert "local_provider.clear()" in body
    assert "wipe_transient_state(wm)" in body
