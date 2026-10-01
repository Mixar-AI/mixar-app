# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mixar MCP stdio launcher (Python 3.10+, standard library only).

Run with --config claude or --config codex for a paste-ready client entry.
The desktop owns account authentication; this process only sees a local token.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import http.client
import importlib.util
import json
from pathlib import Path
import sys
import threading
import uuid


_SPEC = importlib.util.spec_from_file_location(
    "mixar_mcp_discovery", Path(__file__).parent / "modules/mcp_bridge/core/discovery.py")
_DISCOVERY = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_DISCOVERY)
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
MAX_PENDING_REQUESTS = 32


def local_request(record, method, path, body=None, headers=None, timeout=610):
    connection = http.client.HTTPConnection("127.0.0.1", record["port"], timeout=timeout)
    try:
        connection.request(method, path, body=body, headers={
            "Authorization": "Bearer " + record["token"],
            "Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse()
        data = response.read(MAX_MESSAGE_BYTES + 1)
        if len(data) > MAX_MESSAGE_BYTES:
            raise ValueError("MCP response exceeds the transport limit")
        return response.status, data
    finally:
        connection.close()


def discover(instance_id=None):
    candidates = []
    for path in _DISCOVERY.discovery_directory().glob("*.json"):
        try:
            record = _DISCOVERY.read_record(path)
            if instance_id and record.get("instance_id") != instance_id:
                continue
            status, data = local_request(record, "GET", "/health", timeout=1)
            health = json.loads(data)
            if status == 200 and health.get("instance_id") == record.get("instance_id"):
                candidates.append({**record, "session_id": health.get("session_id")})
        except (OSError, ValueError, http.client.HTTPException):
            continue
    if not candidates:
        raise RuntimeError("Open Mixar, sign in, then use Help > Connect Claude / Codex to enable MCP.")
    if len(candidates) != 1:
        ids = ", ".join(item["instance_id"] for item in candidates)
        raise RuntimeError("Several Mixar windows are available; use --instance with one of: " + ids)
    return candidates[0]


class StdioBridge:
    def __init__(self, instance_id=None, session_id=None, qa_port=None):
        self.instance_id = instance_id
        self.session_id = session_id
        self.record = None
        self.protocol_version = None
        self.lock = threading.Lock()
        self.qa = None
        if qa_port is not None:
            spec = importlib.util.spec_from_file_location("mixar_mcp_qa_adapter",
                Path(__file__).parent / "modules/mcp_bridge/core/qa_adapter.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.qa = module.QAAdapter(qa_port, self.health)

    def health(self):
        status, body = local_request(self.record, "GET", "/health", timeout=2)
        result = json.loads(body)
        if status != 200 or result.get("instance_id") != self.record.get("instance_id"):
            raise RuntimeError("The selected Mixar instance is no longer available")
        return result

    def respond(self, payload):
        with self.lock:
            sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
            sys.stdout.flush()

    def handle(self, request):
        call_id = None
        try:
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                raise ValueError("Expected one JSON-RPC 2.0 object")
            if self.record is None:
                self.record = discover(self.instance_id)
            params = request.get("params") or {}
            if request.get("method") == "tools/call":
                meta = params.get("_meta", {})
                call_id = str(uuid.UUID(meta["mixar/request-id"])) if meta.get("mixar/request-id") else str(uuid.uuid4())
            if (self.qa is not None and request.get("method") == "tools/call"
                    and self.qa.handles(params.get("name"))):
                if "id" not in request:
                    return
                result = self.qa.call(params["name"], params.get("arguments") or {}, call_id)
                self.respond({"jsonrpc": "2.0", "id": request["id"], "result": result})
                return
            headers = {}
            if self.protocol_version:
                headers["MCP-Protocol-Version"] = self.protocol_version
            target_session = self.session_id or self.record.get("session_id")
            if target_session:
                headers["X-Mixar-Session-Id"] = target_session
            if request.get("method") == "tools/call":
                headers["X-Mixar-Call-Id"] = call_id
            status, body = local_request(self.record, "POST", "/mcp", json.dumps(request).encode(), headers)
            if "id" not in request:
                return
            if not 200 <= status < 300:
                message = "Mixar connector returned HTTP %d" % status
                try:
                    message = json.loads(body).get("error", message)
                except (ValueError, AttributeError):
                    pass
                raise RuntimeError(message)
            response = json.loads(body)
            if (self.qa is not None and request.get("method") == "tools/list"
                    and "result" in response and not response["result"].get("nextCursor")):
                response["result"].setdefault("tools", []).extend(self.qa.tools())
            if request.get("method") == "initialize" and "result" in response:
                self.protocol_version = response["result"].get("protocolVersion")
            self.respond(response)
        except Exception as exc:
            # Never replay a timed-out mutation automatically. The call id lets the
            # backend return its durable receipt on an explicitly requested retry.
            if isinstance(request, dict) and "id" not in request:
                return
            error = {"code": -32000, "message": str(exc)}
            if call_id:
                error["data"] = {"request_id": call_id, "outcome": "unknown",
                                 "retry_meta": {"mixar/request-id": call_id}}
            self.respond({"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                          "error": error})


def configuration(client, python=None):
    command = python or sys.executable
    script = str(Path(__file__).resolve())
    if client == "claude":
        return json.dumps({"mcpServers": {"mixar": {"command": command, "args": [script]}}}, indent=2)
    return "[mcp_servers.mixar]\ncommand = %s\nargs = [%s]\ntool_timeout_sec = 610\n" % (
        json.dumps(command), json.dumps(script))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=("claude", "codex"))
    parser.add_argument("--instance", help="Pin one running Mixar instance")
    parser.add_argument("--session", help="Pin a scene session UUID")
    parser.add_argument("--qa-port", type=int, help="Opt in to semantic QA tools on this QA instance's port")
    options = parser.parse_args()
    if options.config:
        print(configuration(options.config))
        return
    if options.session:
        uuid.UUID(options.session)
    if options.qa_port is not None and not 1 <= options.qa_port <= 65535:
        parser.error("--qa-port must be between 1 and 65535")
    bridge = StdioBridge(options.instance, options.session, options.qa_port)
    pending = threading.BoundedSemaphore(MAX_PENDING_REQUESTS)
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="mixar-mcp") as pool:
        while True:
            line = sys.stdin.buffer.readline(MAX_MESSAGE_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_MESSAGE_BYTES:
                bridge.respond({"jsonrpc": "2.0", "id": None,
                                "error": {"code": -32600, "message": "MCP message too large"}})
                return
            try:
                request = json.loads(line)
            except ValueError:
                bridge.respond({"jsonrpc": "2.0", "id": None,
                                "error": {"code": -32700, "message": "Invalid JSON"}})
                continue
            # Initialize before accepting follow-up messages; calls can run while
            # cancellation/progress notifications continue to flow on stdin.
            if isinstance(request, dict) and request.get("method") == "initialize":
                bridge.handle(request)
            else:
                submit_request(pool, pending, bridge, request)


def submit_request(pool, pending, bridge, request):
    """Bound queued bodies as well as active workers; never retry rejected work."""
    if not pending.acquire(blocking=False):
        if isinstance(request, dict) and "id" in request:
            bridge.respond({"jsonrpc": "2.0", "id": request["id"],
                            "error": {"code": -32002, "message": "Too many pending MCP requests"}})
        return
    try:
        future = pool.submit(bridge.handle, request)
        future.add_done_callback(lambda _result: pending.release())
    except Exception:
        pending.release()
        raise


if __name__ == "__main__":
    main()
