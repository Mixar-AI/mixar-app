# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""RFC 6455 WebSocket framing — stdlib only, no third-party server dependency.

The virtual-camera server terminates a handful of LAN connections, so a
minimal, well-tested codec beats pulling an asyncio server library into the
embedded Python. Only what the phone app needs is implemented: text/binary
messages, ping/pong, close, client-to-server masking.
"""

from __future__ import annotations

import base64
import hashlib
import struct

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONT = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

_CONTROL_OPCODES = frozenset({OP_CLOSE, OP_PING, OP_PONG})
_KNOWN_OPCODES = _CONTROL_OPCODES | {OP_CONT, OP_TEXT, OP_BINARY}

MAX_FRAME_PAYLOAD = 4 * 1024 * 1024  # control-channel frames are tiny; refuse abuse


class WSProtocolError(Exception):
    """Peer violated the framing rules — the connection must be dropped."""


def accept_key(sec_websocket_key: str) -> str:
    """Compute the Sec-WebSocket-Accept header value for a handshake."""
    digest = hashlib.sha1((sec_websocket_key.strip() + WS_GUID).encode("ascii"))
    return base64.b64encode(digest.digest()).decode("ascii")


def encode_frame(opcode: int, payload: bytes, *, fin: bool = True) -> bytes:
    """Build a server-to-client (unmasked) frame."""
    if opcode not in _KNOWN_OPCODES:
        raise ValueError(f"unknown opcode {opcode:#x}")
    if opcode in _CONTROL_OPCODES and len(payload) > 125:
        raise ValueError("control frame payload must be <= 125 bytes")

    head = bytearray()
    head.append((0x80 if fin else 0x00) | opcode)
    n = len(payload)
    if n <= 125:
        head.append(n)
    elif n <= 0xFFFF:
        head.append(126)
        head += struct.pack("!H", n)
    else:
        head.append(127)
        head += struct.pack("!Q", n)
    return bytes(head) + payload


def encode_close(code: int = 1000, reason: str = "") -> bytes:
    payload = struct.pack("!H", code) + reason.encode("utf-8")[:123]
    return encode_frame(OP_CLOSE, payload)


class FrameReader:
    """Incremental parser for client-to-server frames.

    Feed raw socket bytes with :meth:`feed`; completed ``(opcode, payload)``
    messages come back from :meth:`messages`. Fragmented data frames are
    reassembled; control frames are surfaced individually (they may interleave
    with fragments per the RFC).
    """

    def __init__(self, *, require_mask: bool = True,
                 max_message: int = MAX_FRAME_PAYLOAD) -> None:
        self._buf = bytearray()
        self._require_mask = require_mask
        self._max_message = max_message
        self._frag_opcode: int | None = None
        self._frag_payload = bytearray()

    def feed(self, data: bytes) -> None:
        self._buf += data
        if len(self._buf) > self._max_message + 14:
            raise WSProtocolError("inbound buffer overflow")

    def messages(self):
        """Yield complete (opcode, payload) messages parsed so far."""
        while True:
            frame = self._next_frame()
            if frame is None:
                return
            fin, opcode, payload = frame

            if opcode in _CONTROL_OPCODES:
                if not fin:
                    raise WSProtocolError("fragmented control frame")
                yield opcode, bytes(payload)
                continue

            if opcode == OP_CONT:
                if self._frag_opcode is None:
                    raise WSProtocolError("continuation without start frame")
                self._frag_payload += payload
            else:
                if self._frag_opcode is not None:
                    raise WSProtocolError("new data frame during fragmentation")
                self._frag_opcode = opcode
                self._frag_payload = bytearray(payload)

            if len(self._frag_payload) > self._max_message:
                raise WSProtocolError("message too large")

            if fin:
                complete = (self._frag_opcode, bytes(self._frag_payload))
                self._frag_opcode = None
                self._frag_payload = bytearray()
                yield complete

    def _next_frame(self):
        buf = self._buf
        if len(buf) < 2:
            return None
        b0, b1 = buf[0], buf[1]
        if b0 & 0x70:
            raise WSProtocolError("unexpected RSV bits (no extensions negotiated)")
        fin = bool(b0 & 0x80)
        opcode = b0 & 0x0F
        if opcode not in _KNOWN_OPCODES:
            raise WSProtocolError(f"unknown opcode {opcode:#x}")
        masked = bool(b1 & 0x80)
        if self._require_mask and not masked:
            raise WSProtocolError("client frames must be masked")

        length = b1 & 0x7F
        offset = 2
        if length == 126:
            if len(buf) < 4:
                return None
            (length,) = struct.unpack_from("!H", buf, 2)
            offset = 4
        elif length == 127:
            if len(buf) < 10:
                return None
            (length,) = struct.unpack_from("!Q", buf, 2)
            offset = 10
        if length > self._max_message:
            raise WSProtocolError("frame too large")

        mask = b""
        if masked:
            if len(buf) < offset + 4:
                return None
            mask = bytes(buf[offset:offset + 4])
            offset += 4
        if len(buf) < offset + length:
            return None

        payload = bytearray(buf[offset:offset + length])
        if masked:
            for i in range(length):
                payload[i] ^= mask[i & 3]
        del self._buf[:offset + length]
        return fin, opcode, payload
