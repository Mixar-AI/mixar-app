# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Loopback SSO callback server: a silent peer must never block the real callback.

Regression for the enterprise "Waiting for browser..." hang: endpoint
security agents connect to the freshly bound port without sending a request.
"""

import socket
import threading
import time

import pytest

from mixar.modules.auth.core import sso


@pytest.fixture
def server():
    state = sso.CallbackState("expected-state")
    srv = sso.start_callback_server(state)
    yield srv, state, srv.server_address[1]
    srv.server_close()


def _get(port, path, timeout=5):
    """Send one HTTP/1.0 request and read the whole reply (server closes)."""
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as conn:
        conn.sendall(f"GET {path} HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n".encode())
        chunks = []
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)


def test_server_binds_loopback_only(server):
    srv, _, _ = server
    assert srv.server_address[0] == "127.0.0.1"
    assert srv.daemon_threads is True
    assert srv.allow_reuse_address is False


def test_silent_peer_does_not_block_real_callback(server):
    srv, state, port = server
    silent = socket.create_connection(("127.0.0.1", port))  # connects, never sends
    replies = []

    def real_callback():
        time.sleep(0.3)
        replies.append(_get(port, "/?code=abc123&state=expected-state"))

    callback = threading.Thread(target=real_callback, daemon=True)
    callback.start()
    started = time.monotonic()
    code = sso.wait_for_code(srv, state, timeout=8)
    elapsed = time.monotonic() - started
    silent.close()
    # wait_for_code returns the moment the server reads the code; the reply
    # lands in `replies` only after the server closes the socket, so join
    # before asserting or the check races the callback thread.
    callback.join(timeout=5)

    assert code == "abc123"
    assert elapsed < 5, f"real callback starved behind a silent peer ({elapsed:.1f}s)"
    assert replies and replies[0].startswith(b"HTTP/1.0 200")
    assert b"Login Successful" in replies[0]


def test_deadline_is_honored_with_only_a_silent_peer(server):
    srv, state, port = server
    silent = socket.create_connection(("127.0.0.1", port))
    started = time.monotonic()
    code = sso.wait_for_code(srv, state, timeout=2)
    silent.close()
    assert code is None
    assert time.monotonic() - started < 4


def test_state_mismatch_is_rejected_and_flow_continues(server):
    srv, state, port = server

    def attacker_then_user():
        time.sleep(0.2)
        assert _get(port, "/?code=EVIL&state=wrong").startswith(b"HTTP/1.0 400")
        _get(port, "/?code=GOOD&state=expected-state")

    threading.Thread(target=attacker_then_user, daemon=True).start()
    assert sso.wait_for_code(srv, state, timeout=5) == "GOOD"


def test_stray_request_without_code_is_answered_ok(server):
    srv, state, port = server
    threading.Thread(target=lambda: _get(port, "/favicon.ico"), daemon=True).start()
    assert sso.wait_for_code(srv, state, timeout=1) is None


def test_first_code_wins():
    state = sso.CallbackState("s")
    state.accept("first")
    state.accept("second")
    assert state.code == "first"
    assert state.received.is_set()


def test_handler_has_per_connection_read_timeout():
    handler = sso._make_handler(sso.CallbackState("s"))
    assert handler.timeout == sso.SSO_CALLBACK_READ_TIMEOUT_S
    assert sso.SSO_LOGIN_TIMEOUT_S >= 300


def test_falls_back_to_os_port_when_preferred_is_taken(monkeypatch):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    taken = blocker.getsockname()[1]
    monkeypatch.setattr(sso, "SSO_CALLBACK_PORT", taken)
    try:
        srv = sso.start_callback_server(sso.CallbackState("s"))
        try:
            assert srv.server_address[1] != taken
            assert srv.server_address[0] == "127.0.0.1"
        finally:
            srv.server_close()
    finally:
        blocker.close()
