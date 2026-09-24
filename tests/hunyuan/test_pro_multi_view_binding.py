# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Hunyuan PRO direct path binds a multi-view set by IMAGE, not by tab.

``mixie.hunyuan_generate`` (agent/chat PRO path) used to attach the Model Gen
tab's active set to whatever image it was asked to convert — the same defect
``test_turnaround_operator_wiring.py`` pins for the Model Gen operators: an
unrelated image inherited another subject's companion views. The set is now
resolved from the image it is bound to (``turnaround_main_group``).

A duplicate enqueue returned ``None`` and the operator still reported
FINISHED, so the agent waited on a job that was never queued. Both direct
paths now raise, which ``execute`` routes to ``set_agent_gen_reason`` and
CANCELLED.

``bpy.types.Operator`` is a ``MagicMock`` here, so the operator's methods are
checked at source level; the module-level helper is exercised for real.
"""

import ast
from pathlib import Path
from types import SimpleNamespace

from mixar.modules.hunyuan.ui.operators import hunyuan_ops

_OPS = Path(__file__).resolve().parents[2] / (
    "src/scripts/mixar/modules/hunyuan/ui/operators/hunyuan_ops.py")


def _tree():
    return ast.parse(_OPS.read_text(encoding="utf-8"))


def _function(name):
    for node in ast.walk(_tree()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"hunyuan_ops has no {name}")


def _names(node):
    """Every identifier referenced inside *node*."""
    found = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
        elif isinstance(child, ast.alias):
            found.add(child.asname or child.name)
    return found


def test_both_pro_paths_resolve_the_set_from_the_image():
    for method in ("_submit_pro_direct", "_resolve_turnaround"):
        names = _names(_function(method))
        assert "_pro_turnaround_group" in names, method
        assert "get_active_group" not in names, (
            f"{method} reads the set off the TAB — an unrelated image would "
            "inherit a set left over from an earlier subject")
        assert "_has_active_view_set" not in names, method


def test_the_tab_helper_is_gone():
    names = {
        node.name for node in ast.walk(_tree())
        if isinstance(node, ast.FunctionDef)
    }
    assert "_has_active_view_set" not in names
    assert "get_active_group" not in _names(_tree())


def test_the_helper_binds_through_the_main_image():
    assert "group_id_for_main_image" in _names(
        _function("_pro_turnaround_group"))


def test_the_pro_paths_keep_their_order():
    """tests/test_generation_placement.py slices between these two."""
    text = _OPS.read_text(encoding="utf-8")
    assert text.index("def _submit_pro_direct") < \
        text.index("def _resolve_turnaround")


def _raises_value_error(node):
    return any(
        isinstance(child, ast.Raise)
        and isinstance(child.exc, ast.Call)
        and isinstance(child.exc.func, ast.Name)
        and child.exc.func.id == "ValueError"
        for child in ast.walk(node)
    )


def _is_none_checks(method, callee):
    """``if <callee>(...) is None: raise ValueError`` inside *method*."""
    found = []
    for child in ast.walk(_function(method)):
        if not isinstance(child, ast.If):
            continue
        test = child.test
        if not (isinstance(test, ast.Compare)
                and len(test.ops) == 1 and isinstance(test.ops[0], ast.Is)
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value is None
                and isinstance(test.left, ast.Call)
                and isinstance(test.left.func, ast.Name)
                and test.left.func.id == callee):
            continue
        if any(_raises_value_error(stmt) for stmt in child.body):
            found.append(child)
    return found


def test_a_duplicate_enqueue_fails_loudly_on_both_direct_paths():
    assert _is_none_checks("_submit_pro_direct", "enqueue_pro_job"), (
        "a duplicate PRO enqueue returns None and must raise, not report "
        "FINISHED")
    assert _is_none_checks("_submit_rapid_direct", "enqueue_generation"), (
        "a duplicate RAPID enqueue returns None and must raise, not report "
        "FINISHED")


# ---------------------------------------------------------------------------
# _pro_turnaround_group on a real board shape
# ---------------------------------------------------------------------------

def _item(name, group="", main_of="", view="left"):
    return SimpleNamespace(
        image=SimpleNamespace(name=name), turnaround_group=group,
        turnaround_main_group=main_of, view_type=view)


def _context():
    """Turn 1's bound sheet set, plus turn 2's unrelated image."""
    items = [
        _item("ganesha_left", group="g1", view="left"),
        _item("ganesha_back", group="g1", view="back"),
        _item("ganesha_main", main_of="g1"),
        _item("dragon_front"),
    ]
    scene = SimpleNamespace(mixie_moodboard_images=items)
    return SimpleNamespace(scene=scene), {i.image.name: i.image for i in items}


def test_the_bound_main_resolves_its_set():
    context, images = _context()
    assert hunyuan_ops._pro_turnaround_group(
        context, images["ganesha_main"]) == "g1"


def test_an_unrelated_image_resolves_no_set():
    context, images = _context()
    assert hunyuan_ops._pro_turnaround_group(
        context, images["dragon_front"]) == ""
    assert hunyuan_ops._pro_turnaround_group(
        context, images["ganesha_left"]) == ""


def test_no_image_or_no_board_resolves_no_set():
    context, _images = _context()
    assert hunyuan_ops._pro_turnaround_group(context, None) == ""
    bare = SimpleNamespace(scene=SimpleNamespace())
    assert hunyuan_ops._pro_turnaround_group(
        bare, SimpleNamespace(name="x")) == ""
