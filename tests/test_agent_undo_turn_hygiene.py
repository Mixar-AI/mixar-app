# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent-turn undo hygiene (bug hunt P3).

Only the normal turn ends (stream complete / error, in-band error,
replay-unavailable, Abort) opt into the closing "Mixie Chat Turn" step; tab
close, ``load_pre`` and ``cancel_orphaned_runs`` end turns without one.
Read-only tools (``AGENT_UNDO_NEUTRAL_TOOLS``) push nothing and do not mark
the turn as having run, so a chat-only turn leaves no no-op undo steps.
Fixtures and helpers are shared with ``test_agent_undo_checkpoints``.
"""

import ast
from pathlib import Path

from test_agent_undo_checkpoints import (  # noqa: F401 (fixture re-export)
    _CHAT_ROOT,
    _CORE_ROOT,
    _MODULES_ROOT,
    _mocked_bpy,
    _undo_pushes,
    executor_module,
)


def test_neutral_tools_are_read_only_and_not_the_render_gate_set(executor_module):
    neutral = executor_module.AGENT_UNDO_NEUTRAL_TOOLS
    assert neutral == frozenset({
        "_scene_digest", "_wait_generation_poll", "_detect_views_poll",
        "_await_generation_image", "poll_generation", "get_all_queue_status",
        "list_scene_meshes", "list_rules", "list_moodboard_images",
        "get_paint_layer_stack", "get_paint_channels", "inspect_moodboard_image",
    })
    # render_scene_* are safe during a render but WRITE data: never neutral.
    assert not {"render_scene_image", "render_scene_video"} & neutral


def test_a_digest_only_turn_leaves_no_undo_step(executor_module, monkeypatch):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module)
    executor = executor_module.ScriptExecutor()
    executor.begin_agent_turn("s1")
    result = executor.execute("x = 1", session_id="s1", tool_name="_scene_digest")
    assert result.success is True, result.error
    assert executor._turns["s1"][2] is False
    executor.end_agent_turn("s1", checkpoint=True)
    assert _undo_pushes(bpy_mod) == 0


def test_neutral_then_effectful_pushes_pre_and_closing_steps(executor_module, monkeypatch):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module)
    executor = executor_module.ScriptExecutor()
    executor.begin_agent_turn("s1")
    assert executor.execute("x = 1", session_id="s1", tool_name="poll_generation").success
    assert _undo_pushes(bpy_mod) == 0
    assert executor.execute(
        "bpy.ops.mixar.probe()", session_id="s1", tool_name="execute_bpy_script"
    ).success
    assert _undo_pushes(bpy_mod) == 1
    assert bpy_mod.ops.ed.undo_push.call_args_list[0].kwargs["message"] == "Mixie Chat Script"
    executor.end_agent_turn("s1", checkpoint=True)
    assert _undo_pushes(bpy_mod) == 2
    assert bpy_mod.ops.ed.undo_push.call_args_list[-1].kwargs["message"] == "Mixie Chat Turn"


def test_render_scene_tools_still_checkpoint(executor_module, monkeypatch):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module)
    executor = executor_module.ScriptExecutor()
    executor.begin_agent_turn("s1")
    assert executor.execute("x = 1", session_id="s1", tool_name="render_scene_image").success
    assert _undo_pushes(bpy_mod) == 1
    assert executor._turns["s1"][2] is True


def test_ending_without_the_opt_in_pushes_nothing(executor_module, monkeypatch):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module)
    executor = executor_module.ScriptExecutor()
    executor.begin_agent_turn("s1")
    assert executor.execute("bpy.ops.mixar.probe()", session_id="s1").success
    assert _undo_pushes(bpy_mod) == 1
    # Tab close / cancel_orphaned_runs (inside undo_post) use the default.
    executor.end_agent_turn("s1")
    assert _undo_pushes(bpy_mod) == 1
    # The end-all form (load_pre) never pushes, even for a turn that ran.
    executor.begin_agent_turn("s2")
    assert executor.execute("bpy.ops.mixar.probe()", session_id="s2").success
    assert _undo_pushes(bpy_mod) == 2
    executor.end_agent_turn()
    assert _undo_pushes(bpy_mod) == 2
    assert executor._turns == {}


def _end_turn_calls(path: Path) -> list:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "end_agent_turn"
        ):
            flag = next((k.value for k in node.keywords if k.arg == "checkpoint"), None)
            calls.append(isinstance(flag, ast.Constant) and flag.value is True)
    return calls


def test_only_the_normal_turn_ends_opt_into_the_closing_checkpoint():
    ui_ops = _CHAT_ROOT / "ui" / "operators"
    # Complete / stream error / in-band error, replay-unavailable, Abort.
    expected_true = {
        _CORE_ROOT / "turn_events.py": 1,
        ui_ops / "session_ops.py": 1,
    }
    for path, count in expected_true.items():
        calls = _end_turn_calls(path)
        assert calls == [True] * count, path
    # queue_processor: complete, refused (the backend never started the command,
    # so nothing ran and no step is owed), stream error, in-band error.
    assert _end_turn_calls(_CORE_ROOT / "queue_processor.py") == [True, False, True, True]
    # Tab close and file load end turns without a step. cancel_orphaned_runs
    # (inside undo/redo_post) gets the bound method, so it uses the default.
    for path in (ui_ops / "scene_tab_ops.py", _CORE_ROOT / "file_handlers.py"):
        calls = _end_turn_calls(path)
        assert calls and not any(calls), path
    guard = (_CORE_ROOT / "undo_tab_guard.py").read_text(encoding="utf-8")
    assert "get_executor().end_agent_turn)" in guard


def test_pump_passes_the_tool_name_to_the_executor():
    pump = (_MODULES_ROOT / "common" / "agent_execution" / "pump.py").read_text(encoding="utf-8")
    assert "tool_name=req.tool_name" in pump
