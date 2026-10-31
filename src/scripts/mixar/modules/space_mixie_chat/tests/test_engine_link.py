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


@pytest.mark.parametrize("text,expected", [
    # Spaces inside a path, quoted and unquoted; any drive letter, either separator.
    (r"Saved C:\Users\John Smith\Documents\Game\level.tscn ok", "Saved <local path> ok"),
    ("Saved to D:/Unreal Projects/MyGame/Content/Maps/Arena.umap.", "Saved to <local path>."),
    (r'Open "C:\Users\John Smith\My Game\main scene.tscn" failed', 'Open "<local path>" failed'),
    (r"Open 'z:\Games\Some Folder\file name.txt' failed", "Open '<local path>' failed"),
    ("C:/Users/John Smith/project", "<local path>"),
    (r"Failed (E:\Users\Ann\x.gd)", "Failed (<local path>)"),
    (r"escaped C:\\Users\\John Smith\\x.txt here", "escaped <local path> here"),
    # UNC shares, home-relative and file:// paths.
    (r"share at \\fileserver\team share\proj\a.txt now", "share at <local path> now"),
    ("home ~/Projects/my game/scene.tscn there", "home <local path> there"),
    (r"home ~\Projects\scene.tscn there", "home <local path> there"),
    ("file:///Users/john/a.glb loaded", "<local path> loaded"),
    # POSIX: system roots and any lower-case first folder.
    ("root /root/proj/x.gd and /home/ann/My Stuff/a b.png", "root <local path> and <local path>"),
    ("/Users/john doe/Library/Application Support/Godot/x.log", "<local path>"),
    ('{"path": "/Volumes/Ext Drive/game/a.png"}', '{"path": "<local path>"}'),
    ("plain /tmp/x and /srv/games/foo/bar", "plain <local path> and <local path>"),
    ("in /private/var/folders/x/T/mixar-link-1/a.zip", "in <local path>"),
    # Not local paths: engine resource paths, URLs, Unreal package paths, prose.
    ("res://mixar/Crate/crate.glb and user://save.dat", "res://mixar/Crate/crate.glb and user://save.dat"),
    ("https://example.com/a/b", "https://example.com/a/b"),
    ("/Game/Mixar/Maps/Arena and /Script/Engine.Actor", "/Game/Mixar/Maps/Arena and /Script/Engine.Actor"),
    ("50/50 and/or a/b", "50/50 and/or a/b"),
])
def test_scrub_removes_every_absolute_local_path(text, expected):
    assert engine_link.scrub(text) == expected


def test_scrub_walks_keys_lists_and_tuples():
    out = engine_link.scrub({"C:\\Users\\Ann\\a.txt": ("/home/ann/b c/d.png", ["~/x/y"]), "n": 3})
    assert out == {"<local path>": ["<local path>", ["<local path>"]], "n": 3}


def test_scrub_stays_linear_on_long_text():
    started = time.monotonic()
    engine_link.scrub(("word /Users/abc " + "x" * 50 + " ") * 20000 + "C:\\ " + "a b c d " * 100000)
    assert time.monotonic() - started < 2.0


def test_the_callable_tools_are_the_adapters_minus_import():
    # Every adapter tool the backend's engine_* tools call by name. A name
    # missing here fails the agent's call in the client, before Godot sees it
    # (engine_file could write no script on 2026-10-23).
    assert set(engine_link.CALLABLE_TOOLS) == {
        "status", "new_scene", "open_scene", "place", "scene_tree", "save_scene", "play", "stop",
        "capture", "log", "playtest", "write_script", "add_node", "set_property", "remove_node",
        "read_file", "list_files", "write_file", "delete_file", "project_setting", "build_web",
        "build_info", "blueprint"}
    assert "import_package" not in engine_link.CALLABLE_TOOLS


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


class _Store(http.server.BaseHTTPRequestHandler):
    got: dict = {}
    sent: dict = {}

    def log_message(self, *a):
        pass

    def do_PUT(self):
        type(self).got[self.path] = (self.headers.get("Content-Type"),
                                     self.rfile.read(int(self.headers["Content-Length"])))
        type(self).sent[self.path] = (self.headers.get("Content-Length"), self.headers.get("Transfer-Encoding"),
                                      self.headers.get("x-amz-meta-share"))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


