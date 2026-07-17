# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the fast transport-liveness signal (is_transport_live).

A silently dead TCP connection (wifi off, sleep/resume) keeps
``is_connected`` True until the WS_LIVENESS_TIMEOUT teardown watchdog —
sends still land in the kernel buffer, only recv starvation reveals the
death. The status surfaces (bubble pill, chat header) therefore read
``is_transport_live``, which trips on WS_UI_STALE_THRESHOLD of recv
silence, so the UI stops claiming "Connected" within seconds of a
network drop instead of after 45s (or never repainting at all).
"""

# Install bpy mock before any mixar imports
import sys, os
from unittest.mock import MagicMock

_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

# connection_manager pulls in auth (keyring) and bpy at import time; stub
# both so the test runs in a regular Python process (same pattern as
# test_auth_refresh.py).
for _name in (
    "bpy",
    "bpy.types",
    "bpy.props",
    "bpy.utils",
    "bpy.app",
    "bpy.app.timers",
    "bpy.context",
    "bpy.data",
    "bpy.ops",
    "bpy.ops.mixar",
    "keyring",
):
    sys.modules.setdefault(_name, MagicMock(name=_name))

import time
import unittest

from mixar.modules.space_mixie_chat.constants import (
    DEFAULT_PING_INTERVAL,
    WS_LIVENESS_TIMEOUT,
    WS_UI_STALE_THRESHOLD,
)
from mixar.modules.space_mixie_chat.core.jsonrpc_client import (
    JSONRPCWebSocketClient,
)


def _make_client() -> JSONRPCWebSocketClient:
    return JSONRPCWebSocketClient(
        host="https://example.invalid",
        connection_id="test-conn",
    )


class TestThresholdOrdering(unittest.TestCase):
    """The three timing constants only work in this exact order."""

    def test_ui_threshold_sits_between_ping_and_teardown(self):
        # Below the ping interval every healthy connection would flap;
        # above the teardown watchdog the fast signal would never fire
        # before the socket is torn down anyway.
        self.assertGreater(WS_UI_STALE_THRESHOLD, DEFAULT_PING_INTERVAL)
        self.assertLess(WS_UI_STALE_THRESHOLD, WS_LIVENESS_TIMEOUT)


class TestIsTransportLive(unittest.TestCase):
    def test_false_before_connect(self):
        client = _make_client()
        self.assertFalse(client.is_transport_live)

    def test_false_without_handshake(self):
        client = _make_client()
        client._connected = True
        client._handshake_complete = False
        client._last_recv_time = time.time()
        self.assertFalse(client.is_transport_live)

    def test_true_with_recent_traffic(self):
        client = _make_client()
        client._connected = True
        client._handshake_complete = True
        client._last_recv_time = time.time()
        self.assertTrue(client.is_transport_live)
        self.assertTrue(client.is_connected)

    def test_false_on_recv_starvation_while_is_connected_stays_true(self):
        """The bug this signal exists for: zombie socket after a network
        drop — is_connected still True, but nothing received for longer
        than the UI staleness threshold."""
        client = _make_client()
        client._connected = True
        client._handshake_complete = True
        client._last_recv_time = time.time() - (WS_UI_STALE_THRESHOLD + 1.0)
        self.assertTrue(client.is_connected)
        self.assertFalse(client.is_transport_live)

    def test_boundary_just_inside_threshold_is_live(self):
        client = _make_client()
        client._connected = True
        client._handshake_complete = True
        client._last_recv_time = time.time() - (WS_UI_STALE_THRESHOLD - 2.0)
        self.assertTrue(client.is_transport_live)


class TestConnectionManagerProperty(unittest.TestCase):
    def test_no_client_means_not_live(self):
        from mixar.modules.space_mixie_chat.core import connection_manager as cm
        from mixar.modules.space_mixie_chat.core import jsonrpc_client as jc

        # Ensure no global client is registered.
        old = jc._jsonrpc_client
        jc._jsonrpc_client = None
        try:
            manager = cm.get_connection_manager()
            self.assertFalse(manager.is_transport_live)
        finally:
            jc._jsonrpc_client = old

    def test_delegates_to_client(self):
        from mixar.modules.space_mixie_chat.core import connection_manager as cm
        from mixar.modules.space_mixie_chat.core import jsonrpc_client as jc

        client = _make_client()
        client._connected = True
        client._handshake_complete = True
        client._last_recv_time = time.time()

        old = jc._jsonrpc_client
        jc._jsonrpc_client = client
        try:
            manager = cm.get_connection_manager()
            self.assertTrue(manager.is_transport_live)
            # Starve recv past the UI threshold: display signal flips while
            # the send-gating signal is untouched.
            client._last_recv_time = time.time() - (WS_UI_STALE_THRESHOLD + 1.0)
            self.assertFalse(manager.is_transport_live)
            self.assertTrue(manager.is_connected)
        finally:
            jc._jsonrpc_client = old


if __name__ == "__main__":
    unittest.main()
