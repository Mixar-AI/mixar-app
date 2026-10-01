# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Local transport discovery/recovery. Never retries a submitted mutation."""

import http.client
import json
import threading
import uuid

from . import discovery

MAX_BODY = 8 * 1024 * 1024


def request(record, method, path, payload=None, headers=None, timeout=10):
    body = None if payload is None else json.dumps(payload, allow_nan=False).encode()
    if body and len(body) > MAX_BODY:
        raise ValueError("MCP request exceeds the local transport limit")
    conn = http.client.HTTPConnection("127.0.0.1", record["port"], timeout=timeout)
    try:
        conn.request(method, path, body=body, headers={
            "Authorization": "Bearer " + record["token"], "Content-Type": "application/json", **(headers or {})})
        response = conn.getresponse()
        raw = response.read(MAX_BODY+1)
        if len(raw) > MAX_BODY:
            raise ValueError("MCP response exceeds the local transport limit")
        if not 200 <= response.status < 300:
            raise RuntimeError("Mixar connector unavailable (HTTP %d)" % response.status)
        return json.loads(raw) if raw else None
    finally:
        conn.close()


def instances():
    found = []
    for path in discovery.discovery_directory().glob("*.json"):
        try:
            record = discovery.read_record(path)
            health = request(record, "GET", "/health", timeout=0.5)
            if health["instance_id"] == record["instance_id"]:
                found.append((record, health))
        except (OSError, ValueError, KeyError, RuntimeError, http.client.HTTPException):
            continue
    return found


class Connector:
    def __init__(self, instance=None, session=None):
        self.instance, self.session = instance, session
        self.bound_session = session
        self.owner = str(uuid.uuid4())
        self.record = None
        self.lock = threading.Lock()
        self.upstream_version = None
        self.started = False
        self.tasks = set()

    def attach(self):
        with self.lock:
            if self.record is not None:
                try:
                    health = request(self.record, "GET", "/health", timeout=1)
                    if health["instance_id"] == self.record["instance_id"]:
                        return dict(self.record), health
                    raise ValueError("Desktop identity changed")
                except (OSError, ValueError, KeyError, RuntimeError, http.client.HTTPException):
                    self.record = None
                    self.upstream_version = None
            candidates = [(r, h) for r, h in instances() if not self.instance or r["instance_id"] == self.instance]
            if len(candidates) != 1:
                if not candidates and not self.started:
                    self.started = True
                    from .installation import start_app
                    start_app()
                raise RuntimeError("Mixar is starting or unavailable" if not candidates else
                                   "Several Mixar applications are open; select an instance through mixar_ui_context")
            self.record, health = candidates[0]
            # Once bound, losing the process must not select another open project.
            # A replacement instance is selected explicitly through context.
            self.instance = self.record["instance_id"]
            if self.bound_session is None:
                self.bound_session = self.session or health.get("session_id", "")
            # A successfully attached app closing later must not be resurrected.
            self.started = True
            return dict(self.record), health

    def call(self, name, arguments, call_id):
        record, health = self.attach()
        local = name.startswith("mixar_ui_")
        headers = {"X-Mixar-Controller-Id": self.owner,
                   "X-Mixar-Session-Id": "" if name == "mixar_ui_context" else self.bound_session or "",
                   "X-Mixar-Call-Id": call_id}
        if not local and self.upstream_version:
            headers["MCP-Protocol-Version"] = self.upstream_version
        if not local and health.get("ui_contract"):
            released = request(record, "POST", "/ui", {"jsonrpc": "2.0", "id": "release",
                "method": "tools/call", "params": {"name": "mixar_ui_context", "arguments": {"release": True}}},
                headers, timeout=12)
            if released.get("result", {}).get("isError"):
                raise RuntimeError("Finish or cancel the UI modal before using scene tools")
        message = {"jsonrpc": "2.0", "id": call_id, "method": "tools/call", "params": {
            "name": name, "arguments": arguments, "_meta": {"mixar/request-id": call_id}}}
        # Only transport discovery retries. This request is deliberately attempted ONCE.
        response = request(record, "POST", "/ui" if local else "/mcp", message, headers, timeout=600 if not local else 35)
        if "result" not in response:
            raise RuntimeError("Mixar rejected the tool call; recover using its call ID")
        if name == "mixar_ui_context" and not response["result"].get("isError"):
            payload = response["result"]["structuredContent"]
            payload["result"]["bound_session"] = self.bound_session
            response["result"]["content"][0] = {"type": "text", "text": json.dumps(payload)}
        return response["result"]

    def catalog(self):
        record, _ = self.attach()
        with self.lock:
            if self.upstream_version is None:
                response = request(record, "POST", "/mcp", {
                    "jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {
                        "protocolVersion": "2025-11-25", "capabilities": {},
                        "clientInfo": {"name": "mixar-local-connector", "version": "1"}}})
                self.upstream_version = response["result"]["protocolVersion"]
        result, cursor = [], None
        for _ in range(20):
            response = request(record, "POST", "/mcp", {"jsonrpc": "2.0", "id": "catalog",
                "method": "tools/list", "params": {"cursor": cursor} if cursor else {}},
                {"MCP-Protocol-Version": self.upstream_version}, timeout=5)
            page = response["result"]
            result.extend(page["tools"])
            cursor = page.get("nextCursor")
            if not cursor:
                return result
        raise RuntimeError("Backend tool catalog exceeded pagination bounds")

    def cancel(self, call_id=None):
        if self.record is not None:
            try:
                request(self.record, "POST", "/ui/cancel", {"jsonrpc": "2.0", "method": "cancel",
                    "params": {"call_id": call_id}}, {"X-Mixar-Controller-Id": self.owner}, timeout=2)
            except (OSError, ValueError, RuntimeError, http.client.HTTPException):
                pass  # Native lease expiry remains the final fence.
