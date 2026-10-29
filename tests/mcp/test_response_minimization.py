# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Local MCP results show the model only what the request needs.

Mirrors the backend's response-minimization contract (``billing.visible_usage``):
local tools move no credits, so their content and structuredContent carry no
usage block, request ID or other product's name; the call UUID is visible only
while a mutation's outcome is open, for mixar_ui_call_status. The full receipt
rides in ``_meta["mixar/usage"]``.
"""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

from mcp import Client
import pytest

from mixar.modules.common.ui_control.core import service
from mixar.modules.common.ui_control.core.receipts import Receipts
from mixar.modules.mcp_bridge.core import availability, connector, stdio_server

OWNER = str(uuid4())


def visible(result):
    """Everything the AI app's model can read of a result."""
    return json.dumps([result["content"], result["structuredContent"]])


@pytest.fixture
def receipts(tmp_path, monkeypatch):
    journal = Receipts(tmp_path / "receipts.sqlite")
    monkeypatch.setattr(service, "_receipts", journal)
    monkeypatch.setattr(service, "_registered", True)
    yield journal
    journal.close()


def test_a_free_local_result_has_no_usage_block():
    call_id = str(uuid4())
    result = service.envelope({"scenes": [{"name": "Scene"}]}, call_id)
    assert result["structuredContent"] == {"result": {"scenes": [{"name": "Scene"}]}}
    assert call_id not in visible(result) and "usage" not in visible(result)
    receipt = result["_meta"]["mixar/usage"]
    assert receipt["call_id"] == call_id and receipt["credits_charged"] == 0
    assert "request_id" not in receipt and "note" not in receipt


def test_call_status_answers_only_the_recorded_outcome(receipts):
    asked, call_id = str(uuid4()), str(uuid4())
    receipts.claim(asked, receipts.digest("", "mixar_scene_new", {}))
    result = service.submit(OWNER, "mixar_ui_call_status", {"call_id": asked}, call_id)
    assert result["structuredContent"] == {"result": {"call_id": asked, "status": "accepted"}}
    assert call_id not in visible(result)


@pytest.mark.parametrize("status,shown", [("succeeded", False), ("outcome_unknown", True)])
def test_a_replay_shows_its_call_id_only_while_the_outcome_is_open(receipts, status, shown):
    call_id, args = str(uuid4()), {"name": "Classroom"}
    receipts.claim(call_id, receipts.digest("", "mixar_scene_new", args))
    receipts.finish(call_id, status)
    result = service.submit(OWNER, "mixar_scene_new", args, call_id)
    assert result["structuredContent"]["result"] == {"replayed": True, "status": status}
    assert result["isError"] is shown
    assert (result["structuredContent"].get("usage") == {"call_id": call_id, "status": status}) is shown
    assert (call_id in visible(result)) is shown


def test_a_claimed_mutation_that_failed_shows_its_call_id(receipts, monkeypatch):
    monkeypatch.setattr(service.observe, "invalidate", lambda: None)
    monkeypatch.setattr(service.ownership, "release", lambda *_: None)
    call_id = str(uuid4())
    receipts.claim(call_id, receipts.digest("", "mixar_ui_act", {}))
    request = service.Request(OWNER, "mixar_ui_act", {}, call_id, "", 0.0, claimed=True)
    service._finish(request, {"error_type": "outcome_unknown", "error": "interrupted"},
                    failed=True, status="outcome_unknown")
    assert request.result["structuredContent"]["usage"] == {"call_id": call_id, "status": "outcome_unknown"}
    refused = service.Request(OWNER, "mixar_scene_new", {}, str(uuid4()), "", 0.0)
    service._finish(refused, {"error_type": "scene_limit", "error": "full"}, failed=True, status="failed")
    assert "usage" not in refused.result["structuredContent"]  # Nothing ran: nothing to recover.


def test_reconnect_advice_names_no_ai_app():
    for text in availability.NEXT_STEPS.values():
        assert "Claude" not in text and "Codex" not in text


