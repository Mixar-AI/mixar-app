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
SSE_HANDLER = (
    ROOT
    / "src/scripts/mixar/modules/space_mixie_chat/core/sse_handler.py"
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


def test_pre_request_connection_failures_retry_for_chat_and_input():
    source = SSE_HANDLER.read_text(encoding="utf-8")
    constants = CONSTANTS.read_text(encoding="utf-8")

    assert "SSE_CONNECT_RETRY_DELAYS = (1.0, 2.0, 4.0, 8.0, 15.0)" in constants
    assert 'self._retry_connect_error("Chat", _connect_attempt, e)' in source
    assert 'self._retry_connect_error("Input", _connect_attempt, e)' in source
    assert "except httpx.ConnectError" in source


def test_ambiguous_stream_failures_are_not_automatically_retried():
    source = SSE_HANDLER.read_text(encoding="utf-8")

    timeout_block = source[source.index("except httpx.TimeoutException") :]
    assert "_retry_connect_error" not in timeout_block.split(
        "except Exception", 1
    )[0]


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
    client = JSONRPC_CLIENT.read_text(encoding="utf-8")

    assert "WS_LIVENESS_TIMEOUT = 45.0" in constants
    assert "self._last_recv_time = time.time()" in client
    assert "time.time() - self._last_recv_time > WS_LIVENESS_TIMEOUT" in client


def test_mid_stream_loss_reattaches_instead_of_failing_the_turn():
    """An accepted stream that dies mid-turn must re-attach (idempotent
    replay) — re-POSTing would duplicate the turn, and failing it loses the
    response the backend keeps producing in its disconnect drain."""
    source = SSE_HANDLER.read_text(encoding="utf-8")

    assert 'self._resume_via_attach("Chat")' in source
    assert 'self._resume_via_attach("Input")' in source
    # _consume_sse_stream reports the outcome instead of firing _on_error
    # itself, so stream loops can choose attach over turn failure.
    consume = source[source.index("def _consume_sse_stream") :]
    consume = consume.split("def _process_sse_line", 1)[0]
    assert "_on_error" not in consume
    assert 'return "lost"' in consume


def test_replayed_events_are_deduplicated_by_seq():
    """Attach replays overlap what was already rendered; the per-session
    monotonic seq the backend stamps on every payload is the dedup key.
    A fresh turn resets it, an input stream continues it."""
    source = SSE_HANDLER.read_text(encoding="utf-8")

    assert "if seq <= self._last_seq:" in source

    def _method(name: str) -> str:
        block = source[source.index(f"def {name}") :]
        return block.split("def ", 2)[1]

    assert "self._last_seq = -1" in _method("start_stream")
    assert "self._last_seq = -1" not in _method("start_input_stream")


def test_status_pill_reflects_transport_loss_during_active_turn():
    """Session state deliberately preserves BUSY across a WS drop (resumed
    tool calls must not be rejected), so the pill must derive 'Reconnecting'
    from transport liveness or it shows 'Running' while disconnected."""
    header = BUBBLE_HEADER.read_text(encoding="utf-8")

    assert "_transport_down" in header
    assert '"Reconnecting"' in header
