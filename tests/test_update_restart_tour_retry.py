# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The restart prompt deferred for the onboarding tour keeps retrying for as
long as the tour runs, and re-opens only once it has ended.

The timer used to re-invoke the operator, whose own deferral found the timer
still registered (Blender drops it only after the callback returns None) and
scheduled nothing, so a tour longer than one retry lost the prompt."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock  # noqa: E402

install_bpy_mock()

from mixar.modules.common.updates.ui import operators  # noqa: E402


def test_timer_keeps_waiting_while_tour_runs(monkeypatch):
    ops = MagicMock()
    monkeypatch.setattr(operators.bpy, "ops", ops, raising=False)
    monkeypatch.setattr(operators, "tour_running", lambda: True)
    assert operators._reinvoke_restart_prompt() == operators.TOUR_RETRY_SECONDS
    ops.mixar.restart_to_update.assert_not_called()


def test_timer_reopens_prompt_once_tour_ends(monkeypatch):
    ops = MagicMock()
    context = MagicMock()
    context.window_manager.windows = []
    monkeypatch.setattr(operators.bpy, "ops", ops, raising=False)
    monkeypatch.setattr(operators.bpy, "context", context, raising=False)
    monkeypatch.setattr(operators, "tour_running", lambda: False)
    assert operators._reinvoke_restart_prompt() is None
    ops.mixar.restart_to_update.assert_called_once_with("INVOKE_DEFAULT")
