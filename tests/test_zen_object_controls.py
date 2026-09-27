# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Selection and edit scope stay explicit across redraws and stale menus."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from mixar.modules.workflow.core.zen_object_controls import (
    selected_object, selected_modifier, editable_mesh,
)


def context(kind="MESH", selected=True, editable=True):
    obj = NS(type=kind, name="Cube", is_editable=editable,
             select_get=Mock(return_value=selected), modifiers=NS(active=None))
    return NS(workspace=NS(name="Zen Mode"), object=obj,
              mode="OBJECT", view_layer=object())


def test_deselected_active_object_does_not_leave_stale_properties():
    ctx = context(selected=False)
    assert selected_object(ctx) is None


@pytest.mark.parametrize("kind", ["MESH", "LIGHT"])
def test_selection_is_resolved_in_the_current_view_layer(kind):
    ctx = context(kind)
    assert selected_object(ctx) is ctx.object
    ctx.object.select_get.assert_called_once_with(view_layer=ctx.view_layer)


@pytest.mark.parametrize("kind", ["CAMERA", "EMPTY", "ARMATURE"])
def test_unsupported_objects_do_not_get_mesh_controls(kind):
    assert selected_object(context(kind)) is None


def test_engine_and_edit_mode_keep_their_native_controls():
    ctx = context()
    ctx.workspace.name = "Layout"
    assert selected_object(ctx) is None
    ctx.workspace.name = "Zen Mode"
    ctx.mode = "EDIT_MESH"
    assert selected_object(ctx) is None
    ctx.mode = "OBJECT"
    ctx.object = None
    assert selected_object(ctx) is None


def test_read_only_mesh_keeps_inspection_but_cannot_add_modifiers():
    ctx = context(editable=False)
    assert selected_object(ctx) is ctx.object
    assert editable_mesh(ctx) is None


def test_menu_target_is_revalidated_after_selection_or_name_changes():
    ctx = context()
    assert editable_mesh(ctx, "Cube") is ctx.object
    assert editable_mesh(ctx, "Previous selection") is None
    assert editable_mesh(context("LIGHT")) is None


def test_any_active_modifier_is_preserved_on_draw():
    ctx = context()
    modifier = NS(type="NODES")
    ctx.object.modifiers.active = modifier
    assert selected_modifier(ctx.object) is modifier
    assert ctx.object.modifiers.active is modifier


def test_same_type_modifier_instances_remain_distinct():
    ctx = context()
    first, second = NS(type="BEVEL", name="Bevel"), NS(type="BEVEL", name="Bevel.001")
    ctx.object.modifiers.active = second
    assert selected_modifier(ctx.object) is second
    assert selected_modifier(ctx.object) is not first


def test_stale_add_action_cancels_without_changing_either_object():
    path = Path(__file__).parents[1] / "src/scripts/mixar/modules/workflow/ui/operators/zen_modifiers.py"
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MIXAR_OT_zen_add_modifier")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "execute")
    namespace = {"editable_mesh": editable_mesh}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    ctx = context()
    ctx.object.modifiers.new = Mock()
    op = NS(object_name="Previous selection", report=Mock())
    assert namespace["execute"](op, ctx) == {"CANCELLED"}
    ctx.object.modifiers.new.assert_not_called()
