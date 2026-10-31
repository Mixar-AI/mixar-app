# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The desktop end of the game-engine link (the agent's ``engine_*`` tools).

A game engine on this machine runs a Mixar Link add-on that writes a discovery
file, ``~/.mixar/engine-link/<engine>-<pid>.json`` (``port``, ``token``,
``started_at``, …), and removes it when the editor closes:

- Godot 4.5+ (``mixar-engine-godot``): the add-on is its own MCP server on
  127.0.0.1, bearer ``token``, tools by name.
- Unreal 5.8+ (``mixar-engine-unreal``): the editor's own MCP server
  (``transport: "unreal_mcp"``, no token, loopback only) holds Mixar Link's
  ``toolset``; a tool is reached through Unreal's ``call_tool`` and answers a
  JSON string (``UnrealMcpClient`` turns it into Godot's result shape).

This module finds the newest live one, speaks MCP to it (Streamable HTTP,
``initialize`` → ``Mcp-Session-Id``, one re-initialize on a 404 session), and
returns JSON-safe dicts for the backend.

An agent's engine call reaches here as a script on Blender's main thread. The
engine can take minutes (a playtest, an import), so ``engine_prefetch`` makes
the call on a worker thread as the script arrives and the script, once it
runs, takes the stored answer (``_prefetchable``): Mixar's UI and every other
scene tab's scripts never wait on the engine.

Privacy: the backend never sends or receives a local path. ``link_import``
resolves a package from a destination KIND and a folder NAME (the
``export_asset`` result's ``destination`` / ``folder``) and hands the absolute
folder to the engine on this machine only; ``import_package`` is not reachable
through ``link_call``. Every string coming back is scrubbed of absolute paths.
"""

from __future__ import annotations

import functools
import glob
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

LINK_DIR = os.path.join(os.path.expanduser("~"), ".mixar", "engine-link")
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "mixar-desktop", "version": "1"}
# Tools the backend may call by name. ``import_package`` takes a local path,
# so it is reached only through ``link_import``.
CALLABLE_TOOLS = ("status", "new_scene", "open_scene", "place", "scene_tree", "save_scene",
                  "play", "stop", "capture", "log", "playtest", "write_script", "add_node",
                  "set_property", "remove_node", "read_file", "list_files", "write_file",
                  "delete_file", "project_setting", "build_web", "build_info", "blueprint")
NO_ENGINE = ("No game engine is connected. Connect one from the engine chip in the chat composer "
             "(Godot 4.5+ or Unreal Engine 5.8+ with Mixar Link), then try again.")
UNREAL_TRANSPORT = "unreal_mcp"

# Absolute local paths in what an engine answers (``scrub``). A path starts at
# a drive (any letter, either separator), a UNC share, ``~/``, a ``file://``
# URL, a POSIX system root, or any lower-case first folder (a Linux mount):
# never at a URL scheme (``res://``, ``https://``) or Unreal's capitalised
# package roots (``/Game/…``, ``/Script/…``), which name things in the
# project, not on the disk. Folders may hold spaces when a separator follows
# (``C:\Users\John Smith\…``); the last name takes spaced words only up to
# a file extension. A quoted path is scrubbed to its closing quote.
_POSIX_ROOTS = ("Users|Volumes|Applications|Library|System|Network|private|home|root|tmp|var|mnt|media|"
                "opt|srv|etc|usr|run|data|workspace|snap|proc|dev|sys|boot|nix|cygdrive")
_NOT_AFTER = r"(?<![\w:/.~\\+=-])"
_ROOT = (r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]"
         r"|(?<![\w\\])\\\\[^\s\\/\"'`<>|]+[\\/]"
         r"|(?<![\w~])~[\\/]"
         r"|(?<![\w])[Ff][Ii][Ll][Ee]:/{2,}"
         rf"|{_NOT_AFTER}/(?:{_POSIX_ROOTS})(?=[\\/\s\"'`)\],;]|$)"
         rf"|{_NOT_AFTER}/[a-z][\w.-]*(?=/))")
_SEP = r"[\\/]+"
_NAME = r"[^\s\\/\"'`<>|*?]+"
_ABS_PATH = re.compile(_ROOT + rf"(?:{_SEP}|{_NAME}(?: {_NAME})*{_SEP})*"
                       rf"(?:{_NAME}(?: {_NAME}){{0,3}}?\.[A-Za-z0-9]{{1,8}}(?!\w)|{_NAME})?")
_QUOTED_PATH = re.compile(r"([\"'`])(" + _ROOT + r"[^\r\n]*?)\1")
_clients: dict = {}
# Answers made on a worker thread (engine_prefetch), by call key, oldest first.
_prefetched: dict = {}
_prefetch_lock = threading.Lock()
PREFETCH_KEEP_S = 1800.0


class LinkError(RuntimeError):
    """A link failure the user can act on; its text is safe to show."""


def scrub(value):
    """``value`` with every absolute local path replaced (recursively, keys
    included)."""
    if isinstance(value, str):
        value = _QUOTED_PATH.sub(lambda m: f"{m.group(1)}<local path>{m.group(1)}", value)
        return _ABS_PATH.sub("<local path>", value)
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {scrub(k) if isinstance(k, str) else k: scrub(v) for k, v in value.items()}
    return value


def _alive(pid) -> bool:
    """False only when ``pid`` is known to be gone (a killed editor's file)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    if pid <= 0 or sys.platform == "win32":  # Windows' os.kill(pid, 0) TERMINATES the process
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:  # no permission, or a platform without signal 0: assume alive
        return True
    return True


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
        if os.path.basename(path) == SELECTION_FILE:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                info = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(info, dict) or not info.get("port"):
            continue
        # Godot's own server needs its token; Unreal's server has none.
        if not info.get("token") and info.get("transport") != UNREAL_TRANSPORT:
            continue
        if engine and info.get("engine") != engine:
            continue
        if not _alive(info.get("pid")) or not _listening(info["port"]):
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
    def __init__(self, port: int, token: str, path: str = "/mcp"):
        self.url = f"http://127.0.0.1:{int(port)}/{str(path or '/mcp').lstrip('/')}"
        self.token = token
        self.session = ""
        self._id = 0

    def _post(self, payload: dict, timeout: float):
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        if self.token:
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


class UnrealMcpClient(McpClient):
    """Mixar Link's tools inside Unreal's MCP server: every call goes through
    the server's ``call_tool`` with the plugin's ``toolset``, and the tool's
    JSON-string answer (``{"ok", "data"|"error"}`` under ``returnValue``)
    comes back as Godot's CallToolResult shape."""

    def __init__(self, port: int, path: str, toolset: str, defaults: dict | None = None,
                 json_args: dict | None = None):
        super().__init__(port, "", path)
        self.toolset = toolset
        # Defaults Unreal's schema cannot carry (strings, lists), published by
        # the plugin in its discovery file; a call's own arguments win.
        self.defaults = defaults if isinstance(defaults, dict) else {}
        # Arguments of any JSON shape (playtest steps, a property value), which
        # the plugin takes as one JSON-encoded string.
        self.json_args = json_args if isinstance(json_args, dict) else {}

    def call(self, name: str, arguments: dict, timeout: float) -> dict:
        filled = self.defaults.get(name)
        arguments = {**(filled if isinstance(filled, dict) else {}), **arguments}
        for key in self.json_args.get(name) or ():
            if key in arguments:
                arguments[key] = json.dumps(arguments[key])
        raw = super().call("call_tool", {"toolset_name": self.toolset, "tool_name": name,
                                         "arguments": arguments}, timeout)
        return unreal_result(raw)


def unreal_result(raw: dict) -> dict:
    content = raw.get("content") if isinstance(raw.get("content"), list) else []
    text = next((c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"), "")
    if raw.get("isError"):  # the server's own refusal (unknown tool, bad arguments, an exception)
        return {"isError": True, "content": [{"type": "text", "text": text or "the engine reported an error"}]}
    try:
        value = json.loads(text).get("returnValue")
        reply = json.loads(value) if isinstance(value, str) else value
    except (ValueError, AttributeError):
        reply = None
    if not isinstance(reply, dict) or "ok" not in reply:
        return {"isError": True, "content": [{"type": "text", "text": "Mixar Link sent an unreadable reply."}]}
    data = reply.get("data") if isinstance(reply.get("data"), dict) else {}
    if not reply["ok"]:
        data = {**data, "error": str(reply.get("error") or "the engine reported an error")}
    out = {"structuredContent": data, "isError": not reply["ok"]}
    image = data.pop("image_base64", None) if reply["ok"] else None
    if image:
        out["content"] = [{"type": "image", "data": image, "mimeType": data.pop("image_mime", "image/png")}]
    return out


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


SELECTION_FILE = "selected.json"


def selected_id() -> str:
    """The editor the user picked in the composer's engine chip ("godot-<pid>"),
    or "" for the newest live one."""
    try:
        with open(os.path.join(LINK_DIR, SELECTION_FILE), encoding="utf-8") as fh:
            return str(json.load(fh).get("id") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def select(adapter_id: str) -> None:
    os.makedirs(LINK_DIR, exist_ok=True)
    with open(os.path.join(LINK_DIR, SELECTION_FILE), "w", encoding="utf-8") as fh:
        json.dump({"id": adapter_id}, fh)


def choose(found: list) -> dict:
    """The picked editor when it is still live, else the newest."""
    picked = selected_id()
    return next((i for i in found if public(i)["id"] == picked), found[0])


def _connect(engine: str | None):
    found = adapters(engine)
    if not found:
        raise LinkError(NO_ENGINE)
    info = choose(found)
    key = (info["_path"], info.get("token"), int(info["port"]), info.get("started_at"))
    client = _clients.get(key)
    if client is None:
        _clients.clear()
        if info.get("transport") == UNREAL_TRANSPORT:
            client = UnrealMcpClient(info["port"], info.get("path") or "/mcp", str(info.get("toolset") or ""),
                                     info.get("defaults"), info.get("json_args"))
        else:
            client = McpClient(info["port"], info["token"])
        _clients[key] = client
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

def call_key(fn: str, kwargs: dict) -> str:
    return f"{fn}:{json.dumps(kwargs, sort_keys=True, default=str)}"


def store_prefetched(key: str, result: dict) -> None:
    now = time.monotonic()
    with _prefetch_lock:
        for k in [k for k, v in _prefetched.items() if v and now - v[0][0] > PREFETCH_KEEP_S]:
            del _prefetched[k]
        _prefetched.setdefault(key, []).append((now, result))


def take_prefetched(key: str):
    with _prefetch_lock:
        queue = _prefetched.get(key)
        if not queue:
            return None
        _, result = queue.pop(0)
        if not queue:
            del _prefetched[key]
        return result


def _prefetchable(fn):
    """The answer engine_prefetch already made for this exact call, else the
    call itself. ``fn.__wrapped__`` is the call alone."""
    @functools.wraps(fn)
    def call(*args, **kwargs):
        if not args:
            found = take_prefetched(call_key(fn.__name__, kwargs))
            if found is not None:
                return found
        return fn(*args, **kwargs)
    return call


@_prefetchable
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


@_prefetchable
def link_call(tool: str, arguments: dict | None = None, engine: str | None = None,
              timeout: float = 60.0) -> dict:
    if tool not in CALLABLE_TOOLS:
        return {"success": False, "error": f"{tool!r} is not an engine tool Mixar calls by name."}
    try:
        _, client = _connect(engine)
        return _result(client.call(tool, dict(arguments or {}), float(timeout)))
    except LinkError as err:
        return _fail(err)


@_prefetchable
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
# The sizes the last build manifest declared, by file name (the upload URLs
# are signed for them).
_declared: dict = {}


def _build(engine: str | None):
    """(absolute build folder, files) — the folder stays on this machine."""
    _, client = _connect(engine)
    raw = client.call("build_info", {}, 10.0)
    if raw.get("isError"):
        raise LinkError(_result(raw).get("error") or "There is no web build.")
    data = raw.get("structuredContent") or {}
    return str(data.get("dir") or ""), [f for f in data.get("files") or [] if isinstance(f, dict)]


@_prefetchable
def link_build_manifest(engine: str | None = None) -> dict:
    """The last web build's files (name + bytes), no folder. ``bytes`` is
    each file's real size on disk now, not the engine's figure: the backend
    signs each upload URL for exactly that length."""
    try:
        folder, files = _build(engine)
    except LinkError as err:
        return _fail(err)
    out = []
    for f in files:
        name = os.path.basename(str(f.get("name") or ""))
        try:
            size = os.path.getsize(os.path.join(folder, name))
        except OSError:
            return {"success": False, "error": f"{name} is missing from the web build; build it again."}
        out.append({"name": name, "bytes": size})
    _declared.clear()
    _declared.update({f["name"]: f["bytes"] for f in out})
    return {"success": True, "files": out}


@_prefetchable
def link_upload_build(uploads: list, engine: str | None = None) -> dict:
    """PUT each build file to its presigned URL (``[{name, url, headers}]``
    from the backend). The build folder is read here, on this machine. Each
    PUT sends the whole file with its exact Content-Length (never chunked),
    because the URL is signed for the size the manifest declared; a file
    whose size changed since then is not sent."""
    try:
        folder, files = _build(engine)
    except LinkError as err:
        return _fail(err)
    present = {os.path.basename(str(f.get("name") or "")) for f in files}
    total = 0
    for up in uploads or []:
        name = os.path.basename(str(up.get("name") or ""))
        if name not in present:
            return {"success": False, "error": f"{name} is not in the web build; build it again."}
        try:
            with open(os.path.join(folder, name), "rb") as fh:
                body = fh.read()
        except OSError:
            return {"success": False, "error": f"{name} could not be read; build it again."}
        if name in _declared and len(body) != _declared[name]:
            return {"success": False, "error": f"{name} changed since the share started; share it again."}
        req = urllib.request.Request(str(up.get("url")), data=body, method="PUT")
        for k, v in (up.get("headers") or {}).items():
            if str(k).lower() not in ("content-length", "transfer-encoding"):
                req.add_header(k, v)
        req.add_header("Content-Length", str(len(body)))
        try:
            with urllib.request.urlopen(req, timeout=UPLOAD_TIMEOUT_S) as resp:
                if resp.status not in (200, 201, 204):
                    return {"success": False, "error": f"Uploading {name} failed (HTTP {resp.status})."}
        except urllib.error.HTTPError as err:
            return {"success": False, "error": f"Uploading {name} failed (HTTP {err.code})."}
        except (urllib.error.URLError, OSError) as err:
            return {"success": False, "error": f"Uploading {name} failed ({type(err).__name__})."}
        total += len(body)
    return {"success": True, "uploaded": len(uploads or []), "bytes": total}
