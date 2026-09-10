# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Viewport lock and manual-capture rules for v3 FOREGROUND tasks.

During a v3 run the lock stands down and manual edits are captured — except
while a foreground-class task is bound (agent scripts running live on this
scene), when both behave exactly like a legacy agent turn.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "scripts"))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)
for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.agent_viewport_lock.core import state_probe  # noqa: E402
from mixar.modules.common.agent_execution import document  # noqa: E402
from mixar.modules.operation_history.core import capture_service  # noqa: E402
from mixar.modules.space_mixie_chat.constants import SessionState  # noqa: E402


@pytest.fixture
def v3_run(monkeypatch):
    document.clear_foreground_tasks()
    monkeypatch.setattr(document, "run_active", lambda: True)
    yield
    document.clear_foreground_tasks()


def _agent_scene(state="BUSY"):
    return SimpleNamespace(mixie_chat_active_turn_mode="AGENT", mixie_chat_state=state)


def test_lock_stands_up_only_while_a_foreground_task_is_bound(v3_run):
    scene = _agent_scene()
    assert state_probe.is_agent_executing(scene) is False
    document.set_foreground_task("r1", "t1", True)
    assert state_probe.is_agent_executing(scene) is True
    document.set_foreground_task("r1", "t1", False)
    assert state_probe.is_agent_executing(scene) is False


def test_lock_ignores_foreground_flag_outside_a_v3_run(monkeypatch):
    document.clear_foreground_tasks()
    monkeypatch.setattr(document, "run_active", lambda: False)
    document.set_foreground_task("r1", "t1", True)
    try:
        # Legacy rule: AGENT turn + BUSY locks; IDLE does not.
        assert state_probe.is_agent_executing(_agent_scene("BUSY")) is True
        assert state_probe.is_agent_executing(_agent_scene("IDLE")) is False
    finally:
        document.clear_foreground_tasks()


def test_capture_suppressed_during_foreground_task(v3_run):
    assert capture_service.should_capture(SessionState.BUSY) is True
    document.set_foreground_task("r1", "t1", True)
    assert capture_service.should_capture(SessionState.BUSY) is False
    assert capture_service.should_capture(SessionState.MODIFYING) is False
    document.set_foreground_task("r1", "t1", False)
    assert capture_service.should_capture(SessionState.BUSY) is True
    with document.commit_scope():
        assert capture_service.should_capture(SessionState.BUSY) is False
    assert capture_service.should_capture(SessionState.IDLE) is True
