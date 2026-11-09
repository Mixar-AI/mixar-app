# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""A raw agent script is stopped once the backend has stopped waiting (#1911).

Agent scripts run on Blender's main thread. The backend waits 60 s (orchestrator,
DIRECT, MCP) or 180 s (workers, workspaces) for a raw script, then reports a
timeout, but the client used to keep running it: the window stayed frozen ("Not
Responding") for minutes and every later script queued behind it.

The stop is a check compiled into the model's own code, so it unwinds like any
exception raised by that line: every ``with`` exits and every ``finally``
runs. These tests pin that on the interpreter they run under; run them on the
bundled one.
"""

import ast
import importlib.util
from pathlib import Path
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

_MIXAR_ROOT = Path(__file__).parents[1] / "src" / "scripts" / "mixar"
_MODULES = _MIXAR_ROOT / "modules"
_CHAT_ROOT = _MODULES / "space_mixie_chat"

LIMIT_S = 0.3
# Every busy loop below ends by itself after this long, so a missing stop
# fails the timing assert instead of hanging the suite.
LOOP_S = 6.0
STOPPED_WITHIN_S = 3.0
SPIN = f"t = time.monotonic()\nwhile time.monotonic() - t < {LOOP_S}: pass\n"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mods(monkeypatch):
    for name in ("bmesh", "mathutils", "bpy_extras", "imbuf"):
        monkeypatch.setitem(sys.modules, name, MagicMock(name=name))
    for name, path in (("mixar", _MIXAR_ROOT), ("mixar.modules", _MODULES),
                       ("mixar.modules.common", _MODULES / "common"),
                       ("mixar.modules.common.agent_execution", _MODULES / "common" / "agent_execution"),
                       ("mixar.modules.space_mixie_chat", _CHAT_ROOT),
                       ("mixar.modules.space_mixie_chat.core", _CHAT_ROOT / "core")):
        package = ModuleType(name)
        package.__path__ = [str(path)]
        monkeypatch.setitem(sys.modules, name, package)
    loaded = {}
    for key, name, path in (
            ("stl", "mixar.modules.common.agent_execution.script_time_limit",
             _MODULES / "common" / "agent_execution" / "script_time_limit.py"),
            ("chk", "mixar.modules.space_mixie_chat.core.sandbox_checkpoints",
             _CHAT_ROOT / "core" / "sandbox_checkpoints.py")):
        monkeypatch.delitem(sys.modules, name, raising=False)
        loaded[key] = _load(name, path)
        monkeypatch.setitem(sys.modules, name, loaded[key])
    return SimpleNamespace(**loaded)


@pytest.fixture
def executor_module(mods, monkeypatch):
    # A bpy mock of its own: other suites patch attributes of the shared one
    # (tests/test_sandbox_exec_routes.py removes ``bpy.types`` when it undoes).
    fresh_bpy = MagicMock(name="bpy")
    monkeypatch.setitem(sys.modules, "bpy", fresh_bpy)
    name = "mixar.modules.space_mixie_chat.core.executor"
    monkeypatch.delitem(sys.modules, name, raising=False)
    module = _load(name, _CHAT_ROOT / "core" / "executor.py")
    monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(module, "bpy", fresh_bpy)
    return module


def _exec(mods, source, namespace=None, limit_s=LIMIT_S):
    """Run ``source`` as the executor does; return (outcome, elapsed, namespace)."""
    tree = ast.parse(source)
    if limit_s:
        mods.chk.add_stop_checkpoints(tree, source)
    code = compile(tree, "<agent_script>", "exec")
    namespace = {"time": time, **(namespace or {})}
    started = time.monotonic()
    try:
        mods.stl.exec_with_time_limit(code, namespace, limit_s)
        outcome = "returned"
    except TimeoutError as exc:
        assert "Script stopped" in str(exc)
        outcome = "stopped"
    return outcome, time.monotonic() - started, namespace


def _assert_stopped(outcome, elapsed):
    assert outcome == "stopped"
    assert LIMIT_S <= elapsed < STOPPED_WITHIN_S, f"stopped after {elapsed:.1f}s"


def _helper(source):
    """Functions defined outside the agent's code, like Blender's or Mixar's Python."""
    namespace = {"time": time}
    exec(compile(source, "<mixar_helper>", "exec"), namespace)  # noqa: S102
    return namespace


CM = _helper(
    "class CM:\n"
    "    def __init__(self, log, name='cm'): self.log, self.name = log, name\n"
    "    def __enter__(self): self.log.append('enter ' + self.name); return self\n"
    "    def __exit__(self, *exc): self.log.append('exit ' + self.name); return False\n"
)["CM"]


# --- unwinding: the stop runs every __exit__ and finally ---------------------


def test_a_python_exit_runs(mods):
    log = []
    outcome, elapsed, _ = _exec(mods, "with CM(log):\n" + _indent(SPIN), {"CM": CM, "log": log})
    _assert_stopped(outcome, elapsed)
    assert log == ["enter cm", "exit cm"]


def test_a_native_exit_runs(mods):
    # threading.Lock's __exit__ is C, like temp_override's, temp_data's and
    # libraries.load's: a skipped one leaves the lock held.
    lock = threading.Lock()
    _assert_stopped(*_exec(mods, "with lock:\n" + _indent(SPIN), {"lock": lock})[:2])
    assert not lock.locked()


def test_a_with_left_normally_after_the_limit_still_exits(mods):
    # The limit passes inside one long call; the block then ends normally and
    # the stop comes at the next statement, outside it.
    lock = threading.Lock()
    script = f"with lock:\n    time.sleep({LIMIT_S * 2})\n" + SPIN
    outcome, elapsed, _ = _exec(mods, script, {"lock": lock})
    _assert_stopped(outcome, elapsed)
    assert elapsed >= LIMIT_S * 2 and not lock.locked()


def test_nested_withs_inside_a_function_exit_in_order(mods):
    log, lock = [], threading.Lock()
    script = ("def build():\n"
              "    with CM(log, 'a'):\n"
              "        with lock:\n"
              "            with CM(log, 'b'):\n" + _indent(SPIN, 16) + "build()\n")
    _assert_stopped(*_exec(mods, script, {"CM": CM, "log": log, "lock": lock})[:2])
    assert log == ["enter a", "enter b", "exit b", "exit a"]
    assert not lock.locked()


@pytest.mark.parametrize("finally_src", [
    "finally:\n    log.append('cleanup')\n    log.append('done')\n",
    "finally: log.append('cleanup'); log.append('done')\n",
], ids=["block", "one_line"])
def test_a_finally_runs(mods, finally_src):
    log = []
    _assert_stopped(*_exec(mods, "try:\n" + _indent(SPIN) + finally_src, {"log": log})[:2])
    assert log == ["cleanup", "done"]


def test_a_finally_reached_normally_after_the_limit_runs_whole(mods):
    # Its body, and the model's own functions it calls, hold the stop until
    # it ends (within HARD_GRACE_S).
    log = []
    script = ("def cleanup():\n"
              "    for i in range(3):\n"
              "        log.append(i)\n"
              f"try:\n    time.sleep({LIMIT_S * 2})\n"
              "finally:\n    cleanup()\n    log.append('done')\n" + SPIN)
    _assert_stopped(*_exec(mods, script, {"log": log})[:2])
    assert log == [0, 1, 2, "done"]


def test_a_finally_that_spins_holds_the_stop_until_the_hard_grace(mods, monkeypatch):
    monkeypatch.setattr(mods.stl, "HARD_GRACE_S", 0.5)
    log = []
    script = ("try:\n    pass\nfinally:\n    log.append('cleanup')\n" + _indent(SPIN)
              + "    log.append('never')\n")
    outcome, elapsed, _ = _exec(mods, script, {"log": log})
    _assert_stopped(outcome, elapsed)
    assert elapsed >= LIMIT_S + 0.5 and log == ["cleanup"]


def test_a_generator_suspended_in_a_finally_cannot_hold_the_stop(mods, monkeypatch):
    # Its hold is never released: the generator is never resumed or closed.
    monkeypatch.setattr(mods.stl, "HARD_GRACE_S", 0.5)
    script = ("def g():\n    try:\n        pass\n    finally:\n        yield 1\n"
              "it = g()\nnext(it)\n" + SPIN)
    outcome, elapsed, _ = _exec(mods, script)
    _assert_stopped(outcome, elapsed)
    assert elapsed >= LIMIT_S + 0.5


@pytest.mark.parametrize("script", [
    # The realistic one: a fast path fails, the fallback is slow.
    "def fast():\n    raise RuntimeError('fast path failed')\n"
    "def slow_fallback():\n" + "    " + SPIN.replace("\n", "\n    ").rstrip() + "\n"
    "try:\n    fast()\nexcept Exception:\n    slow_fallback()\n",
    "try:\n    {}['Terrain']\nexcept KeyError:\n" + "    " + SPIN.replace("\n", "\n    ").rstrip() + "\n",
    "def step():\n" + "    " + SPIN.replace("\n", "\n    ").rstrip() + "\n"
    "try:\n    step()\nexcept BaseException:\n    step()\n",
], ids=["fallback_in_except", "loop_in_except", "retry_after_catching_the_stop"])
def test_work_in_an_except_clause_is_stopped(mods, script):
    _assert_stopped(*_exec(mods, script)[:2])


@pytest.mark.parametrize("script", [
    f"t = time.monotonic()\nwhile time.monotonic() - t < {LOOP_S}:\n"
    "    try:\n        pass\n    except BaseException:\n        continue\n",
    f"t = time.monotonic()\nwhile time.monotonic() - t < {LOOP_S}:\n"
    "    try:\n        pass\n    except:\n        pass\n",
    f"t = time.monotonic()\nwhile time.monotonic() - t < {LOOP_S}:\n"
    "    try:\n        pass\n    except Exception:\n        pass\n",
    f"t = time.monotonic()\ntry:\n    while time.monotonic() - t < {LOOP_S}: pass\n"
    f"except BaseException:\n    pass\nwhile time.monotonic() - t < {LOOP_S}: pass\n",
], ids=["except_base_continue", "bare_except", "except_exception", "swallowed_then_spins"])
def test_a_script_that_catches_the_stop_is_still_stopped(mods, script):
    _assert_stopped(*_exec(mods, script)[:2])


# --- coverage: every way the model's code can keep running ------------------


@pytest.mark.parametrize("script", [
    f"t = time.monotonic()\nwhile time.monotonic() - t < {LOOP_S}: pass\n",
    "for i in range(10**12): pass\n",
    f"def spin():\n    t = time.monotonic()\n    while time.monotonic() - t < {LOOP_S}: pass\nspin()\n",
    f"t = time.monotonic()\nn = [i for i in range(10**12) if time.monotonic() - t > {LOOP_S}]\n",
    f"t = time.monotonic()\nn = sum(1 for _ in iter(lambda: time.monotonic() - t < {LOOP_S}, False))\n",
    f"t = time.monotonic()\nn = {{i: i for i in range(10**12) if time.monotonic() - t > {LOOP_S}}}\n",
    # C calls the model's one-line lambda / def; no Python loop in between
    "a = sorted(range(10**6), key=lambda i: (time.sleep(0.001), -i)[1])\n",
    "def key(i): return (time.sleep(0.001), -i)[1]\na = sorted(range(10**6), key=key)\n",
    "a = any(map(lambda i: i < 0, range(10**12)))\n",
    "def fib(n): return n if n < 2 else fib(n - 1) + fib(n - 2)\nfib(60)\n",
], ids=["while_one_line", "for_one_line", "function", "listcomp", "genexpr",
        "dictcomp", "sorted_lambda", "sorted_def", "map_lambda", "recursion"])
def test_the_stop_reaches_every_loop(mods, script):
    _assert_stopped(*_exec(mods, script)[:2])


def test_annotations_are_left_as_written(mods):
    # Under ``from __future__ import annotations`` they are strings the script
    # can read back; a lambda or comprehension in one must not gain a check.
    source = ("from __future__ import annotations\n"
              "def f(x: [i for i in range(3)], k: (lambda: 1)) -> (lambda: None):\n    pass\n"
              "y: [j for j in range(2)] = 1\n"
              "result = (f.__annotations__, __annotations__)\n")
    plain = {}
    exec(compile(source, "<agent_script>", "exec"), plain)  # noqa: S102
    outcome, _, ns = _exec(mods, source)
    assert outcome == "returned" and ns["result"] == plain["result"]


def test_code_the_script_calls_is_never_cut(mods):
    # Blender's Python, Mixar's sandbox wrappers and the backend's helpers carry
    # no check: the call ends before the stop.
    helper = _helper("def helper(done):\n"
                     f"    t = time.monotonic()\n    while time.monotonic() - t < {LIMIT_S * 3}: pass\n"
                     "    done.append(True)\n")["helper"]
    done = []
    outcome, elapsed, _ = _exec(mods, "helper(done)\n" + SPIN, {"helper": helper, "done": done})
    _assert_stopped(outcome, elapsed)
    assert done == [True] and elapsed >= LIMIT_S * 3


def test_a_script_within_its_limit_is_untouched(mods):
    script = f"t = time.monotonic()\nwhile time.monotonic() - t < {LIMIT_S / 3}: pass\nresult = 'done'\n"
    outcome, _, ns = _exec(mods, script)
    assert outcome == "returned" and ns["result"] == "done"


def test_functions_the_script_leaves_behind_run_unlimited(mods):
    # A timer or handler the script registers runs after it returned
    # (bpy.app.timers.register): never stopped, never by a stale flag.
    script = ("def later():\n"
              f"    t = time.monotonic()\n    while time.monotonic() - t < {LIMIT_S * 2}: pass\n"
              "    return 'ran'\n" + SPIN)
    outcome, _, ns = _exec(mods, script)
    assert outcome == "stopped"
    assert ns[mods.stl.HIT_NAME] is False
    assert ns["later"]() == "ran"


# --- only the model's own code is instrumented ------------------------------


def _scaffold(model, epilogue="    log.append('guard')\n", markers=True):
    """A lane script as mixar-backend sends it: the data-view helpers, then the
    marked run, whose ``finally`` (the modifier-cost guard) sits below the end marker."""
    begin, end = ("# >>> mixar model run\n", "# <<< mixar model run\n") if markers else ("", "")
    return ("# >>> model code (as written)\n#| (the model's code as a comment)\n# <<< model code\n"
            "def __ws_helper(log):\n"
            f"    t = time.monotonic()\n    while time.monotonic() - t < {LIMIT_S * 3}: pass\n"
            "    log.append('helper')\n"
            + begin + "try:\n" + _indent(model) + end + "finally:\n" + epilogue)


def test_backend_scaffolding_runs_whole_around_a_stopped_model(mods):
    log = []
    outcome, elapsed, _ = _exec(mods, _scaffold("__ws_helper(log)\n" + SPIN), {"log": log})
    _assert_stopped(outcome, elapsed)
    assert log == ["helper", "guard"]


def test_a_stop_past_the_hard_deadline_never_cuts_the_guard(mods, monkeypatch):
    # A long native call returns after the hard deadline, so the stop lands with
    # no hold left. The guard below the end marker has no checks (only the hold),
    # so it still runs whole.
    monkeypatch.setattr(mods.stl, "HARD_GRACE_S", 0.2)
    source = _scaffold(f"time.sleep({LIMIT_S + 0.5})\nlog.append('after the call')\n",
                       epilogue="    for i in range(3):\n        log.append(i)\n")
    tree = ast.parse(source)
    mods.chk.add_stop_checkpoints(tree, source)
    names = [n for n in ast.walk(tree) if isinstance(n, ast.Name)]
    end = source.split("\n").index("# <<< mixar model run") + 1
    assert max(n.lineno for n in names if n.id == "_mixar_tl_hit") < end
    assert sum(n.id == "_mixar_tl_hold" for n in names) == 1
    log = []
    outcome, elapsed, _ = _exec(mods, source, {"log": log})
    assert outcome == "stopped" and elapsed >= LIMIT_S + 0.5
    assert log == [0, 1, 2]


def test_statements_outside_the_markers_are_left_as_sent(mods):
    source = _scaffold("x = 1\n")
    tree = ast.parse(source)
    before = [ast.dump(stmt) for stmt in tree.body[:1]]
    assert mods.chk.add_stop_checkpoints(tree, source) > 0
    assert [ast.dump(stmt) for stmt in tree.body[:1]] == before


def test_a_scaffold_without_run_markers_is_not_instrumented(mods):
    # A backend before the markers: the model's part cannot be told apart.
    source = _scaffold("x = 1\n", markers=False)
    tree = ast.parse(source)
    before = ast.dump(tree)
    assert mods.chk.add_stop_checkpoints(tree, source) == 0
    assert ast.dump(tree) == before


@pytest.mark.parametrize("source, span", [
    ("x = 1\n", (0.0, float("inf"))),
    ("a = 1\n# >>> mixar model run\nb = 2\n# <<< mixar model run\n", (2.0, 4.0)),
    ("# >>> model code (as written)\n#| x\n# <<< model code\nx = 1\n", None),
    ("# >>> mixar model run\nb = 2\n", None),
    ("# <<< mixar model run\nb = 2\n# >>> mixar model run\n", None),
    ("    # >>> mixar model run\nb = 2\n", (0.0, float("inf"))),
], ids=["plain", "marked", "old_scaffold", "unpaired", "reversed", "indented_is_not_a_marker"])
def test_model_span(mods, source, span):
    assert mods.chk.model_span(source) == span


@pytest.mark.parametrize("source, warned", [
    ("# >>> mixar model run\nb = 2\n", True),
    ("# >>> mixar model run\n# >>> mixar model run\nb = 2\n# <<< mixar model run\n", True),
    ("# <<< mixar model run\nb = 2\n# >>> mixar model run\n", True),
    ("a = 1\n# >>> mixar model run\nb = 2\n# <<< mixar model run\n", False),
    ("# >>> model code (as written)\n#| x\n# <<< model code\nx = 1\n", False),
], ids=["unpaired", "duplicate", "reversed", "marked", "old_scaffold"])
def test_markers_that_turn_checks_off_are_logged(mods, caplog, source, warned):
    caplog.set_level("WARNING", logger=mods.chk.logger.name)
    mods.chk.model_span(source)
    hits = [r for r in caplog.records if "run markers" in r.getMessage()]
    assert len(hits) == (1 if warned else 0)


# --- the limit: the backend's wait, sent per script --------------------------


@pytest.mark.parametrize("tool, envelope, expected", [
    ("execute_bpy_script", {"deadline": 60}, 70.0),
    ("execute_workspace_script", {"deadline": 180}, 190.0),
    ("execute_bpy_script", None, 190.0),
    ("execute_bpy_script", {}, 190.0),
    ("execute_bpy_script", {"deadline": 900}, 190.0),
    ("execute_bpy_script", {"deadline": 0}, 190.0),
    ("execute_bpy_script", {"deadline": -5}, 190.0),
    ("execute_bpy_script", {"deadline": float("nan")}, 190.0),
    ("execute_bpy_script", {"deadline": float("inf")}, 190.0),
    ("execute_bpy_script", {"deadline": True}, 190.0),
    ("execute_bpy_script", {"deadline": "60"}, 190.0),
    ("render_viewport", {"deadline": 60}, None),
    ("unknown", None, None),
])
def test_the_limit_is_the_backends_wait_plus_its_probe_grace(mods, tool, envelope, expected):
    from mixar.modules.common.agent_execution.request import ExecutionEnvelope
    assert mods.stl.limit_for(tool, ExecutionEnvelope.parse(envelope)) == expected


def test_the_shipped_bounds(mods):
    # mixar-backend scene_core: BUILD_SCRIPT_TIMEOUT_S = 180 (the longest wait,
    # assumed when a backend sends none); the backend gives up after at most
    # two 5 s liveness probes past it.
    assert mods.stl.DEFAULT_BUDGET_S == mods.stl.MAX_BUDGET_S == 180.0
    assert mods.stl.GRACE_S == 10.0
    assert mods.stl.LIMITED_TOOLS == {"execute_bpy_script", "execute_workspace_script"}


def test_the_handshake_says_this_client_stops_scripts(mods):
    # mixar-backend tells the model a timed-out script is being stopped only
    # for a client with this capability; released ones take the deadline too.
    assert mods.stl.CAPABILITY == "script_time_limit_v1"
    handshake = (_CHAT_ROOT / "core" / "socket_connection.py").read_text(encoding="utf-8")
    assert "script_time_limit import CAPABILITY as SCRIPT_TIME_LIMIT_CAPABILITY" in handshake
    assert "SCRIPT_TIME_LIMIT_CAPABILITY,\n" in handshake


def test_the_pump_passes_each_script_its_limit():
    from mixar.modules.common.agent_execution import pump
    from mixar.modules.common.agent_execution.request import ExecutionEnvelope, ExecutionRequest
    seen = []

    def execute(script, **kwargs):
        seen.append(kwargs.get("time_limit_s"))
        return SimpleNamespace(to_dict=lambda: {"success": True})

    for tool, envelope in (("execute_bpy_script", {"deadline": 60}),
                           ("execute_workspace_script", None), ("render_viewport", None)):
        pump.execute_request(ExecutionRequest(
            request_id="r", script="x = 1", tool_name=tool,
            envelope=ExecutionEnvelope.parse(envelope)), SimpleNamespace(execute=execute))
    assert seen == [70.0, 190.0, None]


# --- through the executor ----------------------------------------------------


def _run(executor_module, script, tool_name="execute_bpy_script", limit_s=LIMIT_S):
    executor = executor_module.ScriptExecutor()
    started = time.monotonic()
    result = executor.execute(script, push_undo=False, tool_name=tool_name, time_limit_s=limit_s)
    return executor, result, time.monotonic() - started


def test_the_executor_stops_reports_and_runs_the_next_script(executor_module):
    executor, result, elapsed = _run(executor_module, "import time\n" + SPIN + "__RESULT__ = 'finished'\n")
    assert LIMIT_S <= elapsed < STOPPED_WITHIN_S
    assert result.success is False and result.return_value is None
    assert "Script stopped" in result.error

    result = executor.execute("__RESULT__ = 7", push_undo=False,
                              tool_name="execute_bpy_script", time_limit_s=LIMIT_S)
    assert result.success is True and result.return_value == 7


def test_the_executor_without_a_limit_never_stops(executor_module):
    script = f"import time\nt = time.monotonic()\nwhile time.monotonic() - t < {LIMIT_S * 3}: pass\n__RESULT__ = 'done'\n"
    _, result, _ = _run(executor_module, script, tool_name="render_viewport", limit_s=None)
    assert result.success is True and result.return_value == "done"


def _indent(source, spaces=4):
    pad = " " * spaces
    return "".join(pad + line if line.strip() else line for line in source.splitlines(True))
