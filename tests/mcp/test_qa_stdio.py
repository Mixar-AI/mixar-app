# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real stdio and loopback proof for the explicitly enabled semantic QA adapter."""

import importlib.util
import json
from pathlib import Path
import socketserver
import subprocess
import sys
import threading
from unittest.mock import MagicMock
import uuid

import pytest

from mixar.modules.mcp_bridge.core.relay import RelayServer

SCRIPT = Path(__file__).resolve().parents[2] / "src/scripts/mixar/mcp.py"
SPEC = importlib.util.spec_from_file_location("mixar_qa_stdio_launcher", SCRIPT)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


@pytest.fixture
def qa_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXAR_MCP_DISCOVERY_DIR", str(tmp_path / "discovery"))
    qa_calls, backend_calls = [], []
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            request = json.loads(self.rfile.readline(65536))
            qa_calls.append(request)
            self.wfile.write(json.dumps({"ok": True, "result": {"objects": 3, "state": "IDLE"}}).encode() + b"\n")
    harness = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    harness.daemon_threads = True
    threading.Thread(target=harness.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    state = {"instance_id": str(uuid.uuid4()), "session_id": str(uuid.uuid4()), "connected": True,
             "qa_enabled": True, "qa_port": harness.server_address[1]}
    def forward(request, context, headers):
        backend_calls.append(request)
        if request["method"] == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "Mixar", "version": "test"}}
        else:
            result = {"tools": [{"name": "scene_overview", "inputSchema": {"type": "object"}}]}
        return 200, {"jsonrpc": "2.0", "id": request["id"], "result": result}
    relay = RelayServer(lambda: dict(state), forward)
    relay.start()
    try:
        yield relay, state, qa_calls, backend_calls
    finally:
        relay.stop()
        harness.shutdown()
        harness.server_close()


def test_real_stdio_qa_listing_and_numeric_request_id_preserve_protocol(qa_runtime):
    relay, state, qa_calls, backend_calls = qa_runtime
    call_id = str(uuid.uuid4())
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "mixar_qa_status", "arguments": {}, "_meta": {"mixar/request-id": call_id}}},
    ]
    result = subprocess.run([sys.executable, str(SCRIPT), "--qa-port", str(state["qa_port"])],
        input="".join(json.dumps(item) + "\n" for item in messages), capture_output=True,
        text=True, timeout=15, check=True)
    replies = {item["id"]: item for item in map(json.loads, result.stdout.splitlines())}
    assert set(replies) == {1, 2, 3} and not result.stderr
    names = {tool["name"] for tool in replies[2]["result"]["tools"]}
    assert {"scene_overview", "mixar_qa_status", "mixar_qa_snap"} <= names
    usage = replies[3]["result"]["structuredContent"]["usage"]
    assert usage["credits_charged"] == 0 and usage["request_id"] == call_id
    assert qa_calls == [{"cmd": "status", "args": {}}]
    assert all(request["method"] != "tools/call" for request in backend_calls)


@pytest.mark.parametrize("change", [{"qa_enabled": False}, {"qa_port": 1}])
def test_qa_call_rechecks_current_authenticated_health(qa_runtime, monkeypatch, change):
    relay, state, qa_calls, _ = qa_runtime
    bridge = launcher.StdioBridge(qa_port=state["qa_port"])
    bridge.record = launcher.discover()
    assert bridge.qa.tools()
    state.update(change)
    replies = []
    monkeypatch.setattr(bridge, "respond", replies.append)
    bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": "mixar_qa_status", "arguments": {}}})
    assert replies[0]["error"]["code"] == -32000
    assert not qa_calls
