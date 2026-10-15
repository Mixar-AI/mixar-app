# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The agent WebSocket must reconnect by itself once a stopped backend is back.

Before this suite, every handshake failure — a 10s timeout while the backend
was still warming up, a 1011/1012/1008 close before the handshake reply, an
empty reply — was booked as an AUTH failure, and three in a row (about 7s of
backoff) stopped the reconnect loop for good. A backend restart is exactly
where those cluster, so the pill showed "Reconnecting" through the outage
and never came back. Root cause: websocket-client's ``recv()`` folds every
close frame into ``""``, so the client could not see the 4001 close code
that is the ONLY auth signal.
"""

import json
import struct
import time

import pytest
from websocket import ABNF, WebSocketTimeoutException

from mixar.modules.space_mixie_chat.constants import (
    DISCONNECT_REASON_AUTH_FAILED,
    WS_CLOSE_AUTH_FAILED,
)
from mixar.modules.space_mixie_chat.core import jsonrpc_client as jc
from mixar.modules.space_mixie_chat.core.jsonrpc_frames import (
    HANDSHAKE_AUTH_FAILED,
    HANDSHAKE_OK,
    HANDSHAKE_TRANSIENT,
    classify_handshake_response,
    close_code_from_payload,
)


def _close(code: int):
    return (ABNF.OPCODE_CLOSE, struct.pack("!H", code) + b"reason")


def _text(obj) -> tuple:
    return (ABNF.OPCODE_TEXT, json.dumps(obj).encode("utf-8"))


HANDSHAKE_REPLY_OK = _text(
    {"jsonrpc": "2.0", "id": "handshake_1", "result": {"success": True}}
)


class FakeWS:
    """A scripted socket: each recv_data pops the next frame (or raises)."""

    def __init__(self, frames=()):
        self.frames = list(frames)
        self.sent = []
        self.closed = False
        self._timeout = None

    def send(self, data):
        self.sent.append(data)

    def settimeout(self, value):
        self._timeout = value

    def gettimeout(self):
        return self._timeout

    def close(self):
        self.closed = True

    def recv_data(self, control_frame=False):
        assert control_frame, "the client must ask for control frames"
        if not self.frames:
            raise WebSocketTimeoutException("timed out")
        item = self.frames.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _make_client(monkeypatch, sockets, token="tok", refresh=None):
    """Client whose create_connection hands out ``sockets`` in order."""
    client = jc.JSONRPCWebSocketClient(
        "http://backend.test", "conn-1", token_getter=lambda: token
    )
    client._running.set()
    queue = list(sockets)
    headers_seen = []

    def create_connection(url, timeout=None, header=None):
        headers_seen.append(list(header or []))
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(jc.websocket, "create_connection", create_connection)
    if refresh is not None:
        monkeypatch.setattr(client, "_try_refresh_token", lambda: refresh)
    client._headers_seen = headers_seen
    return client


# --------------------------------------------------------------------------
# Frame helpers
# --------------------------------------------------------------------------

def test_close_code_is_read_from_the_close_payload():
    assert close_code_from_payload(struct.pack("!H", 4001) + b"bad token") == 4001
    assert close_code_from_payload(struct.pack("!H", 1012)) == 1012
    assert close_code_from_payload(b"") is None
    assert close_code_from_payload(None) is None


def test_only_not_authenticated_is_an_auth_failure():
    assert classify_handshake_response({"result": {"success": True}}) == HANDSHAKE_OK
    assert (
        classify_handshake_response({"error": {"code": -32004, "message": "no"}})
        == HANDSHAKE_AUTH_FAILED
    )
    # Internal / handler errors are a backend that is not ready yet.
    assert (
        classify_handshake_response({"error": {"code": -32603, "message": "boom"}})
        == HANDSHAKE_TRANSIENT
    )
    assert classify_handshake_response({"result": {"success": False}}) == HANDSHAKE_TRANSIENT
    assert classify_handshake_response("garbage") == HANDSHAKE_TRANSIENT


# --------------------------------------------------------------------------
# _do_connect: what counts as an auth failure
# --------------------------------------------------------------------------

def test_handshake_timeouts_never_stop_the_reconnect_loop(monkeypatch):
    # Three cold-start handshake timeouts used to be three "auth failures".
    client = _make_client(
        monkeypatch,
        [FakeWS(), FakeWS(), FakeWS(), FakeWS([HANDSHAKE_REPLY_OK])],
    )
    for _ in range(3):
        assert client._do_connect() is False
        assert client._auth.failure_count == 0
        assert client._running.is_set()
    assert client._do_connect() is True
    assert client.is_connected


@pytest.mark.parametrize("code", [1012, 1011, 1008, 1006, 1000])
def test_server_close_before_handshake_reply_is_transient(monkeypatch, code):
    client = _make_client(
        monkeypatch,
        [
            FakeWS([_close(code)]),
            FakeWS([_close(code)]),
            FakeWS([_close(code)]),
            FakeWS([HANDSHAKE_REPLY_OK]),
        ],
    )
    for _ in range(3):
        assert client._do_connect() is False
    assert client._auth.failure_count == 0
    assert client._running.is_set()
    assert client._do_connect() is True


def test_connection_refused_while_backend_is_down_then_recovers(monkeypatch):
    client = _make_client(
        monkeypatch,
        [ConnectionRefusedError("down"), ConnectionRefusedError("down"),
         FakeWS([HANDSHAKE_REPLY_OK])],
    )
    assert client._do_connect() is False
    assert client._do_connect() is False
    assert client._auth.failure_count == 0
    assert client._do_connect() is True


def test_auth_close_refreshes_token_then_reconnects(monkeypatch):
    client = _make_client(
        monkeypatch,
        [FakeWS([_close(WS_CLOSE_AUTH_FAILED)]), FakeWS([HANDSHAKE_REPLY_OK])],
        refresh=("fresh-tok", True),
    )
    assert client._do_connect() is False
    assert client._auth.failure_count == 1
    assert client._running.is_set()

    assert client._do_connect() is True
    assert "Authorization: Bearer fresh-tok" in client._headers_seen[1]
    assert client._auth.failure_count == 0  # reset on success


def test_auth_close_with_unrecoverable_refresh_stops_terminally(monkeypatch):
    reasons = []
    client = _make_client(
        monkeypatch,
        [FakeWS([_close(WS_CLOSE_AUTH_FAILED)]), FakeWS([HANDSHAKE_REPLY_OK])],
        refresh=(None, False),  # refresh token rejected -> must log in again
    )
    client._on_disconnected = reasons.append

    assert client._do_connect() is False
    assert client._running.is_set()  # the refresh decides, on the next try
    assert client._do_connect() is False
    assert not client._running.is_set()
    assert reasons == [DISCONNECT_REASON_AUTH_FAILED]


def test_auth_close_while_refresh_is_retryable_keeps_going_slowly(monkeypatch):
    # The backend can answer 4001 while its DB is still down mid-restart, and
    # the refresh endpoint 5xx's for the same reason. That must not be fatal.
    client = _make_client(
        monkeypatch,
        [FakeWS([_close(WS_CLOSE_AUTH_FAILED)]) for _ in range(4)]
        + [FakeWS([HANDSHAKE_REPLY_OK])],
        refresh=(None, True),
    )
    for expected in (1, 2, 3, 4):
        assert client._do_connect() is False
        assert client._auth.failure_count == expected
        assert client._running.is_set()
    assert client._current_delay == 60.0  # slowest cadence, never a stop
    assert client._do_connect() is True
    assert client._current_delay == 1.0


def test_http_401_on_upgrade_is_auth_but_502_is_not(monkeypatch):
    from websocket import WebSocketBadStatusException

    bad_gateway = WebSocketBadStatusException("502", 502)
    unauthorized = WebSocketBadStatusException("401", 401)
    client = _make_client(monkeypatch, [bad_gateway, unauthorized])
    assert client._do_connect() is False
    assert client._auth.failure_count == 0
    assert client._do_connect() is False
    assert client._auth.failure_count == 1


# --------------------------------------------------------------------------
# _receive_loop: close codes and control frames
# --------------------------------------------------------------------------

def _connected_client(frames):
    client = jc.JSONRPCWebSocketClient("http://backend.test", "conn-1")
    client._running.set()
    client._connected = True
    client._handshake_complete = True
    client._ws = FakeWS(frames)
    client._last_ping_time = time.time()
    client._last_recv_time = time.time() - 5.0
    return client


def test_receive_loop_restart_close_is_not_an_auth_failure():
    client = _connected_client([_close(1012)])
    client._receive_loop()
    assert client._auth.failure_count == 0
    assert client._running.is_set()
    assert not client._connected


def test_receive_loop_auth_close_is_recorded_but_not_terminal():
    client = _connected_client([_close(WS_CLOSE_AUTH_FAILED)])
    client._receive_loop()
    assert client._auth.failure_count == 1
    # The run loop reconnects and _do_connect decides after a refresh.
    assert client._running.is_set()


def test_receive_loop_counts_server_ping_as_traffic():
    client = _connected_client([(ABNF.OPCODE_PING, b""), _close(1000)])
    before = client._last_recv_time
    client._receive_loop()
    assert client._last_recv_time > before


def test_receive_loop_dispatches_text_frames():
    seen = []
    client = _connected_client(
        [_text({"jsonrpc": "2.0", "method": "agent.tool_start", "params": {"x": 1}}),
         _close(1000)]
    )
    client._on_tool_start = seen.append
    client._receive_loop()
    assert seen == [{"x": 1}]


# --------------------------------------------------------------------------
# The whole loop across a backend restart
# --------------------------------------------------------------------------

def test_run_loop_reconnects_after_backend_restart(monkeypatch):
    sleeps = []
    monkeypatch.setattr(jc.time, "sleep", sleeps.append)
    events = []
    client = _make_client(
        monkeypatch,
        [
            ConnectionRefusedError("backend down"),   # stopped
            FakeWS(),                                  # up, handshake times out
            FakeWS([_close(1012)]),                    # restarting
            FakeWS([HANDSHAKE_REPLY_OK]),              # back
        ],
    )

    def on_connected():
        events.append("connected")
        client._running.clear()  # end the test loop once we are back

    client._on_connected = on_connected
    client._on_disconnected = lambda reason: events.append(reason)

    client._run_loop()

    assert events.count("connected") == 1
    assert DISCONNECT_REASON_AUTH_FAILED not in events
    assert client._auth.failure_count == 0
    assert sleeps == [1.0, 2.0, 4.0]  # plain exponential backoff, no stop
