# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests: a transient WebSocket drop must not kill a running turn.

The agent turn streams over its own SSE/HTTP connection and the backend keeps
executing through a WS blip; the WS client auto-reconnects within seconds.
``on_disconnected`` used to set EVERY scene to OFFLINE, which cleared
``SessionManager._active_scenes`` — so after the silent reconnect the client
refused every backend script with "Agent session not active" while the status
pill showed Connected/idle, and the backend ground whole build waves against
those refusals (backend trace b0c909ab: six parallel modeling.primitives
lanes failing every capture and workspace merge for minutes).

The policy under test is ``SessionManager.on_transport_disconnect``:
- transient drop → only IDLE/CONNECTING downgrade to OFFLINE; the active
  turn states (BUSY / MODIFYING / AWAITING_INPUT) survive, so the script
  gate (``has_active_session``) stays open across the reconnect;
- terminal drop (auth failure, reconnection stopped) → everything OFFLINE.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

import pytest

from mixar.modules.space_mixie_chat.constants import SessionState
from mixar.modules.space_mixie_chat.core.session import SessionManager


def _set_scenes(scenes):
    """Point the CURRENT bpy mock's data.scenes at our fakes.

    install_bpy_mock() replaces sys.modules["bpy"] every time another test
    module calls it, and session.py resolves ``import bpy`` at call time —
    so a module-level ``import bpy`` here would write scenes onto a stale
    mock when the whole suite runs together."""
    sys.modules["bpy"].data.scenes = scenes


class FakeScene:
    """Minimal stand-in for bpy.types.Scene with the chat properties."""

    def __init__(self, name="Scene"):
        self.name = name
        self.mixie_chat_state = "OFFLINE"
        self.mixie_chat_is_busy = False
        self.mixie_chat_mode = "AGENT"
        self.mixie_chat_active_turn_mode = ""


@pytest.fixture(autouse=True)
def _reset_session_manager():
    SessionManager.reset()
    yield
    SessionManager.reset()


def _reconnect():
    """What connection_manager.on_connected applies after the WS comes back."""
    SessionManager.set_all_scenes_state(
        SessionState.IDLE,
        only_from={SessionState.OFFLINE, SessionState.CONNECTING},
    )


def test_transient_disconnect_preserves_running_turn():
    chat = FakeScene("Scene")
    other = FakeScene("Other")
    _set_scenes([chat, other])

    SessionManager.set_state(chat, SessionState.BUSY)
    SessionManager.set_state(other, SessionState.IDLE)
    assert SessionManager.has_active_session()

    SessionManager.on_transport_disconnect(terminal=False)

    # The running turn survives the blip; the idle scene shows offline.
    assert SessionManager.get_state(chat) == SessionState.BUSY
    assert SessionManager.get_state(other) == SessionState.OFFLINE
    assert SessionManager.has_active_session(), (
        "script gate must stay open — the backend keeps sending scripts "
        "after the silent reconnect"
    )

    # The reconnect only promotes OFFLINE/CONNECTING to IDLE — the turn's
    # BUSY state is untouched and scripts keep executing.
    _reconnect()
    assert SessionManager.get_state(chat) == SessionState.BUSY
    assert SessionManager.get_state(other) == SessionState.IDLE
    assert SessionManager.has_active_session()


@pytest.mark.parametrize(
    "active_state",
    [SessionState.BUSY, SessionState.MODIFYING, SessionState.AWAITING_INPUT],
)
def test_every_active_state_survives_transient_disconnect(active_state):
    chat = FakeScene("Scene")
    _set_scenes([chat])

    SessionManager.set_state(chat, active_state)
    SessionManager.on_transport_disconnect(terminal=False)

    assert SessionManager.get_state(chat) == active_state
    assert SessionManager.has_active_session()


def test_terminal_disconnect_wipes_everything():
    chat = FakeScene("Scene")
    other = FakeScene("Other")
    _set_scenes([chat, other])

    SessionManager.set_state(chat, SessionState.BUSY)
    SessionManager.set_state(other, SessionState.IDLE)

    # Auth failure — reconnection stopped, no turn can continue.
    SessionManager.on_transport_disconnect(terminal=True)

    assert SessionManager.get_state(chat) == SessionState.OFFLINE
    assert SessionManager.get_state(other) == SessionState.OFFLINE
    assert not SessionManager.has_active_session()


def test_connecting_scene_downgrades_on_transient_disconnect():
    connecting = FakeScene("Scene")
    _set_scenes([connecting])

    SessionManager.set_state(connecting, SessionState.CONNECTING)
    SessionManager.on_transport_disconnect(terminal=False)

    assert SessionManager.get_state(connecting) == SessionState.OFFLINE
    assert not SessionManager.has_active_session()


def test_auth_failure_reason_constant_matches_client():
    """connection_manager compares the callback reason against the constant;
    jsonrpc_client must emit exactly that string for terminal disconnects."""
    from mixar.modules.space_mixie_chat.constants import (
        DISCONNECT_REASON_AUTH_FAILED,
    )

    assert DISCONNECT_REASON_AUTH_FAILED == (
        "Authentication failed - please login again"
    )
