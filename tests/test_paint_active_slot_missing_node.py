# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""``set_active_paint_slot_entity`` with no active MPaint node.

Crash signature 8894a574 (4.4.2, Windows): changing the active paint layer ran
``update_layer_index`` -> ``set_active_paint_slot_entity``, whose first line
``node.select = True`` raised ``AttributeError: 'NoneType' object has no
attribute 'select'`` when the material's active node was not the MPaint group
node. The real function runs out of ``update_image.py`` against stubs.
"""

import ast
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
UPDATE_IMAGE = ROOT / "src/scripts/mixar/modules/paint/core/element/update_image.py"


class _Nodes(list):
    def __init__(self, items=()):
        super().__init__(items)
        self.active = None

    def get(self, name):
        return next((node for node in self if node.name == name), None)


def _node(name, node_tree=None):
    return SimpleNamespace(name=name, node_tree=node_tree, select=False, image=None)


def _run(*, obj, mat, active_node, mp, layer=None):
    tree = ast.parse(UPDATE_IMAGE.read_text())
    fn = next(node for node in tree.body
              if isinstance(node, ast.FunctionDef) and node.name == "set_active_paint_slot_entity")
    image_paint = SimpleNamespace(mode=None, canvas="untouched")
    scene = SimpleNamespace(tool_settings=SimpleNamespace(image_paint=image_paint))
    context = SimpleNamespace(scene=scene, window_manager=SimpleNamespace(mpprops=SimpleNamespace()))
    calls = []
    ns = dict(
        get_active_material=lambda: mat,
        get_active_mpaint_node=lambda: active_node,
        get_active_object=lambda: obj,
        get_bpy_context=lambda: context,
        get_active_layer_safe=lambda _mp: layer,
        get_tree=lambda _layer: None,
        get_editor_images_dict=lambda return_pins=False: ({}, {}),
        set_editor_images=lambda *a: calls.append("set_editor_images"),
        update_image_editor_image=lambda *a: calls.append("update_image_editor_image"),
    )
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(UPDATE_IMAGE), "exec"), ns)
    result = ns["set_active_paint_slot_entity"](mp)
    return result, image_paint, calls


def _mesh(materials=1):
    return SimpleNamespace(type="MESH", data=SimpleNamespace(materials=[None] * materials))


def test_the_group_node_of_this_tree_is_used_when_no_mpaint_node_is_active():
    root_tree = SimpleNamespace(nodes=_Nodes())
    group = _node("MPaint", node_tree=root_tree)
    mat = SimpleNamespace(node_tree=SimpleNamespace(nodes=_Nodes([_node("Principled BSDF"), group])))
    mp = SimpleNamespace(id_data=root_tree, use_baked=False, channels=[], layers=[])

    _result, image_paint, calls = _run(obj=_mesh(), mat=mat, active_node=None, mp=mp)

    assert group.select is True
    assert mat.node_tree.nodes.active is group
    assert image_paint.mode == "IMAGE"  # the paint slot is still set
    assert calls == ["set_editor_images", "update_image_editor_image"]


def test_a_material_without_the_group_node_does_not_raise():
    root_tree = SimpleNamespace(nodes=_Nodes())
    mat = SimpleNamespace(node_tree=SimpleNamespace(nodes=_Nodes([_node("Principled BSDF")])))
    mp = SimpleNamespace(id_data=root_tree, use_baked=False, channels=[], layers=[])

    _result, image_paint, _calls = _run(obj=_mesh(), mat=mat, active_node=None, mp=mp)

    assert mat.node_tree.nodes.active is None
    assert image_paint.mode == "IMAGE"


def test_no_active_object_or_material_is_a_no_op():
    mp = SimpleNamespace(id_data=SimpleNamespace(nodes=_Nodes()), use_baked=False, channels=[], layers=[])
    mat = SimpleNamespace(node_tree=SimpleNamespace(nodes=_Nodes()))
    for obj, material in ((None, mat), (_mesh(), None), (_mesh(), SimpleNamespace(node_tree=None))):
        result, image_paint, calls = _run(obj=obj, mat=material, active_node=None, mp=mp)
        assert result is None and image_paint.canvas == "untouched" and calls == []


def test_a_layer_whose_group_node_is_gone_does_not_raise():
    root_tree = SimpleNamespace(nodes=_Nodes())
    group = _node("MPaint", node_tree=root_tree)
    mat = SimpleNamespace(node_tree=SimpleNamespace(nodes=_Nodes([group])))
    layer = SimpleNamespace(group_node="Layer 1 (deleted)", masks=[], channels=[])
    mp = SimpleNamespace(id_data=root_tree, use_baked=False, channels=[], layers=[layer])

    result, image_paint, calls = _run(obj=_mesh(), mat=mat, active_node=group, mp=mp, layer=layer)

    assert result is None and image_paint.canvas == "untouched" and calls == []
