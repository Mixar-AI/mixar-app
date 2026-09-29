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


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "src/scripts/mixar/modules/workflow"
TOOLBAR_CC = ROOT / "src/source/blender/editors/interface/mixar/toolbar.cc"


def _num_slider_branch():
    source = TOOLBAR_CC.read_text()
    start = source.index("if (ELEM(button.type, ButtonType::Num, ButtonType::NumSlider))")
    return source[start:source.index("return false;", start)]


def test_brightness_value_owns_a_column_the_slider_track_never_enters():
    # Regression: the track ended at a hard-coded 44px, so "5000.000" was drawn
    # over the track and thumb. The track must end before the measured value.
    branch = _num_slider_branch()
    assert "fontstyle_string_width(&font, value.c_str())" in branch
    assert "float(text.xmax) - value_width" in branch
    assert "std::min(cell.xmax - 44 * u" in branch
    # One fixed column for every light type, so Point/Sun tracks line up.
    assert 'fontstyle_string_width(&font, "00000")' in branch
    # The measured string is the one drawn.
    assert "mixar_card_draw_text(font, &text, value.c_str()" in branch
    assert "button.drawstr.c_str(), text_color, UI_STYLE_TEXT_RIGHT" not in branch


def test_brightness_label_uses_compact_precision_with_native_units():
    source = TOOLBAR_CC.read_text()
    start = source.index("std::string adaptive_light_energy_label(")
    body = source[start:source.index("\n}\n", start)]
    assert "value >= 100.0 ? 0 : value >= 10.0 ? 1 : 2" in body
    assert "button_string_get_ex(&button" in body
    # Range and formatting share one light-energy predicate.
    assert source.count("adaptive_light_energy(button)") >= 3


def _operator_calls(path):
    tree = ast.parse(path.read_text())
    return [n.args[0].value for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "operator"
            and n.args and isinstance(n.args[0], ast.Constant)]


@pytest.mark.parametrize("header", ["zen_object_controls.py", "zen_scene_controls.py"])
def test_close_and_restore_have_meaningful_tooltips(header):
    # wm.context_toggle's tooltip is the generic "Context Toggle / Toggle a context value".
    calls = _operator_calls(WORKFLOW / "ui/headers" / header)
    assert "wm.context_toggle" not in calls
    assert "mixar.zen_object_controls_show" in calls


def test_object_controls_operator_describes_both_directions():
    tree = ast.parse((WORKFLOW / "ui/operators/zen_object_controls.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    fields = {t.targets[0].id: t.value.value for t in cls.body
              if isinstance(t, ast.Assign) and isinstance(t.value, ast.Constant)}
    assert fields["bl_idname"] == "mixar.zen_object_controls_show"
    assert fields["bl_description"].strip()
    describe = next(n for n in cls.body
                    if isinstance(n, ast.FunctionDef) and n.name == "description")
    texts = [n.value for n in ast.walk(describe)
             if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert any(t.startswith("Show") for t in texts)
    assert any(t.startswith("Hide") for t in texts)
    source = ast.unparse(cls)
    assert "show_region_tool_header = self.show" in source


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
