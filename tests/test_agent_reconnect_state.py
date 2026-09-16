# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Regression coverage for active agent turns across transient WS loss."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANAGER = (
    ROOT
    / "src/scripts/mixar/modules/space_mixie_chat/core/connection_manager.py"
)
CONSTANTS = (
    ROOT
    / "src/scripts/mixar/modules/space_mixie_chat/constants.py"
)


def _callback_block(source: str, start: str, end: str) -> str:
    offset = source.index(start)
    return source[offset : source.index(end, offset)]


def test_disconnect_preserves_active_turn_state_via_transport_hook():
    source = MANAGER.read_text(encoding="utf-8")
    block = _callback_block(
        source,
        "        def on_disconnected(reason: str):",
        "        def on_script_execute",
    )

    assert "terminal = reason == DISCONNECT_REASON_AUTH_FAILED" in block
    assert "session.on_transport_disconnect(terminal=terminal)" in block
    assert "set_all_scenes_state" not in block


def test_reconnect_does_not_overwrite_active_turn_state():
    source = MANAGER.read_text(encoding="utf-8")
    block = _callback_block(
        source,
        "        def on_connected():",
        "        def on_disconnected",
    )

    assert "only_from={SessionState.OFFLINE, SessionState.CONNECTING}" in block






JSONRPC_CLIENT = (
    ROOT
    / "src/scripts/mixar/modules/space_mixie_chat/core/jsonrpc_client.py"
)
BUBBLE_HEADER = (
    ROOT
    / "src/scripts/mixar/modules/agent_bubble/ui/header.py"
)


def test_ws_zombie_connections_are_detected_via_recv_liveness():
    """A silent network drop leaves sends 'succeeding' into the kernel
    buffer forever; only recv starvation reveals it. Without this the UI
    never learns the transport died and no reconnect ever happens."""
    constants = CONSTANTS.read_text(encoding="utf-8")
    client = "\n".join((JSONRPC_CLIENT.parent / name).read_text(encoding="utf-8") for name in ("jsonrpc_client.py", "socket_connection.py", "socket_dispatch.py", "socket_requests.py"))

    assert "WS_LIVENESS_TIMEOUT = 45.0" in constants
    assert "self._last_recv_time = time.time()" in client
    assert "time.time() - self._last_recv_time > WS_LIVENESS_TIMEOUT" in client






def test_status_pill_reflects_transport_loss_during_active_turn():
    """Session state deliberately preserves BUSY across a WS drop (resumed
    tool calls must not be rejected), so the pill must derive 'Reconnecting'
    from transport liveness or it shows 'Running' while disconnected."""
    header = BUBBLE_HEADER.read_text(encoding="utf-8")

    assert "_transport_down" in header
    assert '"Reconnecting"' in header


def test_agent_has_no_http_streaming_fallback():
    core = MANAGER.parent
    assert not (core / 'sse_handler.py').exists()
    for name in ('turn_transport.py', 'composer_send.py', 'turn_events.py'):
        source = (core / name).read_text()
        assert 'import httpx' not in source and 'import requests' not in source
