# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""``engine_link``: discovery, the MCP session (with one re-initialize on a
404), result mapping, path scrubbing and the package import, against a fake
Mixar Link server on 127.0.0.1 (no engine, no Blender)."""

import http.server
import json
import os
import sys
import threading
import time
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), *([".."] * 4)))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.core import engine_link, export_package  # noqa: E402

TOKEN = "t" * 48


class _Fake(http.server.BaseHTTPRequestHandler):
    sessions: set = set()
    issued = 0
    calls: list = []
    expire_next = False

    def log_message(self, *a):
        pass

    def _send(self, status, body=None, headers=None):
        raw = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._send(401)
        if "id" not in msg:
            return self._send(202)
        if msg["method"] == "initialize":
            type(self).issued += 1
            sid = f"s{type(self).issued}"
            self.sessions.add(sid)
            return self._send(200, {"jsonrpc": "2.0", "id": msg["id"], "result": {"serverInfo": {}}},
                              {"Mcp-Session-Id": sid})
        sid = self.headers.get("Mcp-Session-Id")
        if type(self).expire_next:
            type(self).expire_next = False
            self.sessions.discard(sid)
        if sid not in self.sessions:
            return self._send(404)
        name, args = msg["params"]["name"], msg["params"]["arguments"]
        self.calls.append((name, args))
        if name == "capture":
            result = {"content": [{"type": "text", "text": "{}"},
                                  {"type": "image", "data": "/9j/AA==", "mimeType": "image/jpeg"}],
                      "structuredContent": {"source": "game", "width": 4, "height": 3}, "isError": False}
        elif name == "play":
            result = {"content": [{"type": "text", "text": "The game did not connect"}],
                      "structuredContent": {"error": "The game did not connect", "log_seq": 7}, "isError": True}
        else:
            result = {"content": [{"type": "text", "text": "{}"}],
                      "structuredContent": {"tool": name, "seen": args.get("source_dir", ""),
                                            "note": "imported from /Users/someone/Mixar Exports/Crate"},
                      "isError": False}
        self._send(200, {"jsonrpc": "2.0", "id": msg["id"], "result": result})


@pytest.fixture
def link(tmp_path, monkeypatch):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Fake.sessions, _Fake.calls, _Fake.expire_next, _Fake.issued = set(), [], False, 0
    link_dir = tmp_path / "engine-link"
    link_dir.mkdir()
    monkeypatch.setattr(engine_link, "LINK_DIR", str(link_dir))
    engine_link._clients.clear()
    (link_dir / "godot-1.json").write_text(json.dumps({
        "engine": "godot", "version": "4.7.2", "adapter_version": "0.1.0", "project_name": "Ruins",
        "pid": 1, "port": server.server_address[1], "token": TOKEN, "started_at": time.time()}))
    yield link_dir
    server.shutdown()


def test_discovery_skips_dead_and_broken_files(link):
    (link / "godot-2.json").write_text(json.dumps({"engine": "godot", "pid": 2, "port": 1, "token": "x",
                                                   "started_at": time.time() + 10}))
    (link / "junk.json").write_text("{not json")
    found = engine_link.adapters()
    assert [a["pid"] for a in found] == [1]
    assert engine_link.adapters("unreal") == []
    assert engine_link.public(found[0]) == {"id": "godot-1", "engine": "godot", "version": "4.7.2",
                                             "adapter_version": "0.1.0", "project_name": "Ruins"}


def test_no_engine_is_a_plain_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_link, "LINK_DIR", str(tmp_path))
    out = engine_link.link_status()
    assert out["success"] is False and "Mixar Link" in out["error"] and out["adapters"] == []
    assert engine_link.link_call("status")["error"] == engine_link.NO_ENGINE


def test_status_reuses_the_session_and_reinitialises_once_on_404(link):
    out = engine_link.link_status()
    assert out["success"] and out["connected"]["project_name"] == "Ruins"
    assert engine_link.link_call("scene_tree")["data"]["tool"] == "scene_tree"
    assert _Fake.sessions == {"s1"}
    _Fake.expire_next = True
    assert engine_link.link_call("scene_tree")["success"]
    assert _Fake.sessions == {"s2"}


def test_results_map_errors_images_and_scrub_paths(link):
    played = engine_link.link_call("play", {"scene": "main"})
    assert played == {"success": False, "data": {"error": "The game did not connect", "log_seq": 7},
                      "error": "The game did not connect"}
    shot = engine_link.link_call("capture", {"source": "game"})
    assert shot["success"] and shot["image_base64"] == "/9j/AA==" and shot["image_mime"] == "image/jpeg"
    tree = engine_link.link_call("scene_tree")
    assert "/Users" not in json.dumps(tree) and "<local path>" in tree["data"]["note"]


def test_import_package_is_only_reachable_by_folder_name(link, tmp_path, monkeypatch):
    assert "not an engine tool" in engine_link.link_call("import_package", {"source_dir": "/etc"})["error"]
    exports = tmp_path / "Mixar Exports"
    (exports / "Crate").mkdir(parents=True)
    monkeypatch.setattr(export_package, "destination",
                        lambda where, sub=None, create=True: str(exports / export_package._safe(sub)))
    missing = engine_link.link_import("Barrel")
    assert not missing["success"] and "export it with export_asset first" in missing["error"]
    assert not (exports / "Barrel").exists()
    (exports / "Crate" / "manifest.json").write_text("{}")
    out = engine_link.link_import("Crate")
    assert out["success"]
    name, args = _Fake.calls[-1]
    assert name == "import_package" and args == {"source_dir": str(exports / "Crate"), "folder": "Crate"}
    # The local path went to the engine only; what comes back is scrubbed.
    assert str(exports) not in json.dumps(out)


def test_destination_lookup_never_creates_a_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
    path = export_package.destination("downloads", "Nope", create=False)
    assert path.endswith(os.path.join("Downloads", "Nope")) and not os.path.exists(path)
