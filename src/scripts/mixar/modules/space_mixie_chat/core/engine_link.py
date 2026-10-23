# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The desktop end of the game-engine link (the agent's ``engine_*`` tools).

A game engine on this machine runs a Mixar Link add-on (``mixar-engine-godot``
for Godot 4.5+): a small MCP server on 127.0.0.1 that writes a discovery file,
``~/.mixar/engine-link/<engine>-<pid>.json`` (``port``, ``token``,
``started_at``, …), and removes it when the editor closes. This module finds
the newest live one, speaks MCP to it (Streamable HTTP, ``initialize`` →
``Mcp-Session-Id``, one re-initialize on a 404 session), and returns JSON-safe
dicts for the backend.

Privacy: the backend never sends or receives a local path. ``link_import``
resolves a package from a destination KIND and a folder NAME (the
``export_asset`` result's ``destination`` / ``folder``) and hands the absolute
folder to the engine on this machine only; ``import_package`` is not reachable
through ``link_call``. Every string coming back is scrubbed of absolute paths.
"""

from __future__ import annotations

import glob
import json
import os
import re
import socket
import urllib.error
import urllib.request

LINK_DIR = os.path.join(os.path.expanduser("~"), ".mixar", "engine-link")
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "mixar-desktop", "version": "1"}
# Tools the backend may call by name. ``import_package`` takes a local path,
# so it is reached only through ``link_import``.
CALLABLE_TOOLS = ("status", "new_scene", "open_scene", "place", "scene_tree", "save_scene",
                  "play", "stop", "capture", "log", "playtest", "write_script", "add_node",
                  "set_property", "build_web")
NO_ENGINE = ("No game engine is connected. Open the project in Godot 4.5+ with the Mixar Link "
             "add-on enabled (Project Settings > Plugins), then try again.")

_ABS_PATH = re.compile(r"(?:[A-Za-z]:\\|/(?:Users|home|private|var|tmp|Volumes|mnt)/)[^\s\"'<>|]*")
_clients: dict = {}


class LinkError(RuntimeError):
    """A link failure the user can act on; its text is safe to show."""


def scrub(value):
    """``value`` with every absolute local path replaced (recursively)."""
    if isinstance(value, str):
        return _ABS_PATH.sub("<local path>", value)
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    return value


def _listening(port) -> bool:
    try:
        socket.create_connection(("127.0.0.1", int(port)), timeout=0.3).close()
        return True
    except (OSError, TypeError, ValueError):
        return False


def adapters(engine: str | None = None) -> list:
    """Live adapters, newest first. A file whose port no longer answers (an
    editor that crashed without cleaning up) is skipped, never deleted."""
    found = []
    for path in glob.glob(os.path.join(LINK_DIR, "*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                info = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(info, dict) or not info.get("token") or not info.get("port"):
            continue
        if engine and info.get("engine") != engine:
            continue
        if not _listening(info["port"]):
            continue
        info["_path"] = path
        found.append(info)
    found.sort(key=lambda i: float(i.get("started_at") or 0), reverse=True)
    return found


def public(info: dict) -> dict:
    return {"id": f"{info.get('engine')}-{info.get('pid')}", "engine": info.get("engine"),
            "version": info.get("version"), "adapter_version": info.get("adapter_version"),
            "project_name": info.get("project_name")}


class McpClient:
    def __init__(self, port: int, token: str):
        self.url = f"http://127.0.0.1:{int(port)}/mcp"
        self.token = token
        self.session = ""
        self._id = 0

    def _post(self, payload: dict, timeout: float):
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("MCP-Protocol-Version", PROTOCOL_VERSION)
        if self.session:
            req.add_header("Mcp-Session-Id", self.session)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                headers = {k.lower(): v for k, v in resp.headers.items()}
                return resp.status, headers, _decode(resp.read(), headers.get("content-type", ""))
        except urllib.error.HTTPError as err:
            return err.code, {}, None
        except (urllib.error.URLError, OSError) as err:
            raise LinkError(f"The engine did not answer ({type(err).__name__}).") from None

    def _rpc(self, method: str, params: dict, timeout: float):
        self._id += 1
        return self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}, timeout)

    def initialize(self, timeout: float = 10.0) -> dict:
        self.session = ""
        status, headers, body = self._rpc("initialize", {"protocolVersion": PROTOCOL_VERSION,
                                                         "capabilities": {}, "clientInfo": CLIENT_INFO}, timeout)
        if status == 401:
            raise LinkError("The engine refused Mixar's token; restart the engine's editor.")
        if status != 200 or not isinstance(body, dict) or "result" not in body:
            raise LinkError(f"The engine did not accept the connection (HTTP {status}).")
        self.session = headers.get("mcp-session-id", "")
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout)
        return body["result"]

    def call(self, name: str, arguments: dict, timeout: float) -> dict:
        if not self.session:
            self.initialize()
        status, _, body = self._rpc("tools/call", {"name": name, "arguments": arguments}, timeout)
        if status == 404:  # the editor restarted its server: one fresh session
            self.initialize()
            status, _, body = self._rpc("tools/call", {"name": name, "arguments": arguments}, timeout)
        if status != 200 or not isinstance(body, dict):
            raise LinkError(f"The engine answered HTTP {status}.")
        if "error" in body:
            raise LinkError(f"The engine refused the call: {body['error'].get('message', 'unknown error')}")
        return body.get("result") or {}


def _decode(raw: bytes, content_type: str):
    if not raw:
        return None
    text = raw.decode("utf-8", "replace")
    if "text/event-stream" in content_type:  # the last JSON-RPC message in the stream
        data = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        text = data[-1] if data else ""
    try:
        return json.loads(text)
    except ValueError:
        return None


def _connect(engine: str | None):
    found = adapters(engine)
    if not found:
        raise LinkError(NO_ENGINE)
    info = found[0]
    key = (info["_path"], info["token"], int(info["port"]))
    client = _clients.get(key)
    if client is None:
        _clients.clear()
        client = _clients[key] = McpClient(info["port"], info["token"])
    return info, client


def _result(raw: dict) -> dict:
    """An MCP CallToolResult → ``{success, data, error?, image_base64?, image_mime?}``."""
    content = raw.get("content") if isinstance(raw.get("content"), list) else []
    texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
    images = [c for c in content if isinstance(c, dict) and c.get("type") == "image"]
    data = raw.get("structuredContent")
    if not isinstance(data, dict):
        try:
            data = json.loads(texts[0]) if texts else {}
        except ValueError:
            data = {}
        data = data if isinstance(data, dict) else {}
    out = {"success": not raw.get("isError"), "data": scrub(data)}
    if raw.get("isError"):
        out["error"] = scrub(data.get("error") or (texts[0] if texts else "the engine reported an error"))
    if images:
        out["image_base64"] = images[0].get("data", "")
        out["image_mime"] = images[0].get("mimeType", "image/jpeg")
    return out


def _fail(err: Exception) -> dict:
    return {"success": False, "error": scrub(str(err))}


# ---------------------------------------------------------------------------
# Called by the backend (agent scripts)
# ---------------------------------------------------------------------------

def link_status(engine: str | None = None) -> dict:
    """Every live adapter, and the chosen one's own ``status``."""
    found = adapters(engine)
    if not found:
        return {"success": False, "error": NO_ENGINE, "adapters": []}
    try:
        info, client = _connect(engine)
        out = _result(client.call("status", {}, 10.0))
    except LinkError as err:
        return {**_fail(err), "adapters": [public(i) for i in found]}
    out["adapters"] = [public(i) for i in found]
    out["connected"] = public(info)
    return out


def link_call(tool: str, arguments: dict | None = None, engine: str | None = None,
              timeout: float = 60.0) -> dict:
    if tool not in CALLABLE_TOOLS:
        return {"success": False, "error": f"{tool!r} is not an engine tool Mixar calls by name."}
    try:
        _, client = _connect(engine)
        return _result(client.call(tool, dict(arguments or {}), float(timeout)))
    except LinkError as err:
        return _fail(err)


def link_import(folder: str, destination: str = "mixar_exports", engine: str | None = None,
                timeout: float = 180.0) -> dict:
    """Import the ``export_asset`` package ``folder`` (at ``destination``)
    into the engine project as ``res://mixar/<folder>/``."""
    from . import export_package

    try:
        source = export_package.destination(destination, folder, create=False)
    except ValueError as err:
        return _fail(err)
    if not folder or not os.path.isfile(os.path.join(source, "manifest.json")):
        return {"success": False, "error": f"No Mixar package named {folder!r} in {destination}; "
                                           "export it with export_asset first."}
    try:
        _, client = _connect(engine)
        return _result(client.call("import_package",
                                   {"source_dir": source, "folder": os.path.basename(source)},
                                   float(timeout)))
    except LinkError as err:
        return _fail(err)


# ---------------------------------------------------------------------------
# Sharing a web build (the backend's engine_share)
# ---------------------------------------------------------------------------

UPLOAD_TIMEOUT_S = 300.0


def _build(engine: str | None):
    """(absolute build folder, files) — the folder stays on this machine."""
    _, client = _connect(engine)
    raw = client.call("build_info", {}, 10.0)
    if raw.get("isError"):
        raise LinkError(_result(raw).get("error") or "There is no web build.")
    data = raw.get("structuredContent") or {}
    return str(data.get("dir") or ""), [f for f in data.get("files") or [] if isinstance(f, dict)]


def link_build_manifest(engine: str | None = None) -> dict:
    """The last web build's files (name + bytes), no folder."""
    try:
        _, files = _build(engine)
    except LinkError as err:
        return _fail(err)
    return {"success": True, "files": [{"name": str(f.get("name")), "bytes": int(f.get("bytes") or 0)}
                                       for f in files]}


def link_upload_build(uploads: list, engine: str | None = None) -> dict:
    """PUT each build file to its presigned URL (``[{name, url, headers}]``
    from the backend). The build folder is read here, on this machine."""
    try:
        folder, files = _build(engine)
    except LinkError as err:
        return _fail(err)
    present = {str(f.get("name")) for f in files}
    total = 0
    for up in uploads or []:
        name = os.path.basename(str(up.get("name") or ""))
        if name not in present:
            return {"success": False, "error": f"{name} is not in the web build; build it again."}
        path = os.path.join(folder, name)
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            req = urllib.request.Request(str(up.get("url")), data=fh, method="PUT")
            for k, v in (up.get("headers") or {}).items():
                req.add_header(k, v)
            req.add_header("Content-Length", str(size))
            try:
                with urllib.request.urlopen(req, timeout=UPLOAD_TIMEOUT_S) as resp:
                    if resp.status not in (200, 201, 204):
                        return {"success": False, "error": f"Uploading {name} failed (HTTP {resp.status})."}
            except urllib.error.HTTPError as err:
                return {"success": False, "error": f"Uploading {name} failed (HTTP {err.code})."}
            except (urllib.error.URLError, OSError) as err:
                return {"success": False, "error": f"Uploading {name} failed ({type(err).__name__})."}
        total += size
    return {"success": True, "uploaded": len(uploads or []), "bytes": total}
