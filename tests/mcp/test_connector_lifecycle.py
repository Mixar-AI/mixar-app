# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Disabling and exiting the connector fence incoming work and free resources."""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import socket
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


def test_the_launcher_never_serves_qa_harness_tools():
    """The developer QA adapter (--qa-port, mixar_qa_*) was removed; the harness
    drives its own app directly and AI apps get only product tools."""
    root = Path(__file__).parents[2] / "src/scripts/mixar"
    assert not (root / "modules/mcp_bridge/core/qa_adapter.py").exists()
    source = (root / "mcp.py").read_text()
    assert "--qa-port" not in source and "QAAdapter" not in source
    assert "qa_port" not in (root / "modules/mcp_bridge/core/relay.py").read_text()
