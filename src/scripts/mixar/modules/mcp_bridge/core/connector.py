# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Local transport discovery/recovery. Never retries a submitted mutation."""

import http.client
import json
import threading
import uuid

from . import discovery

MAX_BODY = 8 * 1024 * 1024
#: Tools the desktop serves itself through /ui (never the backend).
LOCAL_PREFIXES = ("mixar_ui_", "mixar_scene", "mixar_project")
REBINDS = {"mixar_scene_new", "mixar_scene_switch", "mixar_project_open"}
REPORTS_BINDING = {"mixar_ui_context", "mixar_scenes", *REBINDS}


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
        self.health = {}

    def attach(self):
        with self.lock:
            if self.record is not None:
                try:
                    health = request(self.record, "GET", "/health", timeout=1)
                    if health["instance_id"] == self.record["instance_id"]:
                        self.health = health
                        return dict(self.record), health
                    raise ValueError("Desktop identity changed")
                except (OSError, ValueError, KeyError, RuntimeError, http.client.HTTPException):
                    self.record = None
                    self.upstream_version = None
            live = instances()
            candidates = [(r, h) for r, h in live if not self.instance or r["instance_id"] == self.instance]
            if not candidates and self.instance and live:
                # The bound app closed. Reopening the same saved file restores the
                # scene's session id, so that scene is safe to follow; any other
                # open app is chosen explicitly through mixar_ui_context.
                candidates = [found for found in [self._holding_scene(live)] if found]
                if not candidates:
                    raise RuntimeError(self._closed_message(live))
            if len(candidates) != 1:
                if not candidates and not self.started:
                    self.started = True
                    from .installation import start_app
                    start_app()
                raise RuntimeError("Mixar is starting or unavailable" if not candidates else
                                   "Several Mixar applications are open; select an instance through mixar_ui_context")
            self.record, health = candidates[0]
            # Once bound, losing the process must not select another open project.
            self.instance = self.record["instance_id"]
            if self.bound_session is None:
                self.bound_session = self.session or health.get("session_id", "")
            # A successfully attached app closing later must not be resurrected.
            self.started = True
            self.health = health
            return dict(self.record), health

    def _sessions(self, record):
        """Session ids of the scene tabs an app has open (empty if it cannot say)."""
        message = {"jsonrpc": "2.0", "id": "rebind", "method": "tools/call",
                   "params": {"name": "mixar_scenes", "arguments": {}}}
        try:
            response = request(record, "POST", "/ui", message, {"X-Mixar-Controller-Id": self.owner}, timeout=5)
            return {scene.get("session") for scene in response["result"]["structuredContent"]["result"]["scenes"]}
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, http.client.HTTPException):
            return set()

    def _holding_scene(self, live):
        """The one open app that has this connection's scene (the same saved file reopened)."""
        if not self.bound_session:
            return None
        holding = [(record, health) for record, health in live
                   if health.get("session_id") == self.bound_session or self.bound_session in self._sessions(record)]
        return holding[0] if len(holding) == 1 else None

    def _closed_message(self, live):
        apps = "; ".join("instance %s showing scene %r" % (record["instance_id"], health.get("scene_name", ""))
                         for record, health in live)
        return ("The Mixar app this connection used was closed, and its scene is not open in the running app "
                "(it may not have been saved). Open now: " + apps + ". To continue there, call "
                "mixar_ui_context with that instance, then mixar_scenes to pick a scene tab or "
                "mixar_scene_new; inspect the scene before editing.")

    def call(self, name, arguments, call_id):
        record, health = self.attach()
        local = name.startswith(LOCAL_PREFIXES)
        unpinned = name == "mixar_ui_context" or name.startswith(("mixar_scene", "mixar_project"))
        headers = {"X-Mixar-Controller-Id": self.owner,
                   "X-Mixar-Session-Id": "" if unpinned else self.bound_session or "",
                   "X-Mixar-Call-Id": call_id}
        if not local and self.upstream_version:
            headers["MCP-Protocol-Version"] = self.upstream_version
        # The connection's own input lease is released before anything that
        # edits or replaces the scene: backend tools and the scene-tab/project
        # tools alike (an agent that just pressed Cmd+S may open a project next).
        if (not local or name.startswith(("mixar_scene", "mixar_project"))) and health.get("ui_contract"):
            # Releasing input concerns this controller, not a scene: a stale scene
            # pin (another document was opened) must reach the backend's own
            # document_changed answer instead of failing here.
            released = request(record, "POST", "/ui", {"jsonrpc": "2.0", "id": "release",
                "method": "tools/call", "params": {"name": "mixar_ui_context", "arguments": {"release": True}}},
                {**headers, "X-Mixar-Session-Id": ""}, timeout=12)
            if released.get("result", {}).get("isError"):
                raise RuntimeError("Finish or cancel the UI modal before using scene tools")
        message = {"jsonrpc": "2.0", "id": call_id, "method": "tools/call", "params": {
            "name": name, "arguments": arguments, "_meta": {"mixar/request-id": call_id}}}
        # Only transport discovery retries. This request is deliberately attempted ONCE.
        response = request(record, "POST", "/ui" if local else "/mcp", message, headers, timeout=600 if not local else 35)
        if "result" not in response:
            raise RuntimeError("Mixar rejected the tool call; recover using its call ID")
        if not response["result"].get("isError") and name in REPORTS_BINDING:
            payload = response["result"]["structuredContent"]
            result = payload["result"]
            if name in REBINDS and result.get("session"):
                # A created or switched scene becomes this connection's target:
                # backend scene tools and UI actions follow it from now on.
                self.bound_session = result["session"]
            if name == "mixar_scenes":
                for scene in result.get("scenes", []):
                    scene["bound"] = scene.get("session") == self.bound_session
            result["bound_session"] = self.bound_session
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
