# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The verification render and read-only tools skip the executor's scene diff.

``render_viewport`` (the final render and the inspection preview) renders a
worker snapshot or a private scene copy, so it changes nothing in the user's
document. Every agent script used to walk every object and its animation
twice on the main thread (``_capture_scene_state``, the top Python stack of
the stall log at 0.5 s and more per walk on animated scenes) and push a
memfile undo checkpoint before it ran, even for a render. Fixtures are shared
with ``test_agent_undo_checkpoints``.
"""

from test_agent_undo_checkpoints import (  # noqa: F401 (fixture re-export)
    _mocked_bpy,
    _undo_pushes,
    executor_module,
)


def _count_captures(executor, monkeypatch):
    calls = []
    original = executor._capture_scene_state

    def counted():
        calls.append(1)
        return original()

    monkeypatch.setattr(executor, "_capture_scene_state", counted)
    return calls


def test_render_viewport_is_a_render_tool_and_not_read_only(executor_module):
    assert executor_module.AGENT_RENDER_TOOLS == frozenset({"render_viewport"})
    # The native fallback adds a private scene copy: it must stay out of the
    # read-only contract the render gate and the undo-neutral set share.
    assert "render_viewport" not in executor_module.AGENT_UNDO_NEUTRAL_TOOLS


def test_a_render_skips_the_scene_diff_the_undo_push_and_the_turn_mark(executor_module, monkeypatch):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module)
    executor = executor_module.ScriptExecutor()
    captures = _count_captures(executor, monkeypatch)
    executor.begin_agent_turn("s1")
    result = executor.execute("x = 1", session_id="s1", tool_name="render_viewport")
    assert result.success is True, result.error
    assert captures == []
    assert _undo_pushes(bpy_mod) == 0
    assert executor._turns["s1"][2] is False
    assert result.created_objects == [] and result.modified_objects == []
    executor.end_agent_turn("s1", checkpoint=True)
    assert _undo_pushes(bpy_mod) == 0


def test_read_only_tools_skip_the_scene_diff(executor_module, monkeypatch):
    _mocked_bpy(monkeypatch, executor_module)
    executor = executor_module.ScriptExecutor()
    captures = _count_captures(executor, monkeypatch)
    for tool in sorted(executor_module.AGENT_UNDO_NEUTRAL_TOOLS):
        assert executor.execute("x = 1", session_id="s1", tool_name=tool).success, tool
    assert captures == []


def test_an_effectful_script_still_takes_both_snapshots(executor_module, monkeypatch):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module)
    executor = executor_module.ScriptExecutor()
    captures = _count_captures(executor, monkeypatch)
    assert executor.execute("x = 1", session_id="s1", tool_name="execute_bpy_script").success
    assert len(captures) == 2
    assert _undo_pushes(bpy_mod) == 1
