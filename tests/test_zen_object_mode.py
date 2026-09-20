# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Entering Zen Mode always lands in Object Mode.

Zen's viewport header has no mode selector, so a user who switches from
Edit/Sculpt/Texture Paint would be stranded. The bootstrap's workspace
reset timer must cover the Zen workspace, be re-armed by the Zen operator
itself, and run after a file loads straight into Zen.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mixar.bootstrap import workflow_module
from mixar.modules.workflow.constants import BASIC_WORKSPACE_NAME
from mixar.modules.workflow.ui.operators import ui_mode_ops

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def reset_state():
    workflow_module._object_mode_done = False
    workflow_module._object_mode_retry_count = 0
    yield
    workflow_module._object_mode_done = False
    workflow_module._object_mode_retry_count = 0


def _context(workspace_name, mode):
    return SimpleNamespace(
        window=SimpleNamespace(workspace=SimpleNamespace(name=workspace_name)),
        object=SimpleNamespace(mode=mode),
    )


@pytest.mark.parametrize("mode", ["EDIT", "SCULPT", "TEXTURE_PAINT"])
def test_zen_workspace_resets_to_object_mode(monkeypatch, reset_state, mode):
    mode_set = MagicMock()
    monkeypatch.setattr(workflow_module.bpy, "context", _context(BASIC_WORKSPACE_NAME, mode))
    monkeypatch.setattr(workflow_module.bpy, "ops", SimpleNamespace(object=SimpleNamespace(mode_set=mode_set)))

    assert workflow_module._ensure_modeling_workspace_object_mode() is None

    mode_set.assert_called_once_with(mode="OBJECT")
    assert workflow_module._object_mode_done is True


def test_zen_workspace_already_in_object_mode_is_left_alone(monkeypatch, reset_state):
    mode_set = MagicMock()
    monkeypatch.setattr(workflow_module.bpy, "context", _context(BASIC_WORKSPACE_NAME, "OBJECT"))
    monkeypatch.setattr(workflow_module.bpy, "ops", SimpleNamespace(object=SimpleNamespace(mode_set=mode_set)))

    workflow_module._ensure_modeling_workspace_object_mode()

    mode_set.assert_not_called()


def test_other_workspaces_keep_their_mode(monkeypatch, reset_state):
    mode_set = MagicMock()
    monkeypatch.setattr(workflow_module.bpy, "context", _context("Texturing", "TEXTURE_PAINT"))
    monkeypatch.setattr(workflow_module.bpy, "ops", SimpleNamespace(object=SimpleNamespace(mode_set=mode_set)))

    assert workflow_module._ensure_modeling_workspace_object_mode() is None

    mode_set.assert_not_called()


def test_zen_workspace_retries_until_an_active_object_exists(monkeypatch, reset_state):
    context = SimpleNamespace(
        window=SimpleNamespace(workspace=SimpleNamespace(name=BASIC_WORKSPACE_NAME)),
        object=None,
    )
    monkeypatch.setattr(workflow_module.bpy, "context", context)

    assert workflow_module._ensure_modeling_workspace_object_mode() == 0.2
    assert workflow_module._object_mode_done is False


def test_zen_operator_arms_the_object_mode_reset(monkeypatch):
    armed = MagicMock()
    monkeypatch.setattr(workflow_module, "_schedule_object_mode_reset", armed)

    ui_mode_ops._schedule_object_mode()

    armed.assert_called_once_with()


def test_zen_operator_schedules_after_the_workspace_switch():
    src = (ROOT / "src/scripts/mixar/modules/workflow/ui/operators/ui_mode_ops.py").read_text()
    start = src.index("class MIXAR_OT_set_ui_mode_ai")
    body = src[start:src.index("\nclass ", start + 1)]
    assert body.index("_force_workspace_rebuild(target)") < body.index("_schedule_object_mode()")


def test_file_load_into_zen_arms_the_object_mode_reset(monkeypatch):
    armed = MagicMock()
    monkeypatch.setattr(workflow_module, "_schedule_object_mode_reset", armed)
    monkeypatch.setattr(workflow_module, "configure_basic_workspace_chrome", MagicMock())

    workflow_module._on_load_post(None)

    armed.assert_called_once_with()
