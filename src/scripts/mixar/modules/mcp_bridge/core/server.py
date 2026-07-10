# SPDX-FileCopyrightText: 2026 AnkleBreaker Studio
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Loopback HTTP server for the MCP bridge.

Runs in daemon threads inside Mixar's embedded Python. The companion MCP
server (mcp/ at the repo root) is the only intended client.

Security posture (the bind is loopback, but a local web page could still try
to POST here, so the transport is hardened against browser-driven CSRF /
DNS-rebinding):
  * A shared token is ALWAYS required. If MIXAR_MCP_TOKEN is unset one is
    generated at startup and written to a file the local MCP server reads.
  * POSTs must be Content-Type: application/json (forces a CORS preflight for
    cross-origin browsers, which the server never answers → request blocked).
  * Any request carrying an Origin header is rejected (the Node client never
    sends one; browsers always do cross-origin).
  * The Host header must be loopback (defeats DNS-rebinding).
  * Binding is refused for any non-loopback host.

Thread safety: handlers that touch bpy marshal onto the main thread via
executor_bridge; backend service calls are plain sync HTTP, safe off-main.
"""

import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Optional
from urllib.parse import urlparse

from mixar.config.logging_config import get_logger

from ..constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    ENV_HOST,
    ENV_PORT,
    ENV_TOKEN,
    LOOPBACK_HOSTS,
    MAX_CONCURRENT_REQUESTS,
    MAX_REQUEST_BODY_BYTES,
    SOCKET_TIMEOUT_S,
    TOKEN_FILE_NAME,
    TOKEN_HEADER,
)

logger = get_logger(__name__)

_server: Optional["MCPBridgeServer"] = None
_server_lock = threading.Lock()
# Active shared token for this process (env-supplied or auto-generated).
_active_token: str = ""
_request_slots = threading.Semaphore(MAX_CONCURRENT_REQUESTS)


def _stable_token_path() -> str:
    """Version-independent token path the Node client probes on every OS.

    `~/.mixar/mcp_bridge_token` — deterministic and platform-agnostic, so the
    companion MCP server can find the auto-generated token without guessing
    Blender's versioned config directory.
    """
    base = os.path.join(os.path.expanduser("~"), ".mixar")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, TOKEN_FILE_NAME)


def _token_file_paths() -> list:
    """All locations to persist the token to.

    Always includes the stable `~/.mixar` path (what the Node client reads);
    also writes into Blender's own config dir when available, for operators
    who look there.
    """
    paths = []
    try:
        import bpy

        base = bpy.utils.user_resource("CONFIG", path="mixar", create=True)
        if base:
            paths.append(os.path.join(base, TOKEN_FILE_NAME))
    except Exception:
        pass
    stable = _stable_token_path()
    if stable not in paths:
        paths.append(stable)
    return paths


def _resolve_token() -> str:
    """Return the env token, or generate + persist one for MCP clients."""
    env_token = os.environ.get(ENV_TOKEN, "").strip()
    if env_token:
        return env_token
    token = secrets.token_urlsafe(32)
    persisted = False
    for path in _token_file_paths():
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(token)
            try:  # best-effort owner-only on POSIX
                os.chmod(path, 0o600)
            except OSError:
                pass
            logger.info("[MCP bridge] auth token written to %s", path)
            persisted = True
        except Exception as exc:
            logger.warning("[MCP bridge] could not write auth token to %s: %s", path, exc)
    if not persisted:
        logger.error(
            "[MCP bridge] could not persist the auth token anywhere; the MCP client "
            "will 401. Set MIXAR_MCP_TOKEN on both sides to work around this."
        )
    return token


def _is_loopback(host: str) -> bool:
    return (host or "").strip().lower() in LOOPBACK_HOSTS


def _host_header_ok(host_header: str, port: int) -> bool:
    """Host header must name a loopback host (optionally with our port).

    Handles bracketed IPv6 (`[::1]` and `[::1]:9877`) as well as `host:port`.
    """
    if not host_header:
        return False
    h = host_header.strip()
    if h.startswith("["):  # bracketed IPv6, optional :port
        end = h.find("]")
        hostname = h[1:end] if end != -1 else h.strip("[]")
    elif ":" in h:  # host:port
        hostname = h.rsplit(":", 1)[0]
    else:
        hostname = h
    return hostname.lower() in LOOPBACK_HOSTS


class MCPBridgeHandler(BaseHTTPRequestHandler):
    """HTTP handler: GET /health plus POST routes from handlers.ROUTES."""

    timeout = SOCKET_TIMEOUT_S  # slow-loris guard (socketserver honors this)
    # HTTP/1.1 enables keep-alive so the Node client reuses one loopback socket
    # across a session's many tool calls instead of a connect/close per request.
    # Every response already sends Content-Length, the precondition keep-alive
    # needs.
    protocol_version = "HTTP/1.1"

    # Keep Blender's console quiet; route through the module logger instead.
    def log_message(self, fmt, *args):  # noqa: N802 (stdlib signature)
        logger.debug("[MCP bridge] %s", fmt % args)

    # ── request guards ──────────────────────────────────────────────────────

    def _reject_browser(self) -> Optional[str]:
        """Return a reason string if this looks like a browser cross-origin
        request (CSRF / DNS-rebinding), else None."""
        if self.headers.get("Origin"):
            return "Origin header present"
        port = self.server.server_address[1]
        if not _host_header_ok(self.headers.get("Host", ""), port):
            return "non-loopback Host header"
        return None

    def _check_token(self) -> bool:
        provided = self.headers.get(TOKEN_HEADER, "")
        return bool(_active_token) and hmac.compare_digest(provided, _active_token)

    # ── verbs ───────────────────────────────────────────────────────────────

    def do_GET(self):  # noqa: N802
        reason = self._reject_browser()
        if reason:
            self._send_json(403, {"success": False, "error": "Forbidden: {0}".format(reason)})
            return
        if urlparse(self.path).path != "/health":
            self._send_json(404, {"success": False, "error": "Unknown GET endpoint"})
            return
        # /health still requires the token — no pre-attack recon of app state.
        if not self._check_token():
            self._send_json(401, {"success": False, "error": "Missing or invalid token"})
            return
        self._send_json(200, {
            "success": True,
            "status": "ok",
            "app": "mixar",
            "app_version": self._app_version(),
        })

    def do_POST(self):  # noqa: N802
        reason = self._reject_browser()
        if reason:
            self._send_json(403, {"success": False, "error": "Forbidden: {0}".format(reason)})
            return
        if not self._check_token():
            self._send_json(401, {
                "success": False,
                "error": "Missing or invalid {0} header".format(TOKEN_HEADER),
            })
            return
        # Enforce JSON content type: blocks CORS-safelisted (text/plain,
        # form) cross-origin POSTs that would otherwise skip preflight.
        content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._send_json(415, {
                "success": False,
                "error": "Content-Type must be application/json",
            })
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            content_length = 0
        if content_length > MAX_REQUEST_BODY_BYTES:
            self._send_json(413, {
                "success": False,
                "error": "Request body too large ({0} bytes, max {1})".format(
                    content_length, MAX_REQUEST_BODY_BYTES
                ),
            })
            return

        # Guard the raw socket read: a stalled or reset client mid-upload (very
        # plausible for the large base64 payloads this endpoint anticipates)
        # must yield a structured envelope, not an uncaught traceback to stderr
        # that the Node client would misread as "Mixar is unreachable".
        try:
            body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        except (TimeoutError, ConnectionError, OSError) as exc:
            logger.warning("[MCP bridge] failed reading request body: %s", exc)
            self._send_json(408, {
                "success": False,
                "error": "Timed out or lost connection reading the request body.",
            })
            return
        try:
            params = json.loads(body) if body else {}
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            self._send_json(400, {"success": False, "error": "Invalid JSON: {0}".format(exc)})
            return

        if not _request_slots.acquire(blocking=False):
            self._send_json(503, {
                "success": False,
                "error": "Bridge busy (too many concurrent requests)",
            })
            return
        try:
            from .handlers import route_request

            result = route_request(urlparse(self.path).path, params)
            self._send_json(200, result)
        except Exception as exc:
            logger.error("[MCP bridge] request failed: %s", exc, exc_info=True)
            self._send_json(500, {"success": False, "error": str(exc)})
        finally:
            _request_slots.release()

    # ── helpers ─────────────────────────────────────────────────────────────

    def _send_json(self, status: int, data: dict) -> None:
        try:
            payload = json.dumps(data).encode("utf-8")
        except (TypeError, ValueError) as exc:
            # Don't fail silently: a non-serializable handler result is a bug.
            logger.error("[MCP bridge] response not JSON-serializable: %s", exc, exc_info=True)
            payload = json.dumps(
                {"success": False, "error": "Non-serializable response: {0}".format(exc)}
            ).encode("utf-8")
            status = 500
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client hung up; nothing to do

    @staticmethod
    def _app_version() -> str:
        try:
            import bpy

            return ".".join(str(v) for v in bpy.app.version)
        except Exception:
            return "unknown"


class MCPBridgeServer(ThreadingMixIn, HTTPServer):
    """Thread-per-request server; long scripts must not block other calls.

    Concurrency is capped by a semaphore in the handler, so runaway
    connections cannot exhaust the main thread's work queue unbounded.
    """

    allow_reuse_address = True
    daemon_threads = True


def start_server(host: Optional[str] = None, port: Optional[int] = None) -> Optional[MCPBridgeServer]:
    """Start the bridge server in a daemon thread (idempotent).

    Refuses to bind to any non-loopback host. Always establishes a shared
    token first (env-supplied or auto-generated).
    """
    global _server, _active_token
    with _server_lock:
        if _server is not None:
            return _server
        bind_host = host or os.environ.get(ENV_HOST, DEFAULT_HOST)
        if not _is_loopback(bind_host):
            logger.error(
                "[MCP bridge] refusing to bind non-loopback host %r — the bridge "
                "is a local-control surface only. Unset MIXAR_MCP_HOST.",
                bind_host,
            )
            return None
        try:
            bind_port = int(port if port is not None else os.environ.get(ENV_PORT, DEFAULT_PORT))
        except (TypeError, ValueError):
            bind_port = DEFAULT_PORT

        # Fresh lifecycle: re-arm the executor's shutdown-abandon signal.
        from .executor_bridge import clear_shutdown

        clear_shutdown()

        _active_token = _resolve_token()

        try:
            server = MCPBridgeServer((bind_host, bind_port), MCPBridgeHandler)
        except OSError as exc:
            logger.error(
                "[MCP bridge] failed to bind %s:%s — %s (is another instance running?)",
                bind_host, bind_port, exc,
            )
            return None
        thread = threading.Thread(
            target=server.serve_forever, name="Mixar-MCP-Bridge", daemon=True
        )
        thread.start()
        _server = server
        logger.info("[MCP bridge] listening on %s:%s (token auth required)", bind_host, bind_port)
        return server


def stop_server() -> None:
    """Shut the bridge down gracefully (idempotent).

    The lock is held across shutdown+close so a concurrent start_server() (e.g.
    a rapid Reload Scripts / enable toggle) cannot observe "stopped" and try to
    re-bind the port before the socket is actually released.
    """
    global _server
    # Signal in-flight releasers first so a job that will never finish (app
    # going away) frees its lock instead of blocking a restart.
    from .executor_bridge import signal_shutdown

    signal_shutdown()
    with _server_lock:
        server = _server
        _server = None
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception as exc:
                logger.warning("[MCP bridge] shutdown error: %s", exc)
            logger.info("[MCP bridge] stopped")


def is_running() -> bool:
    return _server is not None
