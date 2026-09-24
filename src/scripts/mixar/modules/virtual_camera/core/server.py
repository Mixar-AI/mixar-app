# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""LAN HTTPS + WebSocket server hosting the phone control app.

Runs entirely on daemon threads and never touches bpy — the Blender side
talks to it through the thread-safe :class:`~.session.Session` object and the
``ServerState`` snapshot. One phone controls at a time; a newer pairing
replaces the current one.
"""

from __future__ import annotations

import hmac
import http.server
import json
import mimetypes
import os
import socket
import ssl
import threading
import time
from collections import deque
from urllib.parse import parse_qs, urlparse

from mixar.config.logging_config import get_logger
from mixar.modules.common.network import server_ssl_context

from ..constants import DEFAULT_PORT, PORT_SCAN_RANGE, WS_PATH
from . import pairing, tls_utils, ws_codec
from .session import Session

logger = get_logger(__name__)

_WEBAPP_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "webapp")
)
_SOCKET_TIMEOUT = 20.0


def _under_webapp(candidate: str) -> bool:
    """Is *candidate* a path inside the bundled webapp folder?

    `os.path.commonpath` raises on Windows when the two paths land on
    different drives, which a request for `/C:/…` does — `os.path.join`
    honours the drive letter and throws the whole prefix away. An
    unauthenticated request must never reach an unhandled exception, and
    "not under the webapp" is exactly the right answer, so the raise is one.
    """
    try:
        resolved = os.path.abspath(candidate)
        return (
            resolved == _WEBAPP_DIR
            or os.path.commonpath([_WEBAPP_DIR, resolved]) == _WEBAPP_DIR
        )
    except (ValueError, OSError):
        return False


def _token_matches(candidate: str, expected: str) -> bool:
    """Constant-time pairing-token check that survives any input.

    `hmac.compare_digest` raises `TypeError` on a `str` outside ASCII, and
    the token arrives percent-decoded from the query string — so a phone (or
    a scanner) sending `?t=café` would crash the handler instead of being
    refused. Comparing the UTF-8 bytes is the same constant-time check
    without the input restriction.
    """
    try:
        return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))
    except (AttributeError, UnicodeEncodeError):
        return False


class ServerState:
    """Lock-free snapshot the UI reads from draw code (plain attributes)."""

    def __init__(self) -> None:
        self.running = False
        self.port = 0
        self.tls = False
        self.token = ""
        self.hosts: list[str] = []
        self.phone_connected = False
        self.last_error = ""

    @property
    def url(self) -> str:
        if not self.running or not self.hosts:
            return ""
        return pairing.pairing_url(self.hosts[0], self.port, self.token, tls=self.tls)


class _Connection:
    """One WebSocket client with a dedicated writer thread.

    JSON messages are never dropped; stream frames overwrite each other so a
    slow phone shows a late picture instead of an ever-growing latency queue.
    """

    def __init__(self, sock) -> None:
        self._sock = sock
        self._json_queue: deque[bytes] = deque()
        self._frame: bytes | None = None
        self._cond = threading.Condition()
        # `_cond` guards the QUEUE; this guards the SOCKET. `close()` writes
        # its frame from the caller's thread while the writer thread may be
        # mid-`sendall` on the same socket, and two interleaved frames are a
        # protocol error the phone cannot resynchronise from.
        self._send_lock = threading.Lock()
        self._alive = True
        self._writer = threading.Thread(
            target=self._write_loop, name="mixar-vcam-writer", daemon=True
        )
        self._writer.start()

    def send_json(self, payload: dict) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        with self._cond:
            if not self._alive:
                return
            self._json_queue.append(ws_codec.encode_frame(ws_codec.OP_TEXT, data))
            self._cond.notify()

    def send_stream_frame(self, image_bytes: bytes) -> None:
        with self._cond:
            if not self._alive:
                return
            self._frame = ws_codec.encode_frame(ws_codec.OP_BINARY, image_bytes)
            self._cond.notify()

    def send_pong(self, payload: bytes) -> None:
        with self._cond:
            if not self._alive:
                return
            self._json_queue.append(ws_codec.encode_frame(ws_codec.OP_PONG, payload))
            self._cond.notify()

    def close(self, code: int = 1000, reason: str = "") -> None:
        with self._cond:
            if not self._alive:
                return
            self._alive = False
            self._cond.notify_all()
        # Outside `_cond`: `sendall` blocks on a phone that has stopped
        # reading, and holding the queue lock through it stalls the writer
        # thread that is being told to stop.
        try:
            with self._send_lock:
                self._sock.sendall(ws_codec.encode_close(code, reason))
        except OSError:
            pass
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    @property
    def alive(self) -> bool:
        return self._alive

    def _write_loop(self) -> None:
        while True:
            with self._cond:
                while self._alive and not self._json_queue and self._frame is None:
                    self._cond.wait(timeout=1.0)
                if not self._alive:
                    return
                if self._json_queue:
                    chunk = self._json_queue.popleft()
                else:
                    chunk, self._frame = self._frame, None
            try:
                with self._send_lock:
                    self._sock.sendall(chunk)
            except OSError:
                with self._cond:
                    self._alive = False
                return


class VirtualCameraServer:
    """Owns the HTTP server thread, the pairing token and the active phone."""

    def __init__(self) -> None:
        self.state = ServerState()
        self.session = Session()
        self._httpd: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._conn_lock = threading.Lock()
        self._connection: _Connection | None = None

    # ---- lifecycle ----------------------------------------------------------

    def start(self) -> bool:
        if self.state.running:
            return True
        self.state.last_error = ""
        hosts = pairing.lan_addresses()
        if not hosts:
            self.state.last_error = "No network interface found — join a Wi-Fi network."
            return False

        cert = tls_utils.ensure_certificate(hosts)
        handler = _make_handler(self)
        httpd = None
        for port in range(DEFAULT_PORT, DEFAULT_PORT + PORT_SCAN_RANGE):
            try:
                httpd = http.server.ThreadingHTTPServer(("0.0.0.0", port), handler)
                break
            except OSError:
                continue
        if httpd is None:
            self.state.last_error = "No free port available."
            return False
        httpd.daemon_threads = True

        tls_ok = False
        if cert is not None:
            try:
                # NOT `ssl.SSLContext` — startup replaces it process-wide with
                # truststore's client subclass, which verifies the PEER's chain
                # inside `wrap_socket`. On a listening socket that is
                # meaningless, and with the handshake deferred it is fatal:
                # there is no `_sslobj` yet, so it raises AttributeError and the
                # server never starts. `server_ssl_context` hands back CPython's
                # own class (`common/network`, which owns the injection).
                ctx = server_ssl_context()
                ctx.load_cert_chain(cert[0], cert[1])
                # do_handshake_on_connect=False: accepted sockets inherit the
                # flag, deferring the TLS handshake from the accept loop into
                # the per-connection handler thread (Handler.setup) — a
                # stalled client must never block new pairings.
                httpd.socket = ctx.wrap_socket(
                    httpd.socket, server_side=True,
                    do_handshake_on_connect=False,
                )
                tls_ok = True
            except Exception as exc:
                # TLS is a DEGRADATION, never a failure to start: without it
                # iOS withholds DeviceOrientation and the app is joystick-only,
                # which is worth having. Anything narrower lets a new failure
                # mode take the whole server down, which is what an
                # AttributeError from the trust store just did. The panel
                # already says "No TLS: joystick control only" beside the QR;
                # the REASON belongs in the log, not in a second message.
                tls_ok = False
                logger.warning("Virtual camera: serving over HTTP, TLS setup failed: %s", exc)

        self._httpd = httpd
        self.state.port = httpd.server_address[1]
        self.state.tls = tls_ok
        self.state.hosts = hosts
        self.state.token = pairing.generate_token()
        self.state.running = True
        self._thread = threading.Thread(
            target=httpd.serve_forever, name="mixar-vcam-server", daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        if not self.state.running:
            return
        self.state.running = False
        self.drop_connection(reason="server stopped")
        httpd, self._httpd = self._httpd, None
        if httpd is not None:
            def _teardown() -> None:
                httpd.shutdown()       # blocks until serve_forever exits
                httpd.server_close()   # release the listening port

            threading.Thread(target=_teardown, daemon=True).start()
        self.state.phone_connected = False

    # ---- connection management ---------------------------------------------

    def adopt_connection(self, conn: _Connection) -> None:
        with self._conn_lock:
            old, self._connection = self._connection, conn
        if old is not None:
            old.close(code=4000, reason="replaced by new pairing")
        self.state.phone_connected = True

    def drop_connection(self, *, conn: _Connection | None = None,
                        reason: str = "") -> None:
        with self._conn_lock:
            if conn is not None and self._connection is not conn:
                return  # a newer pairing already took over
            old, self._connection = self._connection, None
        if old is not None:
            old.close(reason=reason)
        self.state.phone_connected = False
        self.session.mark_disconnected()

    def current_connection(self) -> _Connection | None:
        with self._conn_lock:
            return self._connection

    def send_json(self, payload: dict) -> None:
        conn = self.current_connection()
        if conn is not None:
            conn.send_json(payload)

    def send_stream_frame(self, image_bytes: bytes) -> None:
        conn = self.current_connection()
        if conn is not None:
            conn.send_stream_frame(image_bytes)


def _make_handler(server: VirtualCameraServer):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "MixarVCam"
        timeout = 30  # bounds header reads AND the deferred TLS handshake

        def log_message(self, *_args) -> None:  # keep Blender's console clean
            pass

        def setup(self) -> None:
            super().setup()
            self._tls_ok = True
            if hasattr(self.connection, "do_handshake"):
                try:
                    self.connection.do_handshake()
                except (ssl.SSLError, OSError):
                    self._tls_ok = False

        def handle(self) -> None:
            if not self._tls_ok:
                self.close_connection = True
                return
            super().handle()

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            parsed = urlparse(self.path)
            if parsed.path == WS_PATH:
                self._handle_websocket(parsed)
            else:
                self._serve_static(parsed.path)

        # ---- static webapp ------------------------------------------------

        def _serve_static(self, path: str) -> None:
            if path == "/":
                path = "/index.html"
            rel = os.path.normpath(path.lstrip("/"))
            full = os.path.join(_WEBAPP_DIR, rel)
            if not _under_webapp(full) or not os.path.isfile(full):
                self.send_error(404)
                return
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            with open(full, "rb") as fh:
                body = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        # ---- websocket ----------------------------------------------------

        def _handle_websocket(self, parsed) -> None:
            token = (parse_qs(parsed.query).get("t") or [""])[0]
            key = self.headers.get("Sec-WebSocket-Key", "")
            if (
                self.headers.get("Upgrade", "").lower() != "websocket"
                or not key
                or not server.state.running
                or not _token_matches(token, server.state.token)
            ):
                self.send_error(403)
                return

            self.send_response_only(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", ws_codec.accept_key(key))
            self.end_headers()
            self.close_connection = True

            sock = self.connection
            sock.settimeout(_SOCKET_TIMEOUT)
            conn = _Connection(sock)
            server.adopt_connection(conn)
            reader = ws_codec.FrameReader()
            try:
                while conn.alive:
                    data = sock.recv(65536)
                    if not data:
                        break
                    reader.feed(data)
                    for opcode, payload in reader.messages():
                        if opcode == ws_codec.OP_TEXT:
                            try:
                                msg = json.loads(payload.decode("utf-8"))
                            except (UnicodeDecodeError, ValueError):
                                continue
                            server.session.handle_message(msg, time.monotonic())
                        elif opcode == ws_codec.OP_PING:
                            conn.send_pong(payload)
                        elif opcode == ws_codec.OP_CLOSE:
                            return
            except (OSError, ws_codec.WSProtocolError):
                pass
            finally:
                server.drop_connection(conn=conn, reason="socket closed")

    return Handler


# Module-level singleton, created lazily by the Blender layer.
_server: VirtualCameraServer | None = None


def get_server() -> VirtualCameraServer:
    global _server
    if _server is None:
        _server = VirtualCameraServer()
    return _server
