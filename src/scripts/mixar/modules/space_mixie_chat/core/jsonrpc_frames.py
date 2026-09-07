# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Frame-level reads for the JSON-RPC WebSocket client.

websocket-client's ``WebSocket.recv()`` folds every control frame into an
empty string: a server CLOSE (and its status code), a protocol PING and a
PONG all come back as ``""``. The client therefore could not tell a
deliberate auth rejection (close 4001) from a backend restart (1012), a
Redis registration failure (1011), a replaced connection (1008) or a plain
handshake timeout — and it counted every one of them as an authentication
failure, giving up on reconnection for good after three in a row. A backend
restart is exactly the moment those transient closes and slow handshakes
cluster, so the desktop showed "Reconnecting" through the outage and then
never came back once the backend was up.

Reading through ``recv_data(control_frame=True)`` keeps the opcode and the
close payload, so the loop can react to what the server actually said.
bpy-free by design: this runs on the WebSocket receive thread.
"""

import json
import struct
import time
from dataclasses import dataclass
from typing import Any, Optional

from ..constants import JSONRPCErrorCode, WS_CLOSE_AUTH_FAILED

try:
    from websocket import ABNF
except ImportError:  # pragma: no cover - websocket-client is bundled
    ABNF = None

KIND_MESSAGE = "message"
KIND_CONTROL = "control"
KIND_CLOSED = "closed"

HANDSHAKE_OK = "ok"
HANDSHAKE_AUTH_FAILED = "auth_failed"
HANDSHAKE_TRANSIENT = "transient"

# Server-side JSON-RPC error codes that mean "your credentials are wrong",
# as opposed to "I could not serve you right now".
_AUTH_ERROR_CODES = frozenset({JSONRPCErrorCode.NOT_AUTHENTICATED})


@dataclass(frozen=True)
class Frame:
    """One decoded WebSocket frame.

    ``kind`` is MESSAGE (``text`` holds the payload), CONTROL (a ping/pong
    that proves the link is alive and carries nothing) or CLOSED (the server
    sent a close frame; ``close_code`` is its status when it carried one).
    """

    kind: str
    text: str = ""
    close_code: Optional[int] = None


def close_code_from_payload(data: Any) -> Optional[int]:
    """Extract the RFC 6455 status code from a close frame payload."""
    if isinstance(data, str):
        data = data.encode("utf-8", "replace")
    if not isinstance(data, (bytes, bytearray)) or len(data) < 2:
        return None
    return struct.unpack("!H", bytes(data[:2]))[0]


def read_frame(ws: Any) -> Frame:
    """Receive one frame, preserving control frames and close codes.

    Exceptions from the socket (timeouts, a torn-down connection) propagate
    unchanged so the caller keeps its existing handling for them.
    """
    opcode, data = ws.recv_data(control_frame=True)
    if opcode == ABNF.OPCODE_CLOSE:
        return Frame(KIND_CLOSED, close_code=close_code_from_payload(data))
    if opcode in (ABNF.OPCODE_PING, ABNF.OPCODE_PONG):
        return Frame(KIND_CONTROL)
    if isinstance(data, (bytes, bytearray)):
        data = bytes(data).decode("utf-8")
    return Frame(KIND_MESSAGE, text=data)


def classify_handshake_response(response: Any) -> str:
    """Map a decoded handshake reply to HANDSHAKE_OK / AUTH_FAILED / TRANSIENT.

    Only a server that says the credentials are bad is an auth failure.
    Any other error (handler error, internal error, malformed reply) is
    something a later attempt may well succeed at — the backend may still
    be warming up — and must keep the reconnect loop alive.
    """
    if not isinstance(response, dict):
        return HANDSHAKE_TRANSIENT
    result = response.get("result")
    if isinstance(result, dict) and result.get("success"):
        return HANDSHAKE_OK
    error = response.get("error")
    if isinstance(error, dict) and error.get("code") in _AUTH_ERROR_CODES:
        return HANDSHAKE_AUTH_FAILED
    return HANDSHAKE_TRANSIENT


def wait_for_handshake(ws: Any, timeout: float = 10.0) -> tuple[str, str]:
    """Read frames until the handshake is answered or ``timeout`` elapses.

    Returns ``(outcome, detail)`` where ``outcome`` is one of the
    HANDSHAKE_* constants and ``detail`` is a log-ready explanation.
    A server CLOSE keeps its status code: ``WS_CLOSE_AUTH_FAILED`` is the
    ONLY close that means the credentials were rejected; every other code
    (1011 registration failed, 1012 restarting, 1008 replaced, 1006 lost)
    is a backend that is not ready yet. Control frames are skipped but the
    overall deadline still applies, so a server that only pings cannot
    hold the connect attempt open forever.
    """
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return HANDSHAKE_TRANSIENT, f"no handshake reply within {timeout:.0f}s"
        ws.settimeout(remaining)
        frame = read_frame(ws)
        if frame.kind == KIND_CLOSED:
            if frame.close_code == WS_CLOSE_AUTH_FAILED:
                return (
                    HANDSHAKE_AUTH_FAILED,
                    f"server closed with {WS_CLOSE_AUTH_FAILED} (authentication failed)",
                )
            return (
                HANDSHAKE_TRANSIENT,
                "server closed the socket before answering the handshake "
                f"(close code {frame.close_code})",
            )
        if frame.kind != KIND_MESSAGE:
            continue  # ping/pong while the server works on it
        response = json.loads(frame.text)
        outcome = classify_handshake_response(response)
        if outcome == HANDSHAKE_OK:
            return outcome, "handshake successful"
        error = response.get("error") if isinstance(response, dict) else None
        message = error.get("message", "Unknown") if isinstance(error, dict) else "Unknown"
        return outcome, f"handshake failed ({outcome}): {message}"