def test_a_web_build_uploads_from_the_engine_folder(link, tmp_path, monkeypatch):
    web = tmp_path / "proj" / "mixar_build" / "web"
    web.mkdir(parents=True)
    (web / "index.html").write_bytes(b"<html></html>")
    (web / "index.wasm").write_bytes(b"\0asm1234")

    def build_info(self, name, args):
        if name != "build_info":
            return None
        # The engine's own figures are stale: the manifest reads the disk.
        return {"content": [{"type": "text", "text": "{}"}], "isError": False, "structuredContent": {
            "dir": str(web), "files": [{"name": "index.html", "bytes": 1}, {"name": "index.wasm", "bytes": 999}]}}

    monkeypatch.setattr(_Fake, "build_info", build_info, raising=False)
    original = _Fake.do_POST

    def do_post(self):
        length = int(self.headers["Content-Length"])
        raw = self.rfile.read(length)
        msg = json.loads(raw)
        if msg.get("method") == "tools/call" and msg["params"]["name"] == "build_info":
            return self._send(200, {"jsonrpc": "2.0", "id": msg["id"], "result": self.build_info("build_info", {})})
        self.rfile = __import__("io").BytesIO(raw)
        return original(self)

    monkeypatch.setattr(_Fake, "do_POST", do_post)
    assert engine_link.link_build_manifest() == {"success": True, "files": [
        {"name": "index.html", "bytes": 13}, {"name": "index.wasm", "bytes": 8}]}
    store = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Store)
    threading.Thread(target=store.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{store.server_address[1]}"
    try:
        out = engine_link.link_upload_build([
            {"name": "index.html", "url": f"{base}/k/index.html", "headers": {"Content-Type": "text/html"}},
            {"name": "index.wasm", "url": f"{base}/k/index.wasm",
             "headers": {"Content-Type": "application/wasm", "x-amz-meta-share": "s1", "Content-Length": "999"}}])
        refused = engine_link.link_upload_build([{"name": "../../etc/passwd", "url": f"{base}/x", "headers": {}}])
        # Rebuilt after the manifest: the signed length no longer fits, nothing is sent.
        (web / "index.wasm").write_bytes(b"\0asm12345678")
        got, _Store.got = dict(_Store.got), {}
        changed = engine_link.link_upload_build([{"name": "index.wasm", "url": f"{base}/k/index.wasm",
                                                  "headers": {}}])
    finally:
        store.shutdown()
    assert out == {"success": True, "uploaded": 2, "bytes": 21}
    assert got["/k/index.wasm"] == ("application/wasm", b"\0asm1234")
    # The whole file, its exact length (not the engine's, not a stale header), never chunked; the given headers ride.
    assert _Store.sent["/k/index.wasm"] == ("8", None, "s1")
    assert _Store.sent["/k/index.html"][:2] == ("13", None)
    assert not refused["success"] and "/etc" not in json.dumps(refused)
    assert not changed["success"] and "changed since the share started" in changed["error"] and not _Store.got


# ---------------------------------------------------------------------------
# Unreal: Mixar Link's toolset inside Unreal's own MCP server
# ---------------------------------------------------------------------------

TOOLSET = "mixar_link.toolsets.MixarLinkTools"


class _FakeUnreal(_Fake):
    """Unreal's server: no token, tools only through ``call_tool``, each
    answering a JSON string under ``returnValue``."""

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("Authorization"):
            return self._send(400)  # Mixar sends no token to Unreal
        if "id" not in msg:
            return self._send(202)
        if msg["method"] == "initialize":
            return self._send(200, {"jsonrpc": "2.0", "id": msg["id"], "result": {}}, {"Mcp-Session-Id": "u1"})
        name, args = msg["params"]["name"], msg["params"]["arguments"]
        self.calls.append((name, args))
        if name != "call_tool" or args.get("toolset_name") != TOOLSET:
            result = {"content": [{"type": "text", "text": f"Toolset '{args.get('toolset_name')}' not found"}],
                      "isError": True}
        elif args["tool_name"] == "status":
            reply = {"ok": True, "data": {"engine": "unreal", "project_name": "Arena3D",
                                          "edited_scene": "/Game/Maps/Arena"}}
            result = {"content": [{"type": "text", "text": json.dumps({"returnValue": json.dumps(reply)})}]}
        elif args["tool_name"] == "scene_tree":
            reply = {"ok": False, "error": "No level is open.", "data": {"hint": "open one"}}
            result = {"content": [{"type": "text", "text": json.dumps({"returnValue": json.dumps(reply)})}]}
        elif args["tool_name"] == "capture":
            reply = {"ok": True, "data": {"source": "game", "image_base64": "iVBO", "image_mime": "image/png"}}
            result = {"content": [{"type": "text", "text": json.dumps({"returnValue": json.dumps(reply)})}]}
        else:
            result = {"content": [{"type": "text", "text": f"Unknown tool {args['tool_name']}"}], "isError": True}
        self._send(200, {"jsonrpc": "2.0", "id": msg["id"], "result": result})


@pytest.fixture
def unreal(tmp_path, monkeypatch):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeUnreal)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _FakeUnreal.calls = []
    link_dir = tmp_path / "engine-link"
    link_dir.mkdir()
    monkeypatch.setattr(engine_link, "LINK_DIR", str(link_dir))
    engine_link._clients.clear()
    (link_dir / f"unreal-{os.getpid()}.json").write_text(json.dumps({
        "engine": "unreal", "version": "5.8.4-58902052+++UE5+Release-5.8", "adapter_version": "0.1.0",
        "project_name": "Arena3D", "pid": os.getpid(), "port": server.server_address[1], "path": "/mcp",
        "token": "", "transport": "unreal_mcp", "toolset": TOOLSET, "started_at": time.time(),
        "defaults": {"place": {"name": "", "position": [0.0, 0.0, 0.0], "animation": ""}},
        "json_args": {"playtest": ["steps"], "set_property": ["value"]}}))
    yield link_dir
    server.shutdown()


