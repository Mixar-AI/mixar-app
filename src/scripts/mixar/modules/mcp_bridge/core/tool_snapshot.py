# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The backend's MCP tool list, saved while Mixar is signed in.

An AI app asks for tools once, when it connects, and can only call what that
list holds. Mixar's scene tools come from the backend, which needs a signed-in
app, so the app saves the list (on enabling MCP, on each sign-in and hourly) and
the launcher serves the saved copy whenever Mixar is closed, starting, signed
out or offline. Every tool is listed up front; a call made before Mixar is
ready says why (sign in, connecting, not open), as other desktop MCP servers do.
Tool definitions only: no account data. No Blender access here.
"""

import json
import threading
import time

from .installation import _atomic, directory

FILENAME = "tools.json"
REFRESH_SECONDS = 3600
RETRY_SECONDS = 15

_state = {"thread": None, "saved_at": 0.0, "account": None, "error": None}


def path():
    return directory() / FILENAME


def load():
    """The saved backend tool definitions, or None."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    tools = data.get("tools") if isinstance(data, dict) and data.get("version") == 1 else None
    if not isinstance(tools, list) or not all(isinstance(t, dict) and t.get("name") for t in tools):
        return None
    return tools or None


def save(tools):
    """Atomically replace the saved list; never fails its caller."""
    try:
        root = directory()
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _atomic(path(), json.dumps({"version": 1, "saved_at": int(time.time()), "tools": tools}))
        return True
    except (OSError, TypeError, ValueError):
        return False


def fetch(context, forward):
    """The backend tool list through the app's authenticated forwarder."""
    status, response = forward({"jsonrpc": "2.0", "id": "snapshot-init", "method": "initialize", "params": {
        "protocolVersion": "2025-11-25", "capabilities": {},
        "clientInfo": {"name": "mixar-tool-snapshot", "version": "1"}}}, context, {})
    if status != 200 or not isinstance(response, dict) or "result" not in response:
        _state["error"] = "initialize: HTTP %s %s" % (status, str(response)[:200])
        return None
    headers = {"MCP-Protocol-Version": response["result"]["protocolVersion"]}
    tools, cursor = [], None
    for _ in range(20):
        status, response = forward({"jsonrpc": "2.0", "id": "snapshot", "method": "tools/list",
                                    "params": {"cursor": cursor} if cursor else {}}, context, headers)
        if status != 200 or not isinstance(response, dict) or "result" not in response:
            _state["error"] = "tools/list: HTTP %s %s" % (status, str(response)[:200])
            return None
        tools.extend(response["result"].get("tools") or [])
        cursor = response["result"].get("nextCursor")
        if not cursor:
            return tools
    return None


def refresh_if_due(context, forward, *, now=None):
    """Called from the app's main-thread tick: save the list on a worker thread
    once Mixar is signed in and connected, again after a new sign-in, and hourly."""
    if not (context.get("signed_in") and context.get("connected") and context.get("backend_url")):
        return False
    now = time.monotonic() if now is None else now
    account = context.get("backend_url")
    worker = _state["thread"]
    if worker is not None and worker.is_alive():
        return False
    if _state["account"] == account and now - _state["saved_at"] < REFRESH_SECONDS:
        return False
    _state["account"], _state["saved_at"] = account, now

    def work():
        try:
            tools = fetch(dict(context), forward)
            if tools and save(tools):
                _state["error"] = None
                return
        except Exception as exc:  # noqa: BLE001 - a background refresh must never surface
            _state["error"] = repr(exc)[:200]
        _state["saved_at"] = time.monotonic() - REFRESH_SECONDS + RETRY_SECONDS

    _state["thread"] = threading.Thread(target=work, name="MixarToolSnapshot", daemon=True)
    _state["thread"].start()
    return True


def forget():
    """A sign-out or disabled MCP: the next sign-in saves a fresh list."""
    _state["account"], _state["saved_at"] = None, 0.0
