# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exercise the importer method without Blender's UI/context-dependent operators."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

NODE = Path(__file__).resolve().parents[2] / 'src/scripts/addons_core/io_scene_gltf2/blender/imp/node.py'


@pytest.fixture
def display():
    tree = ast.parse(NODE.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'BlenderNode')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'armature_display')
    method.decorator_list = []
    bpy, bmesh = MagicMock(), MagicMock()
    # No context or operator is available, as with a mismatched import context.
    bpy.context = None
    bpy.ops = None
    collection = MagicMock()
    bpy.data.collections = {'helpers': collection}
    shape = SimpleNamespace(name='Icosphere.003')
    bpy.data.objects.new.return_value = shape
    ns = dict(bpy=bpy, bmesh=bmesh, BLENDER_GLTF_SPECIAL_COLLECTION='helpers')
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(NODE), 'exec'), ns)
    gltf = SimpleNamespace(import_settings={'disable_bone_shape': False}, blender_scene='Scene')
    obj = SimpleNamespace(data=SimpleNamespace())
    return SimpleNamespace(call=ns['armature_display'], bpy=bpy, bmesh=bmesh,
                           collection=collection, gltf=gltf, obj=obj, shape=shape)


def test_shape_links_directly_without_context_or_operator(display):
    d = display
    d.call(d.gltf, d.obj)
    assert d.obj.show_in_front is True
    assert d.obj.data.relation_line_position == 'HEAD'
    assert d.gltf.bone_shape == d.shape.name
    d.collection.objects.link.assert_called_once_with(d.shape)
    d.collection.objects.unlink.assert_not_called()
    bm = d.bmesh.new.return_value
    d.bmesh.ops.create_icosphere.assert_called_once_with(bm, subdivisions=2, radius=1.0)
    bm.to_mesh.assert_called_once_with(d.bpy.data.meshes.new.return_value)
    bm.free.assert_called_once()


def test_disabled_shapes_still_set_armature_display(display):
    d = display
    d.gltf.import_settings['disable_bone_shape'] = True
    d.call(d.gltf, d.obj)
    assert d.obj.show_in_front and d.obj.data.relation_line_position == 'HEAD'
    assert not hasattr(d.gltf, 'bone_shape')
    d.bmesh.new.assert_not_called()
    d.bpy.data.objects.new.assert_not_called()


def test_bmesh_freed_and_geometry_failure_not_swallowed(display):
    d = display
    d.bmesh.ops.create_icosphere.side_effect = RuntimeError('geometry failed')
    with pytest.raises(RuntimeError, match='geometry failed'):
        d.call(d.gltf, d.obj)
    d.bmesh.new.return_value.free.assert_called_once()
    d.collection.objects.link.assert_not_called()