def test_unreal_is_discovered_without_a_token_but_a_tokenless_godot_is_not(unreal):
    (unreal / "godot-3.json").write_text(json.dumps({"engine": "godot", "pid": os.getpid(), "token": "",
                                                    "port": 1, "started_at": time.time()}))
    assert [a["engine"] for a in engine_link.adapters()] == ["unreal"]


def test_a_dead_editors_file_is_skipped_even_when_its_port_answers(unreal, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("Windows never probes pids")
    info = json.loads((unreal / f"unreal-{os.getpid()}.json").read_text())
    (unreal / "unreal-999999.json").write_text(json.dumps({**info, "pid": 999999, "started_at": time.time() + 5}))
    assert [a["pid"] for a in engine_link.adapters("unreal")] == [os.getpid()]


def test_unreal_tools_go_through_call_tool_and_come_back_in_godots_shape(unreal):
    out = engine_link.link_status()
    assert out["success"] and out["data"]["project_name"] == "Arena3D"
    assert out["connected"]["id"] == f"unreal-{os.getpid()}"
    assert _FakeUnreal.calls[0] == ("call_tool", {"toolset_name": TOOLSET, "tool_name": "status", "arguments": {}})
    tree = engine_link.link_call("scene_tree", {"max_nodes": 5})
    assert tree == {"success": False, "data": {"hint": "open one", "error": "No level is open."},
                    "error": "No level is open."}
    shot = engine_link.link_call("capture", {"source": "game"})
    assert shot["success"] and shot["image_base64"] == "iVBO" and shot["image_mime"] == "image/png"
    assert "image_base64" not in shot["data"]
    missing = engine_link.link_call("place", {"scene": "/Game/Mixar/Crate"})
    assert missing == {"success": False, "data": {}, "error": "Unknown tool place"}


def test_unreal_fills_the_defaults_its_schema_cannot_carry(unreal):
    engine_link.link_call("place", {"scene": "/Game/Mixar/Crate", "position": [1.0, 2.0, 0.0]})
    sent = _FakeUnreal.calls[-1][1]["arguments"]
    # The plugin's published defaults fill what the call left out; the call's own values win.
    assert sent == {"name": "", "position": [1.0, 2.0, 0.0], "animation": "", "scene": "/Game/Mixar/Crate"}
    engine_link.link_call("status", {})
    assert _FakeUnreal.calls[-1][1]["arguments"] == {}


def test_unreal_sends_free_shaped_arguments_as_one_json_string(unreal):
    # Unreal's tool schema cannot type "any JSON"; the plugin lists those arguments.
    steps = [{"wait": 1}, {"walk_to": [1.0, 2.0, 0.0]}]
    engine_link.link_call("playtest", {"steps": steps})
    sent = _FakeUnreal.calls[-1][1]["arguments"]
    assert sent == {"steps": json.dumps(steps)}
    engine_link.link_call("set_property", {"node": "Door", "property": "label", "value": "Gate"})
    sent = _FakeUnreal.calls[-1][1]["arguments"]
    assert sent == {"node": "Door", "property": "label", "value": json.dumps("Gate")}


def _backend_script(fn, kwargs):
    # modules/agent/tools/domains/engine.py:_link, verbatim in shape.
    encoded = json.dumps(kwargs)
    return ("import json\n"
            f"from mixar.modules.space_mixie_chat.core.engine_link import {fn}\n"
            f"result = {{'engine_link': {fn}(**json.loads({encoded!r}))}}\n"
            "print('\\n__RESULT__' + json.dumps(result))\n")


def test_an_engine_script_is_recognised_and_others_are_not():
    from mixar.modules.space_mixie_chat.core import engine_prefetch as ep
    kwargs = {"tool": "playtest", "arguments": {"steps": [{"wait": 1}]}, "timeout": 300.0}
    assert ep.parse(_backend_script("link_call", kwargs)) == ("link_call", kwargs)
    assert ep.parse(_backend_script("link_status", {})) == ("link_status", {})
    assert ep.parse("import bpy\nprint(1)\n") is None
    assert ep.parse(_backend_script("adapters", {})) is None


def test_the_engine_call_runs_off_the_main_thread_and_the_script_takes_its_answer(unreal):
    from mixar.modules.space_mixie_chat.core import engine_prefetch as ep
    script = _backend_script("link_call", {"tool": "scene_tree", "arguments": {"max_nodes": 5}, "timeout": 30.0})
    handle = ep.maybe_start(script)
    deadline = time.time() + 10
    while handle.state() != "ready" and time.time() < deadline:
        time.sleep(0.02)
    assert handle.state() == "ready"
    calls = len(_FakeUnreal.calls)
    scope = {}
    exec(compile(script.replace("print(", "_ = ("), "<engine script>", "exec"), scope)
    # The script took the stored answer: no second call reached the engine.
    assert len(_FakeUnreal.calls) == calls
    assert scope["result"]["engine_link"]["error"] == "No level is open."


def test_an_engine_call_past_its_time_answers_with_a_timeout(unreal, monkeypatch):
    from mixar.modules.space_mixie_chat.core import engine_prefetch as ep
    gate = threading.Event()
    monkeypatch.setattr(engine_link.link_status, "__wrapped__", lambda **kw: gate.wait(5) or {"success": True})
    monkeypatch.setattr(ep, "HEADROOM_S", 0.0)
    script = _backend_script("link_status", {})
    handle = ep.EngineCallPrefetch("link_status", {"timeout": 0.05})
    time.sleep(0.1)
    assert handle.state() == "ready"
    answer = engine_link.take_prefetched(handle.key)
    assert answer["success"] is False and "did not answer in time" in answer["error"]
    gate.set()
    time.sleep(0.1)
    assert engine_link.take_prefetched(handle.key) is None  # the late answer is not stored twice
    assert ep.parse(script) == ("link_status", {})
