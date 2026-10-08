# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The connector sidecar serves the local hub only.

Loopback is shared by every process on the machine and, in some browsers, by
every web page, so every route needs the per-launch bearer token, refuses a
browser ``Origin``, pins ``Host`` and never sends a CORS header.
"""

from http.client import HTTPConnection
import json
import os
from pathlib import Path
import stat
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.connector.core import sidecar  # noqa: E402

SIDECAR_SOURCE = SCRIPTS / "mixar/modules/connector/core/sidecar.py"


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXAR_CONNECTOR_DISCOVERY_DIR", str(tmp_path))
    calls = []
    monkeypatch.setattr(sidecar, "_health", lambda: calls.append("health") or {"ok": True, "app": "mixar"})
    monkeypatch.setattr(sidecar, "_scene", lambda: calls.append("scene") or {"scene_name": "Scene", "objects": []})
    monkeypatch.setattr(sidecar, "_prompt", lambda payload: calls.append(("prompt", payload)) or {"queued": True})
    port = sidecar.start_sidecar(0)
    assert sidecar._server is not None
    try:
        yield {"port": port, "token": sidecar._server.token, "calls": calls, "dir": tmp_path}
    finally:
        sidecar.stop_sidecar()


def request(port, method, path, headers=None, body=None, host=None):
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        sent = dict(headers or {})
        if host is not None:
            sent["Host"] = host  # http.client sends only this Host when one is given
        connection.request(method, path, body=body, headers=sent)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def bearer(token):
    return {"Authorization": "Bearer " + token}


def test_preflight_is_refused_without_any_cors_header(server):
    status, headers, _ = request(server["port"], "OPTIONS", "/scene", {
        "Origin": "https://example.com", "Access-Control-Request-Method": "GET"})
    assert status == 403
    assert not any(name.lower().startswith("access-control-") for name in headers)


def test_scene_needs_the_credential(server):
    status, headers, body = request(server["port"], "GET", "/scene")
    assert status == 401
    assert json.loads(body)["ok"] is False
    assert not any(name.lower().startswith("access-control-") for name in headers)
    assert "scene" not in server["calls"]


def test_health_needs_the_credential(server):
    status, _, _ = request(server["port"], "GET", "/health")
    assert status == 401
    assert "health" not in server["calls"]


def test_wrong_credential_is_rejected(server):
    status, _, _ = request(server["port"], "GET", "/scene", bearer("x" * 43))
    assert status == 401
    assert "scene" not in server["calls"]


def test_browser_origin_is_refused_even_with_the_credential(server):
    headers = {**bearer(server["token"]), "Origin": "https://example.com"}
    status, _, _ = request(server["port"], "GET", "/scene", headers)
    assert status == 403
    assert "scene" not in server["calls"]


def test_rebound_host_name_is_refused(server):
    status, _, _ = request(server["port"], "GET", "/scene", bearer(server["token"]),
                           host="mixar.attacker.example:%d" % server["port"])
    assert status == 403
    assert "scene" not in server["calls"]


def test_hub_with_the_credential_is_served_without_cors(server):
    status, headers, body = request(server["port"], "GET", "/scene", bearer(server["token"]))
    assert status == 200
    assert json.loads(body)["scene_name"] == "Scene"
    assert headers.get("Cache-Control") == "no-store"
    assert not any(name.lower().startswith("access-control-") for name in headers)
    assert server["calls"] == ["scene"]


def test_web_page_cannot_queue_an_agent_prompt(server):
    # A cross-site POST with a "simple" content type needs no preflight, so
    # the handler itself has to refuse it: Origin first, then the token.
    body = json.dumps({"prompt": "delete every object"})
    status, _, _ = request(server["port"], "POST", "/prompt", {
        "Origin": "https://example.com", "Content-Type": "text/plain"}, body)
    assert status == 403
    status, _, _ = request(server["port"], "POST", "/prompt", {"Content-Type": "text/plain"}, body)
    assert status == 401
    assert not [call for call in server["calls"] if call[0] == "prompt"]


def test_hub_prompt_requires_a_json_body(server):
    body = json.dumps({"prompt": "add a cube"})
    headers = {**bearer(server["token"]), "Content-Type": "text/plain"}
    status, _, _ = request(server["port"], "POST", "/prompt", headers, body)
    assert status == 400
    headers["Content-Type"] = "application/json"
    status, _, reply = request(server["port"], "POST", "/prompt", headers, body)
    assert status == 200 and json.loads(reply)["queued"] is True
    assert server["calls"] == [("prompt", {"prompt": "add a cube"})]


def test_oversized_body_is_refused_before_it_is_read(server):
    headers = {**bearer(server["token"]), "Content-Type": "application/json",
               "Content-Length": str(2 * 1024 * 1024)}
    connection = HTTPConnection("127.0.0.1", server["port"], timeout=5)
    try:
        connection.putrequest("POST", "/prompt")
        for name, value in headers.items():
            connection.putheader(name, value)
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 400
    finally:
        connection.close()


def test_credential_is_published_privately_and_withdrawn_on_stop(server):
    record = server["dir"] / ("%d.json" % os.getpid())
    data = json.loads(record.read_text(encoding="utf-8"))
    assert data == {"version": 1, "pid": os.getpid(), "port": server["port"],
                    "token": server["token"]}
    assert len(data["token"]) >= 32
    if os.name != "nt":
        assert stat.S_IMODE(record.stat().st_mode) == 0o600
        assert stat.S_IMODE(server["dir"].stat().st_mode) == 0o700
    sidecar.stop_sidecar()
    assert not record.exists()
    assert sidecar._server is None


def test_unwritable_discovery_record_leaves_no_listener(tmp_path, monkeypatch):
    monkeypatch.setenv("MIXAR_CONNECTOR_DISCOVERY_DIR", str(tmp_path))
    from mixar.modules.connector.core import credential

    def refuse(port, token):
        raise OSError("read-only")
    monkeypatch.setattr(sidecar, "publish", refuse)
    with pytest.raises(OSError):
        sidecar.start_sidecar(0)
    assert sidecar._server is None
    assert not list(tmp_path.glob("*.json"))
    assert credential.discovery_directory() == tmp_path


def test_sidecar_never_sends_a_cors_header():
    source = SIDECAR_SOURCE.read_text(encoding="utf-8")
    assert 'send_header("Access-Control' not in source
    assert "Access-Control-Allow-Origin" not in source
    for method in ("do_GET", "do_POST", "do_OPTIONS"):
        start = source.index("def %s(self)" % method)
        assert "self._authorized()" in source[start:start + 400], method
