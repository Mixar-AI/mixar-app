# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Real loopback/stdio transport, privacy and connection-routing contracts."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

from mixar.modules.mcp_bridge.core import discovery
from mixar.modules.mcp_bridge.core.relay import RelayServer


SCRIPT = Path(__file__).resolve().parents[2] / "src/scripts/mixar/mcp.py"
SPEC = importlib.util.spec_from_file_location("mixar_launcher_test", SCRIPT.resolve())
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


@pytest.fixture
def relay(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXAR_MCP_DISCOVERY_DIR", str(tmp_path / "discovery"))
    context = {"instance_id": str(uuid.uuid4()), "session_id": str(uuid.uuid4()),
               "scene_name": "MCP Test Scene", "connected": True, "signed_in": True}
    calls = []

    def forward(request, snapshot, headers):
        calls.append((request, snapshot, headers))
        if "id" not in request:
            return 202, None
        result = ({"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                   "serverInfo": {"name": "test", "version": "1"}}
                  if request["method"] == "initialize" else {"content": [], "isError": False})
        return 200, {"jsonrpc": "2.0", "id": request["id"], "result": result}

    server = RelayServer(lambda: dict(context), forward)
    server.start()
    try:
        yield server, context, calls
    finally:
        server.stop()


def record(server):
    return {"port": server.server_port, "token": server.token}


def test_discovery_publishes_private_local_credential_only(relay):
    server, context, _ = relay
    saved = discovery.read_record(server.record)
    assert set(saved) == {"version", "pid", "port", "token", "instance_id"}
    assert saved["instance_id"] == context["instance_id"]
    if os.name != "nt":
        assert server.record.stat().st_mode & 0o777 == 0o600
    assert launcher.discover()["session_id"] == context["session_id"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX ownership/modes")
def test_discovery_refuses_world_readable_tokens(relay):
    server, _, _ = relay
    server.record.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        discovery.read_record(server.record)


def test_discovery_rejects_non_loopback_record_shape(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"version": 1, "port": "https://evil.test", "token": "x" * 32}))
    path.chmod(0o600)
    with pytest.raises(ValueError):
        discovery.read_record(path)


def test_health_requires_local_bearer(relay):
    server, _, _ = relay
    status, _ = launcher.local_request({"port": server.server_port, "token": "wrong"}, "GET", "/health")
    assert status == 401


@pytest.mark.parametrize("headers", [{"Origin": "http://malicious.test"}, {"Host": "malicious.test"}])
def test_browser_and_dns_rebinding_requests_rejected(relay, headers):
    server, _, calls = relay
    status, _ = launcher.local_request(record(server), "POST", "/mcp", b"{}", headers)
    assert status == 403
    assert not calls


def test_transport_pins_explicit_scene_and_passes_call_id(relay):
    server, context, calls = relay
    scene_id, call_id = str(uuid.uuid4()), str(uuid.uuid4())
    status, body = launcher.local_request(record(server), "POST", "/mcp",
        json.dumps({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {}}).encode(),
        {"X-Mixar-Session-Id": scene_id, "X-Mixar-Call-Id": call_id})
    assert status == 200
    assert json.loads(body)["id"] == 4
    assert calls[0][1]["session_id"] == scene_id
    assert calls[0][1]["instance_id"] == context["instance_id"]
    assert calls[0][2]["X-Mixar-Call-Id"] == call_id


def test_disconnected_scene_never_forwards(relay):
    """Listing tools needs only the account; anything reaching the scene needs the
    desktop's live agent connection; nothing is forwarded while signed out."""
    server, context, calls = relay
    context["connected"] = False
    listing = b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
    call = b'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"scene_overview"}}'
    status, _ = launcher.local_request(record(server), "POST", "/mcp", call)
    assert status == 503 and not calls
    status, _ = launcher.local_request(record(server), "POST", "/mcp", listing)
    assert status == 200 and len(calls) == 1
    context["signed_in"] = False
    status, body = launcher.local_request(record(server), "POST", "/mcp", listing)
    assert status == 503 and b"Sign in" in body and len(calls) == 1
    from mixar.modules.mcp_bridge.core import connector  # The agent sees the reason, not "HTTP 503".
    with pytest.raises(RuntimeError, match="^Sign in to Mixar"):
        connector.request(record(server), "POST", "/mcp", json.loads(call))


def test_bad_session_never_forwards(relay):
    server, _, calls = relay
    status, _ = launcher.local_request(record(server), "POST", "/mcp",
        b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}', {"X-Mixar-Session-Id": "../other"})
    assert status == 400
    assert not calls


def test_stdio_has_only_json_protocol_and_preserves_replay_key(relay):
    _, context, calls = relay
    call_id = str(uuid.uuid4())
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "scene_overview", "_meta": {"mixar/request-id": call_id}}},
    ]
    result = subprocess.run([sys.executable, str(SCRIPT), "--legacy-proxy"],
        input="\n".join(json.dumps(item) for item in messages) + "\n", text=True,
        capture_output=True, timeout=20, check=True)
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert {r["id"] for r in replies} == {1, 2}
    assert all("result" in item for item in replies)
    call = next(item for item in calls if item[0]["method"] == "tools/call")
    assert call[1]["session_id"] == context["session_id"]
    assert call[2]["X-Mixar-Call-Id"] == call_id
    assert call[2]["MCP-Protocol-Version"] == "2025-06-18"
    assert not result.stderr


