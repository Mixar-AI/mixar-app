# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The soft attribute gate wired into ScriptExecutor cannot change an outcome.

The gate runs at the one choke point every agent script passes through
(``_execute_locked``), which makes it the most dangerous place in the app for
an advisory feature to sit: a bug there would take out script execution for
every turn. These tests pin the two halves of the deal:

- the gate cannot break a run, whether it raises, returns junk, or the truth
  table is missing entirely;
- what it learns still reaches the model, as ``attribute_warnings`` on a
  result that says ``success: true``.
"""

import importlib
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
_PACKAGES = (
    ("mixar", _MIXAR_ROOT),
    ("mixar.modules", _MODULES_ROOT),
    ("mixar.modules.space_mixie_chat", _CHAT_ROOT),
    ("mixar.modules.space_mixie_chat.core", _CORE_ROOT),
)
_VALIDATOR = "mixar.modules.space_mixie_chat.core.script_validator"


def _load_executor_module(monkeypatch):
    for name, path in _PACKAGES:
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
    module = _load_executor_module(monkeypatch)
    monkeypatch.setattr(module, "bpy", MagicMock(name="bpy"))
    return module


@pytest.fixture
def gate(monkeypatch):
    """The real validator module, so tests can patch what the executor calls."""
    return importlib.import_module(_VALIDATOR)


# --- the gate cannot break a run -------------------------------------------

def test_a_broken_gate_cannot_fail_a_good_script(executor_module, gate, monkeypatch):
    def explode(_script):
        raise RuntimeError("bug in the gate")

    monkeypatch.setattr(gate, "prepare_script", explode)
    executor = executor_module.ScriptExecutor()

    result = executor.execute("__RESULT__ = 7", push_undo=False)

    assert result.success is True, "an advisory gate must never fail a script"
    assert result.return_value == 7
    assert result.attribute_warnings == []


def test_a_broken_gate_cannot_rewrite_the_error_of_a_failing_script(
    executor_module, gate, monkeypatch
):
    def explode(_script):
        raise RuntimeError("bug in the gate")

    monkeypatch.setattr(gate, "prepare_script", explode)
    executor = executor_module.ScriptExecutor()

    result = executor.execute("raise ValueError('the real bug')", push_undo=False)

    assert result.success is False
    assert "the real bug" in (result.error or ""), "the script's own error must survive"
    assert "bug in the gate" not in (result.error or "")


@pytest.mark.parametrize("junk", [None, 12345, object(), ""])
def test_a_gate_returning_nonsense_runs_what_it_was_given(
    executor_module, gate, monkeypatch, junk
):
    """prepare_script is defensive, but the executor must not trust it either."""
    monkeypatch.setattr(gate, "prepare_script", lambda _script: junk)
    executor = executor_module.ScriptExecutor()

    result = executor.execute("__RESULT__ = 7", push_undo=False)

    assert result.success is True, "even a gate that returns garbage cannot fail a script"
    assert result.return_value == 7


def test_a_missing_truth_table_changes_nothing(executor_module, gate, monkeypatch):
    """Validation degrades to blind; execution must not notice."""
    def blind(_script):
        raise OSError("truth table missing")

    monkeypatch.setattr(gate, "validate_bpy_properties", blind)
    executor = executor_module.ScriptExecutor()

    result = executor.execute("__RESULT__ = 7", push_undo=False)

    assert result.success is True
    assert result.return_value == 7


# --- what it learns still reaches the model --------------------------------

def test_warnings_ride_on_a_successful_result(executor_module, gate, monkeypatch):
    """The whole point of a soft gate: correct the model without a round trip."""
    report = gate.GateReport(
        normalized="__RESULT__ = 1\n",
        issues=["bpy.types.Object has no attribute 'rotation'"],
    )
    monkeypatch.setattr(gate, "prepare_script", lambda _script: report)
    executor = executor_module.ScriptExecutor()

    result = executor.execute("__RESULT__ = 1", push_undo=False)
    payload = result.to_dict()

    assert payload["success"] is True
    assert payload["attribute_warnings"] == [
        "bpy.types.Object has no attribute 'rotation'"
    ]


def test_a_clean_script_carries_no_warnings_key(executor_module, gate, monkeypatch):
    monkeypatch.setattr(
        gate, "prepare_script", lambda script: gate.GateReport(normalized=script)
    )
    executor = executor_module.ScriptExecutor()

    payload = executor.execute("__RESULT__ = 1", push_undo=False).to_dict()

    assert payload == {"success": True, "return_value": 1}


# --- the gate runs before the sandbox, on the text that gets compiled ------

def test_normalized_text_is_what_runs(executor_module, gate, monkeypatch):
    """The rewrite is not decoration: it is the script the sandbox compiles."""
    report = gate.GateReport(normalized="__RESULT__ = 42\n", notes=["test rewrite"])
    monkeypatch.setattr(gate, "prepare_script", lambda _script: report)
    executor = executor_module.ScriptExecutor()

    result = executor.execute("__RESULT__ = 1", push_undo=False)

    assert result.success is True
    assert result.return_value == 42


def test_the_sandbox_checks_the_normalized_text_not_the_original(
    executor_module, gate, monkeypatch
):
    """Ordering matters for security.

    Normalization rewrites the script, so the sandbox denylist has to run on
    the result. Validating the original and compiling the rewrite would let a
    rewrite be the way past the denylist.
    """
    escape = "__RESULT__ = ().__class__.__subclasses__\n"
    report = gate.GateReport(normalized=escape)
    monkeypatch.setattr(gate, "prepare_script", lambda _script: report)
    executor = executor_module.ScriptExecutor()

    result = executor.execute("__RESULT__ = 1", push_undo=False)

    assert result.success is False
    assert "SandboxViolation" in (result.error or "") or "sandbox" in (result.error or "").lower()

