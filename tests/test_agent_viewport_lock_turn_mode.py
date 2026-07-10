# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for the agent viewport lock's mode gating.

The halo + input block must key off the mode the RUNNING turn was
started in (``mixie_chat_active_turn_mode``, stamped by
``SessionManager.set_state``), not the live ``mixie_chat_mode``
dropdown — the dropdown stays editable mid-turn, and flipping it
AGENT → ASK → AGENT used to drop the lock while the agent was still
editing the scene, letting the user select objects out from under it.
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

from mixar.modules.agent_viewport_lock.core.state_probe import is_agent_executing
from mixar.modules.space_mixie_chat.constants import SessionState
from mixar.modules.space_mixie_chat.core.session import SessionManager


class FakeScene:
    """Minimal stand-in for bpy.types.Scene with the chat properties."""

    def __init__(self, mode="AGENT"):
        self.name = "Scene"
        self.mixie_chat_state = "OFFLINE"
        self.mixie_chat_is_busy = False
        self.mixie_chat_mode = mode
        self.mixie_chat_active_turn_mode = ""


@pytest.fixture(autouse=True)
def _reset_session_manager():
    SessionManager.reset()
    yield
    SessionManager.reset()


def test_turn_mode_stamped_on_turn_start_and_cleared_on_end():
    scene = FakeScene(mode="AGENT")
    SessionManager.set_state(scene, SessionState.IDLE)
    assert scene.mixie_chat_active_turn_mode == ""

    SessionManager.set_state(scene, SessionState.BUSY)
    assert scene.mixie_chat_active_turn_mode == "AGENT"

    # Intra-turn transitions keep the stamp, even if the dropdown moved.
    scene.mixie_chat_mode = "ASK"
    SessionManager.set_state(scene, SessionState.AWAITING_INPUT)
    assert scene.mixie_chat_active_turn_mode == "AGENT"
    SessionManager.set_state(scene, SessionState.BUSY)
    assert scene.mixie_chat_active_turn_mode == "AGENT"

    SessionManager.set_state(scene, SessionState.IDLE)
    assert scene.mixie_chat_active_turn_mode == ""


def test_lock_survives_agent_to_ask_to_agent_dropdown_flip():
    """The reported bug: flipping the mode dropdown to ASK and back
    mid-run dropped the halo + input block while the agent turn was
    still executing."""
    scene = FakeScene(mode="AGENT")
    SessionManager.set_state(scene, SessionState.BUSY)
    assert is_agent_executing(scene)

    scene.mixie_chat_mode = "ASK"
    assert is_agent_executing(scene), "lock must hold after flipping to ASK mid-turn"

    scene.mixie_chat_mode = "AGENT"
    assert is_agent_executing(scene), "lock must hold after flipping back to AGENT"

    SessionManager.set_state(scene, SessionState.IDLE)
    assert not is_agent_executing(scene)


def test_ask_turn_never_locks_even_if_dropdown_flipped_to_agent():
    scene = FakeScene(mode="ASK")
    SessionManager.set_state(scene, SessionState.BUSY)
    assert not is_agent_executing(scene)

    # Flipping the dropdown to AGENT while the Ask turn streams must not
    # spuriously raise the halo / input block.
    scene.mixie_chat_mode = "AGENT"
    assert not is_agent_executing(scene)


def test_probe_still_requires_an_executing_state():
    scene = FakeScene(mode="AGENT")
    SessionManager.set_state(scene, SessionState.BUSY)
    SessionManager.set_state(scene, SessionState.AWAITING_INPUT)
    # Paused for the user — stamp is held but the lock must lift.
    assert scene.mixie_chat_active_turn_mode == "AGENT"
    assert not is_agent_executing(scene)


def test_probe_handles_scenes_without_the_property():
    class BareScene:
        name = "Scene"
        mixie_chat_state = "BUSY"

    assert not is_agent_executing(BareScene())
