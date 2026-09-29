# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Undo checkpoints for agent-executed scripts.

Agent scripts run from a bpy.app.timers tick (no window in the context) and
``ed.undo_push`` polls for a window + screen, so the bare push used to fail
and be silently swallowed: an agent turn got NO undo checkpoint at all. The
executor now retries inside a borrowed window and governs the result:

- per-script checkpoints by default, capped at
  ``AGENT_UNDO_MAX_CHECKPOINTS_PER_TURN`` per turn so a long turn cannot evict
  the pre-turn state from Blender's (32-step default) undo stack;
- ``AGENT_UNDO_GROUP_PER_TURN`` collapses a turn to one checkpoint;
- the first push of a turn happens BEFORE the first script runs (that is the
  pre-turn state), a failed push never aborts the script, is not counted, and
  is logged once per turn;
- turn boundaries are wired in the stream pipeline (begin on the first
  streamed event, end on complete/error/abort/file-load).
"""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

_SRC_ROOT = Path(__file__).parents[1] / "src" / "scripts"
_MIXAR_ROOT = _SRC_ROOT / "mixar"
_MODULES_ROOT = _MIXAR_ROOT / "modules"
_CHAT_ROOT = _MODULES_ROOT / "space_mixie_chat"
_CORE_ROOT = _CHAT_ROOT / "core"


def _load_executor_module(monkeypatch):
    packages = (
        ("mixar", _MIXAR_ROOT),
        ("mixar.modules", _MODULES_ROOT),
        ("mixar.modules.space_mixie_chat", _CHAT_ROOT),
        ("mixar.modules.space_mixie_chat.core", _CORE_ROOT),
    )
    for name, path in packages:
        package = ModuleType(name)
        package.__path__ = [str(path)]
        monkeypatch.setitem(sys.modules, name, package)

    module_name = "mixar.modules.space_mixie_chat.core.executor"
    spec = importlib.util.spec_from_file_location(module_name, _CORE_ROOT / "executor.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def executor_module(monkeypatch):
    for module_name in ("bmesh", "mathutils", "bpy_extras", "imbuf"):
        monkeypatch.setitem(sys.modules, module_name, MagicMock(name=module_name))
    return _load_executor_module(monkeypatch)


def _mocked_bpy(monkeypatch, executor_module, **kwargs):
    bpy_mod = MagicMock(name="bpy")
    if "undo_side_effect" in kwargs:
        bpy_mod.ops.ed.undo_push.side_effect = kwargs["undo_side_effect"]
    bpy_mod.context.window_manager.windows = kwargs.get("windows", [])
    monkeypatch.setattr(executor_module, "bpy", bpy_mod)
    return bpy_mod


def _undo_pushes(bpy_mod) -> int:
    return bpy_mod.ops.ed.undo_push.call_count


# --------------------------------------------------------------------------- #
#  Defaults and the decision helper
# --------------------------------------------------------------------------- #


def test_default_is_one_checkpoint_per_turn_with_a_cap_under_blenders_stack(executor_module):
    # One checkpoint per turn (2026-09-29): a mid-turn checkpoint of an
    # orchestrated turn holds a worker lane and a pre-merge object set; undoing
    # to it resurrected the lane and crashed the depsgraph on the replaced
    # objects. The pre-turn state is the only step a turn leaves.
    assert executor_module.AGENT_UNDO_GROUP_PER_TURN is True
    cap = executor_module.AGENT_UNDO_MAX_CHECKPOINTS_PER_TURN
    # Blender keeps 32 undo steps by default; the cap must leave room for the
    # pre-turn checkpoint to survive a whole turn.
    assert 0 < cap < 32


def _window(scene_session: str = ""):
    return MagicMock(scene=MagicMock(mixie_session_id=scene_session))


def test_no_checkpoint_while_the_window_is_pinned_to_a_worker_lane(executor_module, monkeypatch):
    # The routing pin of a workspace script has the window on the lane scene;
    # a memfile step written then records the lane as the current scene, and
    # an undo landing on it puts the user inside the lane. Skipped, uncounted:
    # the next MAIN-pinned script pushes the turn's checkpoint instead.
    bpy_mod = _mocked_bpy(monkeypatch, executor_module,
                          windows=[_window("agentlane:abc")])
    executor = executor_module.ScriptExecutor()
    executor.begin_agent_turn()
    assert executor.execute("bpy.ops.mixar.probe()").success is True
    assert _undo_pushes(bpy_mod) == 0
    bpy_mod.context.window_manager.windows = [_window("tab-session")]
    assert executor.execute("bpy.ops.mixar.probe()").success is True
    assert _undo_pushes(bpy_mod) == 1
    assert executor.execute("bpy.ops.mixar.probe()").success is True
    assert _undo_pushes(bpy_mod) == 1


def test_lane_probe_fails_open(executor_module, monkeypatch):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module)
    type(bpy_mod.context.window_manager).windows = property(lambda self: (_ for _ in ()).throw(RuntimeError("no wm")))
    executor = executor_module.ScriptExecutor()
    assert executor._window_on_lane_scene() is False


def test_scripts_outside_a_turn_always_push(executor_module):
    executor = executor_module.ScriptExecutor()
    assert executor._should_push_undo() is True
    assert executor._should_push_undo(grouping=True) is True


def test_ungrouped_turn_pushes_per_script_until_the_cap(executor_module, monkeypatch):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module)
    monkeypatch.setattr(executor_module, "AGENT_UNDO_GROUP_PER_TURN", False)
    cap = executor_module.AGENT_UNDO_MAX_CHECKPOINTS_PER_TURN
    executor = executor_module.ScriptExecutor()
    executor.begin_agent_turn()

    decisions = []
    for _ in range(cap + 3):
        allowed = executor._should_push_undo()
        decisions.append(allowed)
        if allowed:
            assert executor._push_undo_for_script() is True

    assert decisions == [True] * cap + [False] * 3
    assert _undo_pushes(bpy_mod) == cap


def test_grouped_turn_pushes_once_per_turn(executor_module, monkeypatch):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module)
    executor = executor_module.ScriptExecutor()
    executor.begin_agent_turn()

    assert executor._should_push_undo(grouping=True) is True
    assert executor._push_undo_for_script() is True
    assert executor._should_push_undo(grouping=True) is False
    assert executor._should_push_undo(grouping=True) is False

    # The next turn starts a fresh checkpoint even while still grouped. No
    # script ran through execute() here, so ending the turn adds no closing
    # checkpoint.
    executor.end_agent_turn()
    executor.begin_agent_turn()
    assert executor._should_push_undo(grouping=True) is True
    assert _undo_pushes(bpy_mod) == 1


def test_ending_a_turn_resets_the_checkpoint_budget(executor_module, monkeypatch):
    _mocked_bpy(monkeypatch, executor_module)
    cap = executor_module.AGENT_UNDO_MAX_CHECKPOINTS_PER_TURN
    executor = executor_module.ScriptExecutor()
    executor.begin_agent_turn()
    for _ in range(cap):
        assert executor._push_undo_for_script() is True
    assert executor._should_push_undo() is False

    executor.end_agent_turn()
    executor.begin_agent_turn()
    assert executor._should_push_undo() is True
    # begin is idempotent: a second call mid-turn must NOT reset the budget.
    assert executor._push_undo_for_script() is True
    executor.begin_agent_turn()
    assert executor._turns[""][0] == 1


# --------------------------------------------------------------------------- #
#  The push itself
# --------------------------------------------------------------------------- #


def test_push_checkpoint_success_without_override(executor_module, monkeypatch):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module)
    executor = executor_module.ScriptExecutor()
    assert executor._push_undo_for_script() is True
    assert _undo_pushes(bpy_mod) == 1
    bpy_mod.context.temp_override.assert_not_called()


def test_push_checkpoint_retries_inside_window_context(executor_module, monkeypatch):
    window = MagicMock()
    bpy_mod = _mocked_bpy(
        monkeypatch,
        executor_module,
        undo_side_effect=[RuntimeError("operator poll failed"), MagicMock()],
        windows=[window],
    )
    executor = executor_module.ScriptExecutor()
    assert executor._push_undo_for_script() is True
    assert _undo_pushes(bpy_mod) == 2
    bpy_mod.context.temp_override.assert_called_once_with(window=window)


# --------------------------------------------------------------------------- #
#  Through execute(): ordering, cap, grouping, failure
# --------------------------------------------------------------------------- #


def _call_index(bpy_mod, needle: str) -> int:
    for index, call in enumerate(bpy_mod.mock_calls):
        if needle in str(call):
            return index
    raise AssertionError(f"no call matching {needle!r} in {bpy_mod.mock_calls}")


def test_first_push_of_a_turn_precedes_the_first_script(executor_module, monkeypatch):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module)
    executor = executor_module.ScriptExecutor()
    executor.begin_agent_turn()

    result = executor.execute("bpy.ops.mixar.probe()")

    assert result.success is True, result.error
    assert _undo_pushes(bpy_mod) == 1
    # The checkpoint captures the PRE-turn scene: it lands before the script.
    assert _call_index(bpy_mod, "ops.ed.undo_push(") < _call_index(bpy_mod, "ops.mixar.probe(")


def test_execute_stops_pushing_after_the_cap_but_keeps_running_scripts(
    executor_module, monkeypatch
):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module)
    monkeypatch.setattr(executor_module, "AGENT_UNDO_GROUP_PER_TURN", False)
    cap = executor_module.AGENT_UNDO_MAX_CHECKPOINTS_PER_TURN
    executor = executor_module.ScriptExecutor()
    executor.begin_agent_turn()

    results = [executor.execute("bpy.ops.mixar.probe()") for _ in range(cap + 3)]

    assert all(result.success for result in results)
    assert _undo_pushes(bpy_mod) == cap
    assert bpy_mod.ops.mixar.probe.call_count == cap + 3


def test_execute_grouped_turn_pushes_once(executor_module, monkeypatch):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module)
    monkeypatch.setattr(executor_module, "AGENT_UNDO_GROUP_PER_TURN", True)
    executor = executor_module.ScriptExecutor()

    executor.begin_agent_turn()
    for _ in range(3):
        assert executor.execute("bpy.ops.mixar.probe()").success is True
    assert _undo_pushes(bpy_mod) == 1

    # Ending a turn that ran scripts closes it with the state the agent left,
    # so the turn is bracketed: undo reverts it, redo reapplies it.
    executor.end_agent_turn()
    assert _undo_pushes(bpy_mod) == 2
    assert bpy_mod.ops.ed.undo_push.call_args_list[-1].kwargs["message"] == "Mixie Chat Turn"
    executor.begin_agent_turn()
    assert executor.execute("bpy.ops.mixar.probe()").success is True
    assert _undo_pushes(bpy_mod) == 3


def test_failed_push_never_aborts_is_retried_and_logged_once_per_turn(
    executor_module, monkeypatch
):
    bpy_mod = _mocked_bpy(
        monkeypatch, executor_module, undo_side_effect=RuntimeError("poll fail")
    )
    fake_logger = MagicMock()
    monkeypatch.setattr(executor_module, "logger", fake_logger)
    executor = executor_module.ScriptExecutor()
    executor.begin_agent_turn()

    results = [executor.execute("bpy.ops.mixar.probe()") for _ in range(3)]

    # The scripts still ran.
    assert all(result.success for result in results)
    assert bpy_mod.ops.mixar.probe.call_count == 3
    # Failures are not counted, so every script retried (no windows exist, so
    # each attempt is exactly one failed undo_push call).
    assert _undo_pushes(bpy_mod) == 3
    assert executor._turns[""][0] == 0
    # ...but the warning is logged once for the turn, not per script.
    warnings = [
        call for call in fake_logger.warning.mock_calls
        if "Undo checkpoint failed" in str(call)
    ]
    assert len(warnings) == 1

    # A new turn may warn again.
    executor.end_agent_turn()
    executor.begin_agent_turn()
    executor.execute("bpy.ops.mixar.probe()")
    warnings = [
        call for call in fake_logger.warning.mock_calls
        if "Undo checkpoint failed" in str(call)
    ]
    assert len(warnings) == 2


# --------------------------------------------------------------------------- #
#  Turn boundaries are wired in the stream pipeline
# --------------------------------------------------------------------------- #


def _method_body(source: str, name: str) -> str:
    start = source.index(f"def {name}(")
    rest = source[start + 1:]
    next_def = rest.find("\n    def ")
    return source[start:] if next_def == -1 else rest[:next_def]


def test_turn_boundaries_are_wired_in_the_stream_pipeline():
    queue_processor = (_CORE_ROOT / "queue_processor.py").read_text(encoding="utf-8")
    # Begin: the first streamed event of a turn.
    assert "begin_agent_turn(" in _method_body(queue_processor, "_handle_agent_event_internal")
    # End: however the stream stops.
    for handler in (
        "_handle_agent_complete_internal",
        "_handle_inband_error",
        "_handle_agent_error_internal",
    ):
        assert "end_agent_turn(" in _method_body(queue_processor, handler), handler

    # A user abort drains the queue (and with it the complete/error event),
    # so it must end the turn itself; so must a file load.
    session_ops = (_CHAT_ROOT / "ui" / "operators" / "session_ops.py").read_text(encoding="utf-8")
    abort = session_ops[session_ops.index("class MIXIE_CHAT_OT_abort_session"):]
    assert "end_agent_turn(" in abort
    file_handlers = (_CORE_ROOT / "file_handlers.py").read_text(encoding="utf-8")
    assert "end_agent_turn()" in file_handlers


def test_a_turn_without_scripts_closes_without_a_checkpoint(executor_module, monkeypatch):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module)
    executor = executor_module.ScriptExecutor()
    executor.begin_agent_turn("s1")
    executor.end_agent_turn("s1")
    executor.begin_agent_turn("s2")
    executor.end_agent_turn()               # every session, none ran a script
    assert _undo_pushes(bpy_mod) == 0


def test_closing_checkpoint_is_skipped_while_pinned_to_a_lane(executor_module, monkeypatch):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module, windows=[_window("tab")])
    executor = executor_module.ScriptExecutor()
    executor.begin_agent_turn("s1")
    assert executor.execute("bpy.ops.mixar.probe()", session_id="s1").success is True
    assert _undo_pushes(bpy_mod) == 1
    bpy_mod.context.window_manager.windows = [_window("agentlane:x")]
    executor.end_agent_turn("s1")
    assert _undo_pushes(bpy_mod) == 1


def test_checkpoints_are_pushed_on_behalf_of_the_sessions_tab(executor_module, monkeypatch):
    # Per-tab undo (M1): the executor pushes through WindowManager.mixar_undo_push
    # with the SESSION's scene, so the step is tagged with the agent's tab even
    # when the window shows another (the closing checkpoint lands from a timer
    # after the user moved on).
    bpy_mod = _mocked_bpy(monkeypatch, executor_module, windows=[_window("other-tab")])
    agent_scene = MagicMock(mixie_session_id="s1")
    bpy_mod.data.scenes = [MagicMock(mixie_session_id="other-tab"), agent_scene]
    pusher = bpy_mod.context.window_manager.mixar_undo_push
    pusher.return_value = True
    executor = executor_module.ScriptExecutor()
    executor.begin_agent_turn("s1")
    assert executor.execute("bpy.ops.mixar.probe()", session_id="s1").success is True
    executor.end_agent_turn("s1")
    assert pusher.call_count == 2
    for call in pusher.call_args_list:
        assert call.kwargs["scene"] is agent_scene
    assert pusher.call_args_list[-1].args[0] == "Mixie Chat Turn"
    assert _undo_pushes(bpy_mod) == 0            # never the window-scene path


def test_a_build_without_mixar_undo_push_falls_back_to_ed_undo_push(executor_module, monkeypatch):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module, windows=[_window("tab")])
    agent_scene = MagicMock(mixie_session_id="s1")
    bpy_mod.data.scenes = [agent_scene]
    del bpy_mod.context.window_manager.mixar_undo_push
    executor = executor_module.ScriptExecutor()
    executor.begin_agent_turn("s1")
    assert executor.execute("bpy.ops.mixar.probe()", session_id="s1").success is True
    assert _undo_pushes(bpy_mod) == 1


def test_a_push_without_a_known_session_scene_keeps_the_old_path(executor_module, monkeypatch):
    bpy_mod = _mocked_bpy(monkeypatch, executor_module)
    bpy_mod.data.scenes = []
    executor = executor_module.ScriptExecutor()
    assert executor._push_undo_checkpoint() is True
    assert bpy_mod.context.window_manager.mixar_undo_push.call_count == 0