def test_stdio_unknown_outcome_does_not_retry(relay, monkeypatch):
    server, context, _ = relay
    bridge = launcher.StdioBridge()
    bridge.record = {**record(server), "session_id": context["session_id"]}
    responses, attempts = [], []
    monkeypatch.setattr(bridge, "respond", responses.append)

    def fail(*args, **kwargs):
        attempts.append(args)
        raise TimeoutError("Tool response timed out")

    monkeypatch.setattr(launcher, "local_request", fail)
    bridge.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {}})
    assert len(attempts) == 1
    detail = responses[0]["error"]["data"]
    assert detail["outcome"] == "unknown"
    assert str(uuid.UUID(detail["request_id"])) == detail["retry_meta"]["mixar/request-id"]


def test_setup_json_and_toml_escape_install_paths(monkeypatch):
    from mixar.modules.mcp_bridge.core.setup import connection_config
    monkeypatch.setattr(sys, "platform", "win32")
    config = json.loads(connection_config("JSON", 'C:\\Program Files\\Mixar'))
    assert "Mixar" in config["mcpServers"]["mixar"]["command"]
    assert "token" not in json.dumps(config).lower()
    import tomllib
    parsed = tomllib.loads(connection_config("CODEX", 'C:\\Program Files\\Mixar'))
    assert parsed["mcp_servers"]["mixar"]["tool_timeout_sec"] == 610


def test_the_dialog_copies_one_standard_config_and_links_the_guide(monkeypatch):
    """One mcpServers JSON for every app; per-app formats live in the website guide."""
    from mixar.modules.mcp_bridge.constants import SETUP_GUIDE_URL
    from mixar.modules.mcp_bridge.core.setup import connection_config
    monkeypatch.setattr(sys, "platform", "darwin")
    root = "/Applications/Mixar App.app/Contents/Resources/5.2"
    server = json.loads(connection_config("JSON", root))["mcpServers"]["mixar"]
    assert server["command"].startswith(root) and set(server) == {"command", "args"}
    assert SETUP_GUIDE_URL == "https://www.mixar.app/docs#connect-ai-apps"
    from pathlib import Path
    dialog = (Path(__file__).parents[2] / "src/scripts/mixar/modules/mcp_bridge/ui/operators/connect.py").read_text()
    assert 'text="Copy MCP Config"' in dialog and 'text="Setup Guide"' in dialog
    assert "default='JSON'" in dialog
