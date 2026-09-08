# SPDX-License-Identifier: GPL-3.0-or-later
"""Atomic script failure injection; real Blender coverage lives in tests/bpy/."""

import importlib
import sys
from unittest.mock import MagicMock

import pytest
from test_script_executor_safe_modules import _load_executor_module


@pytest.fixture
def executor(monkeypatch):
    for name in ("bmesh", "mathutils", "bpy_extras", "imbuf"):
        monkeypatch.setitem(sys.modules, name, MagicMock(name=name))
    return _load_executor_module(monkeypatch).ScriptExecutor()


@pytest.fixture
def atomic(executor):
    module = importlib.import_module(
        "mixar.modules.space_mixie_chat.core.atomic_script"
    )
    module.bpy.context.mode = "OBJECT"
    module.bpy.context.preferences.edit.use_global_undo = True
    module.bpy.ops.ed.undo_push.return_value = {"FINISHED"}
    module.bpy.ops.ed.undo.return_value = {"FINISHED"}
    module.bpy.ops.mesh.primitive_cube_add.return_value = {"FINISHED"}
    module.bpy.ops.ed.undo.reset_mock()
    module.bpy.ops.ed.undo_push.reset_mock()
    module.bpy.ops.mesh.primitive_cube_add.reset_mock()
    return module


def test_multiple_mutations_rollback_once(executor, atomic):
    result = executor.execute(
        "bpy.ops.mesh.primitive_cube_add()\nbpy.ops.mesh.primitive_cube_add()\nraise ValueError('fault')",
        atomic=True,
    )
    assert not result.success
    assert result.rollback == "restored"
    assert atomic.bpy.ops.ed.undo_push.call_count == 2
    atomic.bpy.ops.ed.undo.assert_called_once()
    atomic.bpy.ops.mesh.primitive_cube_add.assert_called_with("EXEC_DEFAULT", False)


def test_operator_cancelled_is_failure(executor, atomic):
    atomic.bpy.ops.mesh.primitive_cube_add.return_value = {"CANCELLED"}
    result = executor.execute("bpy.ops.mesh.primitive_cube_add()", atomic=True)
    assert not result.success
    assert result.rollback == "restored"


def test_cannot_mutate_without_checkpoint(executor, atomic):
    atomic.bpy.context.preferences.edit.use_global_undo = False
    result = executor.execute("bpy.ops.mesh.primitive_cube_add()", atomic=True)
    assert not result.success
    assert result.rollback == "not_started"
    atomic.bpy.ops.mesh.primitive_cube_add.assert_not_called()
    assert not executor._execution_lock.locked()


def test_explicit_result_failure_cannot_override_transaction(executor, atomic):
    result = executor.execute(
        "print('__RESULT__' + json.dumps({'success': False, 'error': 'no change'}))",
        atomic=True,
    )
    assert not result.success
    assert result.rollback == "restored"


def test_addon_import_cannot_bypass_atomic_ops(executor, atomic):
    result = executor.execute(
        "import mixar.modules.space_mixie_chat.core.atomic_script", atomic=True
    )
    assert not result.success
    assert result.rollback == "not_started"


def test_rollback_failure_is_honest(executor, atomic):
    atomic.bpy.ops.ed.undo.return_value = {"CANCELLED"}
    result = executor.execute("raise ValueError('fault')", atomic=True)
    assert not result.success
    assert result.rollback == "failed"
    assert "rollback failed" in result.error


def test_swallowed_cancel_still_rolls_back(executor, atomic):
    atomic.bpy.ops.mesh.primitive_cube_add.return_value = {"CANCELLED"}
    result = executor.execute(
        "try:\n    bpy.ops.mesh.primitive_cube_add()\nexcept RuntimeError:\n    pass",
        atomic=True,
    )
    assert not result.success
    assert result.rollback == "restored"


def test_scratchpad_is_session_scoped_and_invalidated(monkeypatch):
    module = importlib.import_module("mixar.modules.space_mixie_chat.core.scratchpad")
    monkeypatch.setattr(module.bpy.app.handlers, "undo_post", [])
    monkeypatch.setattr(module.bpy.app.handlers, "load_pre", [])
    module.clear_scratchpads()
    module.scratchpad("one")["index"] = [1, 2]
    assert module.scratchpad("two") == {}
    assert module.scratchpad("one")["index"] == [1, 2]
    module.bpy.app.handlers.undo_post[0]()
    assert module.scratchpad("one") == {}
    module.scratchpad("two")["index"] = [3]
    module.bpy.app.handlers.load_pre[0]()
    assert module.scratchpad("two") == {}
