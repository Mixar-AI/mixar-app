# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Disabling and exiting the connector fence incoming work and free resources."""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import socket
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock
import uuid

import pytest

from mixar.modules.mcp_bridge.core import runtime
from mixar.modules.mcp_bridge.core.relay import RelayServer

SPEC = importlib.util.spec_from_file_location("mixar_lifecycle_launcher",
    Path(__file__).resolve().parents[2] / "src/scripts/mixar/mcp.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def server(tmp_path, monkeypatch, forward):
    monkeypatch.setenv("MIXAR_MCP_DISCOVERY_DIR", str(tmp_path))
    context = dict(instance_id=str(uuid.uuid4()), session_id=str(uuid.uuid4()), connected=True)
    relay = RelayServer(lambda: context, forward)
    relay.start()
    return relay


def test_disable_fences_connection_that_already_sent_headers(tmp_path, monkeypatch):
    calls, entered = [], threading.Event()
    relay = server(tmp_path, monkeypatch, lambda *args: calls.append(args))
    from mixar.modules.mcp_bridge.core.relay import RelayHandler
    original = RelayHandler.authorized
    def authorized(handler):
        result = original(handler)
        entered.set()
        return result
    monkeypatch.setattr(RelayHandler, "authorized", authorized)
    body = b'{"jsonrpc":"2.0","id":1,"method":"tools/call"}'
    connection = socket.create_connection(("127.0.0.1", relay.server_port), timeout=3)
    try:
        connection.sendall((
            f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{relay.server_port}\r\n"
            f"Authorization: Bearer {relay.token}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n\r\n").encode())
        assert entered.wait(3), "Request must be accepted before testing disable"
        relay.stop()
        connection.sendall(body)
        response = connection.recv(4096)
        assert b" 503 " in response
        assert not calls
    finally:
        connection.close()
        if not relay.stopping.is_set():
            relay.stop()


def test_failed_discovery_cleanup_still_closes_listening_socket(tmp_path, monkeypatch):
    relay = server(tmp_path, monkeypatch, lambda *args: None)
    relay.record = SimpleNamespace(unlink=MagicMock(side_effect=PermissionError("read-only")))
    with pytest.raises(PermissionError):
        relay.stop()
    assert relay.stopping.is_set() and relay.socket.fileno() == -1


def test_runtime_atexit_never_dereferences_bpy_and_forgets_closed_server(monkeypatch):
    class FreedBlender:
        def __getattr__(self, name):
            raise AssertionError("bpy has already been freed")
    relay = SimpleNamespace(stop=MagicMock())
    monkeypatch.setattr(runtime, "bpy", FreedBlender())
    monkeypatch.setattr(runtime, "_server", relay)
    monkeypatch.setattr(runtime, "_registered", True)
    runtime.unregister(shutdown=True)
    relay.stop.assert_called_once()
    assert runtime._server is None and not runtime._registered


def test_runtime_shutdown_forgets_server_even_when_cleanup_fails(monkeypatch):
    relay = SimpleNamespace(stop=MagicMock(side_effect=PermissionError()))
    monkeypatch.setattr(runtime, "_server", relay)
    with pytest.raises(PermissionError):
        runtime.unregister(shutdown=True)
    assert runtime._server is None


def test_stdio_queue_bounds_pending_bodies_and_releases_slot_after_completion():
    pending = threading.BoundedSemaphore(1)
    entered, done = threading.Event(), threading.Event()
    replies = []
    def handle(request):
        entered.set()
        assert done.wait(3)
    bridge = SimpleNamespace(handle=handle, respond=replies.append)
    with ThreadPoolExecutor(max_workers=1) as pool:
        launcher.submit_request(pool, pending, bridge, {"jsonrpc": "2.0", "id": 1})
        assert entered.wait(3)
        launcher.submit_request(pool, pending, bridge, {"jsonrpc": "2.0", "id": 2})
        assert replies == [{"jsonrpc": "2.0", "id": 2, "error": {
            "code": -32002, "message": "Too many pending MCP requests"}}]
        done.set()
    assert pending.acquire(blocking=False)


def test_stdio_queue_release_when_executor_is_closed():
    pending = threading.BoundedSemaphore(1)
    bridge = SimpleNamespace(handle=lambda request: None, respond=lambda response: None)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pass
    with pytest.raises(RuntimeError):
        launcher.submit_request(pool, pending, bridge, {"jsonrpc": "2.0", "id": 1})
    assert pending.acquire(blocking=False)


def test_optional_qa_health_requires_a_real_qa_launch(monkeypatch):
    monkeypatch.setattr(runtime, "bpy", SimpleNamespace(app=SimpleNamespace(use_event_simulate=True)))
    thread = SimpleNamespace(name="MixarQAServer", is_alive=lambda: True)
    monkeypatch.setattr(runtime.threading, "enumerate", lambda: [thread])
    monkeypatch.setitem(sys.modules, "qa_driver", SimpleNamespace())
    monkeypatch.delenv("MIXAR_QA", raising=False)
    assert runtime._qa_status() == {"qa_enabled": False, "qa_port": None}
    monkeypatch.setenv("MIXAR_QA", "1")
    monkeypatch.setenv("MIXAR_QA_PORT", "4888")
    assert runtime._qa_status() == {"qa_enabled": True, "qa_port": 4888}
    monkeypatch.setenv("MIXAR_QA_PORT", "65536")
    assert runtime._qa_status()["qa_enabled"] is False
    monkeypatch.setenv("MIXAR_QA_PORT", "4888")
    monkeypatch.setattr(thread, "is_alive", lambda: False)
    assert runtime._qa_status()["qa_enabled"] is False
    monkeypatch.setattr(thread, "is_alive", lambda: True)
    monkeypatch.delitem(sys.modules, "qa_driver")
    assert runtime._qa_status()["qa_enabled"] is False


def test_optional_qa_tools_only_append_to_last_backend_page(monkeypatch):
    bridge = launcher.StdioBridge()
    bridge.record = {"port": 1, "token": "local", "instance_id": "desktop"}
    bridge.qa = SimpleNamespace(tools=lambda: [{"name": "mixar_qa_status"}])
    replies = []
    monkeypatch.setattr(bridge, "respond", replies.append)
    pages = [dict(tools=[{"name": "mesh"}], nextCursor="next"), dict(tools=[{"name": "render"}])]
    def request(*args):
        return 200, json.dumps({"jsonrpc": "2.0", "id": 1, "result": pages.pop(0)}).encode()
    monkeypatch.setattr(launcher, "local_request", request)
    bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    bridge.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert replies[0]["result"]["tools"] == [{"name": "mesh"}]
    assert replies[1]["result"]["tools"] == [{"name": "render"}, {"name": "mixar_qa_status"}]


def test_optional_qa_call_routes_to_explicit_adapter_without_backend_dispatch(monkeypatch):
    bridge = launcher.StdioBridge()
    bridge.record = {"port": 1, "token": "local", "instance_id": "desktop"}
    invoked, replies = [], []
    bridge.qa = SimpleNamespace(handles=lambda name: name == "mixar_qa_status",
        call=lambda *args: invoked.append(args) or {"content": [], "isError": False})
    monkeypatch.setattr(bridge, "respond", replies.append)
    backend = MagicMock(side_effect=AssertionError("QA must not execute backend tools"))
    monkeypatch.setattr(launcher, "local_request", backend)
    call_id = str(uuid.uuid4())
    request = {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
               "params": {"name": "mixar_qa_status", "arguments": {},
                          "_meta": {"mixar/request-id": call_id}}}
    bridge.handle(request)
    assert invoked == [("mixar_qa_status", {}, call_id)]
    assert replies[0]["result"] == {"content": [], "isError": False}
    request.pop("id")
    bridge.handle(request)
    assert len(invoked) == 1


def test_optional_qa_health_rejects_a_different_instance(monkeypatch):
    bridge = launcher.StdioBridge()
    bridge.record = {"port": 1, "token": "local", "instance_id": "desktop"}
    monkeypatch.setattr(launcher, "local_request", lambda *a, **kw: (200,
        b'{"instance_id":"other","qa_enabled":true,"qa_port":4777}'))
    with pytest.raises(RuntimeError, match="no longer available"):
        bridge.health()
