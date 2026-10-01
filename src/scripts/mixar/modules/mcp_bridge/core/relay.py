# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Authenticated, bounded loopback relay; socket threads never access bpy."""

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
import uuid

from .discovery import publish

MAX_BODY = 8 * 1024 * 1024


class RelayServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, snapshot, forward):
        self.token = secrets.token_urlsafe(32)
        self.snapshot = snapshot
        self.forward = forward
        self.slots = threading.BoundedSemaphore(8)
        self.stopping = threading.Event()
        self.record = None
        super().__init__(("127.0.0.1", 0), RelayHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def start(self):
        self.record = publish(self.server_port, self.token, self.snapshot()["instance_id"])
        threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.1},
                         name="mixar-mcp-relay", daemon=True).start()

    def stop(self):
        self.stopping.set()
        try:
            if self.record:
                self.record.unlink(missing_ok=True)
        finally:
            # shutdown waits for the accept loop only, never a tool operation.
            self.shutdown()
            self.server_close()


class RelayHandler(BaseHTTPRequestHandler):
    server_version = "MixarMCP"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_args):
        pass  # Do not log tool arguments, local paths, or credentials.

    def reply(self, status, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def authorized(self):
        if self.server.stopping.is_set():
            self.reply(503, {"error": "MCP connector is disabled"})
            return False
        if self.headers.get("Origin") or self.headers.get("Host") != "127.0.0.1:%d" % self.server.server_port:
            self.reply(403, {"error": "Only local MCP clients may connect"})
            return False
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, "Bearer " + self.server.token):
            self.reply(401, {"error": "Local connector credential rejected; reconnect to Mixar"})
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        if self.path != "/health":
            self.reply(404, {"error": "Unknown connector endpoint"})
            return
        context = self.server.snapshot()
        self.reply(200, {key: context.get(key) for key in
                         ("instance_id", "session_id", "scene_name", "connected", "qa_enabled", "qa_port")})

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != "/mcp":
            self.reply(404, {"error": "Unknown connector endpoint"})
            return
        try:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Chunked requests are not supported")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise ValueError("Invalid MCP request size")
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Expected application/json")
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                raise ValueError("Expected a JSON-RPC 2.0 object")
            if self.server.stopping.is_set():
                self.reply(503, {"error": "MCP connector is disabled"})
                return
            context = dict(self.server.snapshot())
            if not context.get("connected"):
                self.reply(503, {"error": "Sign in to Mixar and wait for the agent connection"})
                return
            if self.headers.get("X-Mixar-Session-Id"):
                context["session_id"] = str(uuid.UUID(self.headers["X-Mixar-Session-Id"]))
            headers = {}
            for name in ("MCP-Protocol-Version", "X-Mixar-Call-Id"):
                if self.headers.get(name):
                    headers[name] = self.headers[name]
            if "X-Mixar-Call-Id" in headers:
                headers["X-Mixar-Call-Id"] = str(uuid.UUID(headers["X-Mixar-Call-Id"]))
            status, response = self.server.forward(request, context, headers)
            self.reply(status, response)
        except (ValueError, TypeError, KeyError):
            self.reply(400, {"error": "Malformed MCP request"})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except Exception:
            self.reply(502, {"error": "MCP relay failed; check the desktop connection"})
