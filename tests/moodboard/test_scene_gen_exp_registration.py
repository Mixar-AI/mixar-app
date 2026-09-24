# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MOODBOARD_UI = ROOT / "src/scripts/mixar/modules/moodboard/ui"
COMMON_JOB_QUEUE = ROOT / "src/scripts/mixar/modules/common/job_queue"


def read(relative_path: str) -> str:
    return (MOODBOARD_UI / relative_path).read_text(encoding="utf-8")


def read_job_queue(relative_path: str) -> str:
    return (COMMON_JOB_QUEUE / relative_path).read_text(encoding="utf-8")


def identifiers(source: str) -> set[str]:
    """Return active Python identifiers, excluding comments and strings."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.rsplit('.', 1)[-1])
    return names


def assigned_class_names(source: str) -> set[str]:
    """Return class names in the module's final ``classes`` assignment."""
    value = None
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "classes"
                for target in node.targets
            )
        ):
            value = node.value.body if isinstance(node.value, ast.IfExp) else node.value
    if not isinstance(value, (ast.Tuple, ast.List)):
        return set()
    return {
        element.id
        for element in value.elts
        if isinstance(element, ast.Name)
    }


def test_scene_gen_exp_operators_are_not_registered():
    operators = read("operators/scene_gen_exp_ops.py")
    place_ops = read("operators/scene_gen_exp_place_ops.py")
    operator_registry = identifiers(read("operators/__init__.py"))

    # The implementation remains for later reuse, but its module-level register
    # hook is deliberately a no-op and the aggregate registry does not import it.
    register = next(
        node
        for node in ast.parse(operators).body
        if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    assert len(register.body) == 1 and isinstance(register.body[0], ast.Return)
    assert assigned_class_names(place_ops) == set()
    assert "scene_gen_exp_ops" not in operator_registry


def test_scene_gen_exp_ui_list_is_not_registered():
    ui_list = read("lists/scene_gen_exp_uilist.py")
    panels = read("moodboard_sidebar_panels.py")

    assert assigned_class_names(ui_list) == set()
    assert "MIXIE_PT_gen_scene_gen_exp" not in assigned_class_names(panels)


def test_scene_gen_exp_properties_are_not_registered_on_bpy_types():
    scene_registration = read("moodboard_scene_registration.py")
    tab_properties = read("moodboard_tab_properties.py")
    queue_properties = read_job_queue("ui/properties/queue_properties.py")

    forbidden = (
        "MixieSceneGenExpBBox",
        "MixieSceneGenExpLabelObject",
        "MixieMoodboardTabSceneGenExpProps",
        "tab_scene_gen_exp",
        "mixie_scene_gen_exp_is_processing",
        "mixie_scene_gen_hp_is_generating",
        "mixie_scene_gen_lp_is_generating",
        "scene_gen_hp",
        "scene_gen_lp",
        "SCENE_GEN_EXP",
    )
    for symbol in forbidden:
        assert symbol not in identifiers(scene_registration)
        assert symbol not in identifiers(tab_properties)
        assert symbol not in identifiers(queue_properties)
