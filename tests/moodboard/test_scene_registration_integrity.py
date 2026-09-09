# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene property registration must not be able to fail halfway.

`register()` registers the moodboard's Scene properties one call at a time. An
exception anywhere in that run aborts it, so every property declared AFTER the
failure is silently missing -- and the first symptom is an unrelated panel
drawer dying on `scene.mixie_moodboard_sidebar` at every redraw, with nothing
pointing at the real cause.

`_safe_scene_prop` guards the `setattr` itself, but not its own call signature:
passing it the wrong number of arguments raises before the guard is reached.
Parsed rather than executed, so this holds without a Blender runtime.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_UI = ROOT / "src/scripts/mixar/modules/moodboard/ui"
REGISTRATION = _UI / "moodboard_scene_registration.py"
# The transient canvas-interaction props register from their own module but
# through the same guarded helper, so the arity rule has to cover it too.
TRANSIENT = _UI / "moodboard_graph_transient_props.py"

_TREE = ast.parse(REGISTRATION.read_text(encoding="utf-8"))
_TRANSIENT_TREE = ast.parse(TRANSIENT.read_text(encoding="utf-8"))


def _prop_calls(helper: str, tree=None):
    """(name, call) for every `helper('name', ...)` in the module."""
    found = []
    for node in ast.walk(tree if tree is not None else _TREE):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != helper:
            continue
        first = node.args[0] if node.args else None
        name = first.value if isinstance(first, ast.Constant) else None
        found.append((name, node))
    return found


def _string_list(function_name: str) -> set:
    """Every string literal in the named function's list literals."""
    for node in _TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return {
                element.value
                for inner in ast.walk(node)
                if isinstance(inner, (ast.List, ast.Tuple))
                for element in inner.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
    raise AssertionError(f"{function_name}() not found")


def test_every_property_helper_is_called_with_exactly_a_name_and_a_property():
    """Extra positional arguments raise a TypeError at register() time, taking
    every later property down with them. This is not hypothetical: a scripted
    edit once spliced three property NAMES into one of these calls, which left
    `mixie_moodboard_sidebar` unregistered and broke the whole sidebar."""
    for helper in ("_safe_scene_prop", "_safe_wm_prop"):
        calls = _prop_calls(helper) + _prop_calls(helper, _TRANSIENT_TREE)
        assert calls, f"no {helper} calls found -- has it been renamed?"
        for name, call in calls:
            assert len(call.args) == 2 and not call.keywords, (
                f"{helper}({name!r}, ...) takes a name and a property, "
                f"but got {len(call.args)} positional arguments"
            )


def test_registered_scene_properties_are_all_unregistered():
    """A property left off the teardown list survives an add-on reload and
    shadows the fresh registration; one registered only in teardown is a typo
    that silently never existed."""
    # Names built in a loop (`f"mixie_moodboard_context_{axis}"`) cannot be
    # matched statically, so they are skipped rather than reported as missing.
    registered = {
        name
        for name, _ in (
            _prop_calls("_safe_scene_prop")
            + _prop_calls("_safe_scene_prop", _TRANSIENT_TREE)
        )
        if isinstance(name, str)
    }
    removed = _string_list("unregister")

    missing = sorted(registered - removed)
    assert not missing, f"registered but never removed: {missing}"
