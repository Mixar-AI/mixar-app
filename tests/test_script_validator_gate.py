# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The soft attribute gate reports; it must never decide whether a script runs.

The gate checks agent scripts against a dumped truth table of the bpy API in
this build. That table is a reference, not the language spec: it cannot see
custom properties, ID-property keys or anything added after it was dumped.
Every one of those used to look like a refusal while the gate still had an
``ok`` flag, which is why the flag is gone and these tests exist.

The property that matters most is the last group: for ANY input,
prepare_script returns a report instead of raising.
"""

import importlib

import pytest

_VALIDATOR = "mixar.modules.space_mixie_chat.core.script_validator"


@pytest.fixture(scope="module")
def gate():
    """The real validator, with the real truth table (loaded once)."""
    return importlib.import_module(_VALIDATOR)


# --- the contract: no veto power -------------------------------------------

def test_report_exposes_no_way_to_veto(gate):
    """A boolean verdict is what made this a hard gate. It must not come back."""
    report = gate.prepare_script("__RESULT__ = 1")

    for veto_field in ("ok", "allowed", "valid", "blocked", "passed", "should_run"):
        assert not hasattr(report, veto_field)


def test_a_script_full_of_bad_attributes_is_still_handed_back(gate):
    """Reporting every problem must not remove, rewrite or withhold the code."""
    script = (
        "import bpy\n"
        "ob = bpy.data.objects[0]\n"
        "ob.definitely_not_a_property = 3\n"
        "bpy.ops.object.also_not_an_operator()\n"
    )

    report = gate.prepare_script(script)

    assert report.issues, "the invented attributes should have been reported"
    assert report.normalized == script, "the gate may not edit a script it dislikes"


def test_warnings_reach_the_report_without_blocking(gate):
    """The advice channel is what replaces the veto: warn, and let it run."""
    report = gate.prepare_script(
        "import bpy\nob = bpy.data.objects[0]\nob.nope = 1\n"
    )

    assert report.warnings
    assert report.warnings[0] in report.issues
    assert report.clean is False


def test_warnings_are_capped(gate):
    """An agent inventing 40 properties gets the lesson once, not 40 times."""
    report = gate.GateReport(issues=[f"issue {n}" for n in range(40)])

    shown = report.warnings

    assert len(shown) == gate.MAX_REPORTED_ISSUES + 1
    assert "further issue" in shown[-1]


# --- what it actually catches ----------------------------------------------

def test_a_real_attribute_is_left_alone(gate):
    report = gate.prepare_script(
        "import bpy\nob = bpy.data.objects[0]\n__RESULT__ = ob.location[:]\n"
    )

    assert report.issues == []
    assert report.clean is True


def test_custom_properties_are_not_flagged(gate):
    """The false positive that made a hard gate unusable.

    ``ob["my_custom"]`` is an ID property key, not an attribute lookup, and the
    truth table has no idea what an agent named its own properties. A gate that
    flagged these blocked working scripts on every turn.
    """
    report = gate.prepare_script(
        "import bpy\n"
        "ob = bpy.data.objects[0]\n"
        "ob['my_custom'] = 1\n"
        "__RESULT__ = ob['my_custom']\n"
    )

    assert report.issues == []



def test_invented_attributes_are_named_with_suggestions(gate):
    report = gate.prepare_script(
        "import bpy\nme = bpy.data.meshes.new('m')\nme.also_not_real = 3\n"
    )

    assert len(report.issues) == 1
    assert "also_not_real" in report.issues[0]
    assert "bpy.types.Mesh" in report.issues[0]


def test_invented_operators_are_reported(gate):
    report = gate.prepare_script("import bpy\nbpy.ops.object.nope_not_here()\n")

    assert any("nope_not_here" in issue for issue in report.issues)


# --- a half-loaded truth table must not invent problems ---------------------

def test_a_property_is_never_called_a_method_without_its_type_map(gate, monkeypatch):
    """The memory-gated load keeps the dir() table and drops the type maps.

    Without a type map every property looks exactly like a method, so the
    subscript check used to announce that `ob.location` is not a property -
    under memory pressure, on every script the agent wrote. A confident wrong
    answer is worse than silence, because the model cannot tell which one it
    got, and the gate only gets to speak when it is sure.
    """
    monkeypatch.setattr(gate, "BPy_TYPES", {})

    issues = gate.validate_bpy_properties(
        "import bpy\n"
        "ob = bpy.data.objects[0]\n"
        "ob.location[:] = (1, 2, 3)\n"
        "__RESULT__ = ob.location[:]\n"
    )

    assert issues == []


def test_socket_writes_are_not_judged_without_their_type_maps(gate, monkeypatch):
    """The socket verdict is about a whole family; an empty family proves nothing."""
    monkeypatch.setattr(gate, "BPy_TYPES", {})

    assert gate._generic_socket_access_issue("default_value", True) is None


# --- normalization: the part that helps for free ----------------------------

def test_known_bad_idioms_are_rewritten_before_execution(gate):
    """use_nodes is deprecated here and warns at runtime; the rewrite is free."""
    script = "import bpy\nmat = bpy.data.materials.new('m')\nmat.use_nodes = True\n"

    report = gate.prepare_script(script)

    assert report.normalized != script
    assert "use_nodes" not in report.normalized
    assert report.notes
    assert report.issues == []


def test_a_script_needing_no_rewrite_is_returned_byte_identical(gate):
    script = "__RESULT__ = 1 + 1\n"

    assert gate.prepare_script(script).normalized == script


# --- never raises -----------------------------------------------------------

def test_syntax_errors_are_reported_not_raised(gate):
    report = gate.prepare_script("def broken(:\n    pass\n")

    assert report.syntax_error
    assert report.issues
    assert "line 1" in report.syntax_error


@pytest.mark.parametrize("junk", [
    None, "", "   \n", 12345, [], {}, b"__RESULT__ = 1", object(),
    "def (:", "(", "x =" * 5000, "\x00\x01\x02", "\N{SNOWMAN}" * 100,
    "﻿import bpy\n", "if True:\n", "class Broken(:\n    pass\n",
])
def test_prepare_script_never_raises(gate, junk):
    """THE contract of a soft gate.

    Whatever the agent produced - empty, binary, truncated mid-token - the
    executor still gets a report and still runs something. A gate that can
    raise is a gate that can take the app down with a bad model reply.
    """
    report = gate.prepare_script(junk)

    assert isinstance(report.normalized, str)
    assert isinstance(report.issues, list)
    assert isinstance(report.warnings, list)


def test_blind_validation_still_produces_a_report(gate, monkeypatch):
    """A missing or corrupt table must degrade to advice-free, not to failure."""
    def explode(_src):
        raise OSError("table gone")

    monkeypatch.setattr(gate, "validate_bpy_properties", explode)

    report = gate.prepare_script("import bpy\nbpy.data.objects[0].whatever = 1\n")

    assert report.issues == []
    assert report.normalized.startswith("import bpy")


def test_a_failure_inside_normalization_cannot_stop_the_script(gate, monkeypatch):
    def explode(_script):
        raise RuntimeError("bug in a rewrite rule")

    monkeypatch.setattr(gate, "normalize_mixar_script", explode)
    script = "import bpy\nbpy.data.objects[0].location = (1, 2, 3)\n"

    report = gate.prepare_script(script)

    assert report.normalized == script, "run exactly what we were given"
    assert any("Normalization was skipped" in issue for issue in report.issues)
