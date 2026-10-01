# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in semantic QA tools for an explicitly identified developer QA desktop.

Standalone standard-library module: the stdio launcher loads this by file path.
Only reviewed harness commands are constructed; neither command names nor
filesystem paths come from model arguments.
"""

import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import threading
import uuid

MAX_REPLY = 1024 * 1024
MAX_IMAGE = 4 * 1024 * 1024
MAX_RECEIPTS = 1024
_QUERY_TEXT = {name: {"type": "string", "maxLength": limit} for name, limit in (
    ("text", 1024), ("op", 128), ("prop", 128), ("prop_owner", 256), ("panel", 128),
    ("area_type", 64), ("region_type", 64), ("but_type", 64), ("surface", 128),
    ("value", 1024), ("detail", 1024))}
_QUERY_PROPERTIES = {**_QUERY_TEXT,
                     **{key: {"type": "boolean"} for key in ("contains", "popup", "enabled")},
                     "window": {"type": "integer", "minimum": 1, "maximum": 2**64 - 1},
                     "index": {"type": "integer", "minimum": 0, "maximum": 1000000}}
_QUERY = {"type": "object", "properties": _QUERY_PROPERTIES, "additionalProperties": False}
_TARGET = {**_QUERY, "minProperties": 1}
_BOOL = {"type": "boolean"}
_TEXT = {"type": "string", "maxLength": 8192}
_KEYS = ["RET", "ESC", "TAB", "BACK_SPACE", "DEL", "SPACE", "LEFT_ARROW", "RIGHT_ARROW",
         "UP_ARROW", "DOWN_ARROW", "HOME", "END", "PAGE_UP", "PAGE_DOWN", "INSERT",
         "WHEELUPMOUSE", "WHEELDOWNMOUSE", "NUMPAD_ENTER", "NUMPAD_PLUS", "NUMPAD_MINUS",
         "NUMPAD_PERIOD", "NUMPAD_SLASH", "NUMPAD_ASTERIX"]
_KEYS += list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + ["F%d" % i for i in range(1, 13)]
_KEYS += ["NUMPAD_%d" % i for i in range(10)]
_KEYS += ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE"]


def _schema(properties=None, required=()):
    return {"type": "object", "properties": properties or {},
            "required": list(required), "additionalProperties": False}


_SCHEMAS = {
    "status": _schema(),
    "find": _schema({"query": _QUERY, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}),
    "dump": _schema({"query": _QUERY, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}),
    "click": _schema({"target": _TARGET, "double": _BOOL}, ("target",)),
    "choose": _schema({"target": _TARGET, "item": {"type": "string", "minLength": 1, "maxLength": 1024},
                       "contains": _BOOL}, ("target", "item")),
    "set_text": _schema({"target": _TARGET, "text": _TEXT, "enter": _BOOL}, ("target", "text")),
    "type": _schema({"text": _TEXT, "window": _QUERY_PROPERTIES["window"]}, ("text",)),
    "press": _schema({"key": {"type": "string", "enum": _KEYS},
                      **{key: _BOOL for key in ("ctrl", "shift", "alt", "oskey")},
                      "window": _QUERY_PROPERTIES["window"]}, ("key",)),
    "drag": _schema({"from": _TARGET, "to": _TARGET,
                     "steps": {"type": "integer", "minimum": 1, "maximum": 60},
                     "shift": _BOOL, "button": {"type": "string", "enum": ["LEFTMOUSE", "MIDDLEMOUSE"]}},
                    ("from", "to")),
    "snap": _schema({"area": {"type": "string", "minLength": 1, "maxLength": 64},
                     "target": _TARGET, "annotate": _QUERY,
                     "margin": {"type": "integer", "minimum": 0, "maximum": 160}}),
}
_READ_ONLY = frozenset({"status", "find", "dump", "snap"})
_DESCRIPTIONS = {
    "status": "Read QA desktop login, agent state, busy flag and scene object count.",
    "find": "Find visible UI controls by their semantic labels, operator IDs, properties or surfaces.",
    "dump": "Inspect the bounded semantic UI map; query can restrict an area or popup.",
    "click": "Click the one matching semantic UI target. Inspect its enabled/selected state first.",
    "choose": "Open the target dropdown and choose an item by its visible label.",
    "set_text": "Replace text in one semantic UI field; Enter commits by default.",
    "type": "Type into the focused QA control after clicking it.",
    "press": "Press one named keyboard key with optional modifiers in the QA desktop.",
    "drag": "Drag between two semantic UI targets; both must resolve in one window.",
    "snap": "View a PNG screenshot of the QA desktop, area, or target, optionally annotated. No file path argument.",
}


def _validate(value, schema, name="arguments"):
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict) or set(value) - set(schema["properties"]):
            raise ValueError(name + " contains unsupported fields")
        if set(schema.get("required", ())) - set(value) or len(value) < schema.get("minProperties", 0):
            raise ValueError(name + " is missing required fields")
        for key, item in value.items():
            _validate(item, schema["properties"][key], name + "." + key)
    elif kind == "boolean":
        if type(value) is not bool:
            raise ValueError(name + " must be a boolean")
    elif kind == "integer":
        if type(value) is not int or not schema["minimum"] <= value <= schema["maximum"]:
            raise ValueError(name + " must be an integer within its advertised bounds")
    elif kind == "string":
        if not isinstance(value, str) or not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 128):
            raise ValueError(name + " must be text within its advertised bounds")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(name + " must be one of the advertised values")
        if "\x00" in value:
            raise ValueError(name + " cannot contain NUL")


def _without_paths(value):
    if isinstance(value, dict):
        return {key: _without_paths(item) for key, item in value.items()
                if key not in {"path", "filepath", "directory", "traceback"}}
    if isinstance(value, list):
        return [_without_paths(item) for item in value]
    return value


class QAAdapter:
    def __init__(self, port, health):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("QA port must be an integer from 1 to 65535")
        self.port = port
        self.health = health
        self._lock = threading.Lock()
        self._receipts = {}

    @staticmethod
    def handles(name):
        return isinstance(name, str) and name in {"mixar_qa_" + command for command in _SCHEMAS}

    def _check_health(self):
        state = self.health()
        if not isinstance(state, dict) or state.get("qa_enabled") is not True or state.get("qa_port") != self.port:
            raise ValueError("QA tools require the selected Mixar desktop to advertise this developer QA port")

    def tools(self):
        self._check_health()
        return [{"name": "mixar_qa_" + command,
                 "description": description + " Developer QA only. Invocation costs 0 credits; UI-triggered generation retains normal pricing.",
                 "inputSchema": deepcopy(_SCHEMAS[command]),
                 "annotations": {"readOnlyHint": command in _READ_ONLY, "destructiveHint": command not in _READ_ONLY,
                                 "idempotentHint": command in _READ_ONLY, "openWorldHint": command not in _READ_ONLY},
                 "_meta": {"mixar/billing": {"invocation_credits": 0, "surface": "developer_qa"}}}
                for command, description in _DESCRIPTIONS.items()]

    def _send(self, command, arguments):
        # Commands reach this function only through the reviewed map below.
        request = {"cmd": command, "args": arguments}
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as connection:
            connection.settimeout(30)
            with connection.makefile("rwb") as stream:
                stream.write(json.dumps(request).encode("utf-8") + b"\n")
                stream.flush()
                raw = stream.readline(MAX_REPLY + 1)
        if not raw or len(raw) > MAX_REPLY or not raw.endswith(b"\n"):
            raise ValueError("QA server returned an invalid or oversized response")
        response = json.loads(raw)
        if not isinstance(response, dict) or type(response.get("ok")) is not bool:
            raise ValueError("QA server returned an invalid response")
        return response

    def _run(self, command, arguments):
        args = dict(arguments)
        if command in {"find", "dump"}:
            args = {**args.get("query", {}), "limit": args.get("limit", 50)}
        elif command == "click":
            args = {**args["target"], "double": args.get("double", False)}
        elif command in {"choose", "set_text"}:
            args["widget"] = args.pop("target")
        if command != "snap":
            return self._send(command, args), None
        with tempfile.TemporaryDirectory(prefix="mixar-mcp-qa-") as temporary:
            path = Path(temporary) / "capture.png"
            response = self._send("snap", {**args, "path": str(path)})
            if not response.get("ok"):
                return response, None
            # Ignore every path returned by the server. Read only the file this
            # process requested in its own private temporary directory.
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_IMAGE:
                raise ValueError("Screenshot is unavailable or too large; request an area or target crop")
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "rb") as stream:
                raw = stream.read(MAX_IMAGE + 1)
            if not raw.startswith(b"\x89PNG\r\n\x1a\n") or len(raw) > MAX_IMAGE:
                raise ValueError("QA server did not create a bounded PNG screenshot")
            return response, {"type": "image", "data": base64.b64encode(raw).decode("ascii"), "mimeType": "image/png"}

    def call(self, name, arguments, request_id):
        request_id = str(uuid.UUID(str(request_id)))
        if not self.handles(name):
            raise ValueError("Unknown semantic QA tool")
        command = name.removeprefix("mixar_qa_")
        _validate(arguments, _SCHEMAS[command])
        digest = hashlib.sha256(json.dumps([name, arguments], sort_keys=True).encode()).hexdigest()
        with self._lock:
            self._check_health()
            # A local UI action has no backend receipt. Preserve its identity for
            # this launcher session, including an uncertain transport outcome.
            if command not in _READ_ONLY and request_id in self._receipts:
                prior_digest, response = self._receipts[request_id]
                if prior_digest != digest:
                    raise ValueError("A QA call ID cannot be reused for different arguments")
                replay = deepcopy(response)
                replay["structuredContent"]["usage"]["replayed"] = True
                replay["content"].insert(0, {"type": "text", "text": "This QA action was already accepted in this launcher session. It was not executed again; no invocation credits were charged."})
                return replay
            if command not in _READ_ONLY and len(self._receipts) >= MAX_RECEIPTS:
                raise ValueError("The QA session receipt limit was reached; start a new QA session")
            image = None
            try:
                response, image = self._run(command, arguments)
                result = _without_paths(response.get("result")) if response["ok"] else {
                    "error": "The semantic QA action was refused. Inspect the current UI targets and state."}
                failed = not response["ok"]
            except (OSError, ValueError, TypeError, KeyError):
                result = {"error": "QA action outcome is unavailable. Inspect status and a screenshot before another action; no automatic retry occurred."}
                failed = True
            usage = {"request_id": request_id, "credits_charged": 0, "surface": "developer_qa",
                     "status": "failed" if failed else "succeeded", "replay_scope": "launcher_session",
                     "note": "UI-triggered generation retains its normal generation credits."}
            blocks = [{"type": "text", "text": json.dumps({"result": result, "usage": usage}, ensure_ascii=False)}]
            if image:
                blocks.append(image)
            out = {"content": blocks, "structuredContent": {"result": result, "usage": usage},
                   "isError": failed, "_meta": {"mixar/usage": usage, "mixar/request-id": request_id}}
            if command not in _READ_ONLY:
                self._receipts[request_id] = (digest, deepcopy(out))
            return out
