# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""End-to-end LAN server test over real sockets.

Runs the actual ThreadingHTTPServer on loopback (TLS forced off — cert
generation touches bpy paths) and speaks genuine HTTP + RFC 6455 client
frames at it: static serving, token gating, the upgrade handshake, inbound
control messages landing in the Session, and outbound JSON/binary frames
reaching the client. This is the closest CI gets to a phone pairing.
"""

import base64
import json
import socket
import struct
import time

import pytest

from mixar.modules.virtual_camera.core import server as server_mod
from mixar.modules.virtual_camera.core.server import VirtualCameraServer


@pytest.fixture
def running_server(monkeypatch):
    monkeypatch.setattr(server_mod.pairing, "lan_addresses", lambda: ["127.0.0.1"])
    monkeypatch.setattr(server_mod.tls_utils, "ensure_certificate", lambda hosts: None)
    srv = VirtualCameraServer()
    assert srv.start()
    yield srv
    srv.stop()
    time.sleep(0.15)  # let the teardown thread release the port


def _http_get(port, path):
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(
            f"GET {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n".encode()
        )
        data = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    status = int(head.split(b" ", 2)[1])
    return status, head, body


class _WSClient:
    def __init__(self, port, token):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        key = base64.b64encode(b"0123456789abcdef").decode()
        self.sock.sendall(
            (
                f"GET /ws?t={token} HTTP/1.1\r\n"
                "Host: x\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        head = b""
        while b"\r\n\r\n" not in head:
            head += self.sock.recv(4096)
        self.status = int(head.split(b" ", 2)[1])
        self._buf = head.partition(b"\r\n\r\n")[2]

    def send_text(self, payload: dict):
        data = json.dumps(payload).encode()
        mask = b"\xaa\xbb\xcc\xdd"
        head = bytearray([0x81])
        n = len(data)
        if n <= 125:
            head.append(0x80 | n)
        else:
            head.append(0x80 | 126)
            head += struct.pack("!H", n)
        head += mask
        head += bytes(b ^ mask[i & 3] for i, b in enumerate(data))
        self.sock.sendall(bytes(head))

    def recv_frame(self):
        while True:
            if len(self._buf) >= 2:
                length = self._buf[1] & 0x7F
                offset = 2
                if length == 126:
                    if len(self._buf) >= 4:
                        (length,) = struct.unpack_from("!H", self._buf, 2)
                        offset = 4
                    else:
                        length = None
                elif length == 127:
                    if len(self._buf) >= 10:
                        (length,) = struct.unpack_from("!Q", self._buf, 2)
                        offset = 10
                    else:
                        length = None
                if length is not None and len(self._buf) >= offset + length:
                    opcode = self._buf[0] & 0x0F
                    payload = self._buf[offset:offset + length]
                    self._buf = self._buf[offset + length:]
                    return opcode, payload
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("server closed")
            self._buf += chunk

    def close(self):
        self.sock.close()


class TestHTTP:
    def test_index_served_with_no_store(self, running_server):
        status, head, body = _http_get(running_server.state.port, "/")
        assert status == 200
        assert b"Cache-Control: no-store" in head
        assert b"Mixar Virtual Camera" in body

    def test_asset_served_with_content_type(self, running_server):
        status, head, _ = _http_get(running_server.state.port, "/js/app.js")
        assert status == 200
        assert b"javascript" in head.lower()

    def test_traversal_404(self, running_server):
        status, _, _ = _http_get(
            running_server.state.port, "/../../core/server.py"
        )
        assert status == 404

    def test_pairing_url_uses_http_without_tls(self, running_server):
        assert running_server.state.url.startswith("http://127.0.0.1:")


class TestWebSocket:
    def test_bad_token_rejected(self, running_server):
        client = _WSClient(running_server.state.port, "wrong-token")
        assert client.status == 403
        client.close()

    def test_handshake_control_and_outbound_frames(self, running_server):
        client = _WSClient(running_server.state.port, running_server.state.token)
        assert client.status == 101

        client.send_text({"t": "hello", "device": {"ua": "pytest"}})
        client.send_text(
            {"t": "ctl", "q": [1, 0, 0, 0], "j1": [0.25, 0], "j2": [0, 0]}
        )

        deadline = time.time() + 5
        session = running_server.session
        while time.time() < deadline:
            if session.connected and session.control_snapshot(time.monotonic()):
                break
            time.sleep(0.02)
        packet = session.control_snapshot(time.monotonic())
        assert packet is not None and packet.j1 == (0.25, 0)
        assert session.device_info == {"ua": "pytest"}
        assert running_server.state.phone_connected

        running_server.send_json({"t": "state", "frame": 7})
        opcode, payload = client.recv_frame()
        assert opcode == 0x1
        assert json.loads(payload)["frame"] == 7

        running_server.send_stream_frame(b"\xff\xd8fakejpeg")
        opcode, payload = client.recv_frame()
        assert opcode == 0x2
        assert payload == b"\xff\xd8fakejpeg"
        client.close()

    def test_new_connection_replaces_old(self, running_server):
        token = running_server.state.token
        first = _WSClient(running_server.state.port, token)
        assert first.status == 101
        second = _WSClient(running_server.state.port, token)
        assert second.status == 101

        # The first client gets a close frame (code 4000) and dies.
        deadline = time.time() + 5
        closed = False
        while time.time() < deadline and not closed:
            try:
                opcode, payload = first.recv_frame()
            except (ConnectionError, OSError):
                closed = True
                break
            if opcode == 0x8:
                assert struct.unpack("!H", payload[:2])[0] == 4000
                closed = True
        assert closed

        running_server.send_json({"t": "state", "frame": 1})
        opcode, _ = second.recv_frame()
        assert opcode == 0x1
        first.close()
        second.close()