def test_launcher_failures_show_the_call_id_only_when_the_outcome_is_unknown():
    call_id = str(uuid4())
    refused = stdio_server.failure(RuntimeError("Mixar is not open"), call_id).model_dump(by_alias=True)
    # usage stays {} for outputSchemas listed before it became optional.
    assert refused["structuredContent"] == {"result": {"error": "Mixar is not open"}, "usage": {}}
    assert call_id not in json.dumps(refused["content"]) and refused["_meta"]["mixar/request-id"] == call_id
    lost = stdio_server.failure(connector.Unconfirmed("answer lost"), call_id).model_dump(by_alias=True)
    assert lost["structuredContent"]["usage"] == {"call_id": call_id, "status": "unknown"}


@pytest.mark.parametrize("raised,unconfirmed", [
    (connector.Refused("Sign in to Mixar before using its tools", 503), False),
    (connector.Refused("Too many MCP requests", 429), False),
    (ConnectionRefusedError(61, "Connection refused"), False),
    (connector.Refused("MCP network request failed (NET-TIMEOUT)", 502), True),
    (TimeoutError("timed out"), True),
])
def test_only_a_call_that_may_have_run_is_unconfirmed(monkeypatch, raised, unconfirmed):
    client = connector.Connector()
    monkeypatch.setattr(client, "attach", lambda **_: ({}, {"session_id": "scene"}))

    def send(*_args, **_kwargs):
        raise raised

    monkeypatch.setattr(connector, "request", send)
    with pytest.raises(Exception) as caught:
        client.call("execute_bpy_script", {}, str(uuid4()))
    assert isinstance(caught.value, connector.Unconfirmed) is unconfirmed


def test_a_json_rpc_refusal_is_not_an_unknown_outcome(monkeypatch):
    client = connector.Connector()
    monkeypatch.setattr(client, "attach", lambda **_: ({}, {"session_id": "scene"}))
    monkeypatch.setattr(connector, "request", lambda *_a, **_k: {"error": {"message": "bad params"}})
    with pytest.raises(RuntimeError) as caught:
        client.call("execute_bpy_script", {}, str(uuid4()))
    assert not isinstance(caught.value, connector.Unconfirmed)


def test_the_launchers_own_answers_carry_no_usage_block():
    class Idle:
        tasks = set()

        def catalog(self):
            return []

        def cancel(self, call_id=None):
            pass

    async def main():
        async with Client(stdio_server.create_server(Idle())) as client:
            quote = await client.call_tool("mixar_tool_quote", {"tool": "mixar_scenes"})
            index = await client.call_tool("mixar_tool_catalog", {"domain": "scenes"})
            return quote, index

    for result in asyncio.run(main()):
        assert result.structured_content == {"result": result.structured_content["result"], "usage": {}}
        text = json.dumps([block.text for block in result.content])
        assert "usage" not in text and "request_id" not in text and "surface" not in text
        assert result.meta["mixar/usage"]["credits_charged"] == 0


def test_the_backend_receipt_reaches_the_ai_app_in_meta():
    receipt = {"call_id": str(uuid4()), "tool": "create_layered_material", "status": "succeeded",
               "credits_charged": 3, "remaining_credits": 97}
    answer = {"content": [{"type": "text", "text": "{}"}, {"type": "image", "data": "AA==", "mimeType": "image/png"}],
              "structuredContent": {"result": {}, "usage": {"credits_charged": 3, "remaining_credits": 97}},
              "isError": False, "_meta": {"mixar/usage": receipt}}

    class Backend:
        tasks = set()

        def catalog(self):
            return []

        def call(self, name, arguments, call_id):
            return json.loads(json.dumps(answer))

        def cancel(self, call_id=None):
            pass

    async def main():
        async with Client(stdio_server.create_server(Backend())) as client:
            return await client.call_tool("create_layered_material", {})

    assert asyncio.run(main()).meta["mixar/usage"] == receipt
    shaped = stdio_server.presentation.for_client(answer, "codex-mcp-client")
    assert "structuredContent" not in shaped and shaped["_meta"]["mixar/usage"] == receipt
