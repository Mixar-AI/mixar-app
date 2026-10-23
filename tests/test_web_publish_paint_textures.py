# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Paint publication must carry fresh images or fail before upload."""

from contextlib import nullcontext
from types import SimpleNamespace as NS

import pytest

from mixar.modules.web_publish.core import paint_textures
from mixar.modules.space_mixie_chat.core import export_preflight


@pytest.fixture
def paint(monkeypatch):
    class Nodes(dict):
        active = None

    root_nodes = Nodes()
    tree = NS(nodes=root_nodes, mp=NS(use_baked=False))
    node = NS(node_tree=tree)
    original_node = object()
    material_nodes = Nodes()
    material_nodes.active = original_node
    material = NS(name='Paint', as_pointer=lambda: 17, node_tree=NS(nodes=material_nodes))
    channel = NS(name='Base Color', baked='baked_color')
    obj = NS(name='Cube', active_material_index=0, mode='OBJECT',
             data=NS(materials=[material], uv_layers=[object()]))
    other = NS(name='Other', mode='EDIT')
    selected = {'Cube': False, 'Other': True}
    obj.select_set = lambda value: selected.update(Cube=value)
    other.select_set = lambda value: selected.update(Other=value)
    context = NS(view_layer=NS(objects=NS(active=other)), selected_objects=[other])
    calls = []
    baked_image = object()
    behavior = NS(status={'FINISHED'}, create_image=True)

    def bake(*args, **kwargs):
        calls.append(kwargs)
        tree.mp.use_baked = True
        if behavior.create_image:
            root_nodes['baked_color'] = NS(image=baked_image)
        return behavior.status

    ops = NS(object=NS(
        select_all=lambda **_: selected.update(Cube=False, Other=False),
        mode_set=lambda mode: setattr(context.view_layer.objects.active, 'mode', mode),
    ), wm=NS(m_bake_channels=bake))
    monkeypatch.setattr(paint_textures.bpy, 'context', context)
    monkeypatch.setattr(paint_textures.bpy, 'ops', ops)
    monkeypatch.setattr(paint_textures.bpy, 'app', NS(is_job_running=lambda _: False))
    monkeypatch.setattr(export_preflight, 'active_mixar_nodes', lambda mat: [node] if mat is material else [])
    monkeypatch.setattr(paint_textures, '_used_channels', lambda _: [channel])
    return NS(obj=obj, other=other, context=context, selected=selected, tree=tree,
              material=material, original_node=original_node, root_nodes=root_nodes,
              calls=calls, image=baked_image, behavior=behavior)


def assert_restored(paint):
    assert paint.context.view_layer.objects.active is paint.other
    assert paint.other.mode == 'EDIT'
    assert paint.selected == {'Cube': False, 'Other': True}
    assert paint.material.node_tree.nodes.active is paint.original_node
    assert paint.obj.data.materials == [paint.material]


@pytest.mark.parametrize('export_fails', [False, True])
def test_live_stack_refreshes_stale_cache_and_restores_context(paint, export_fails):
    paint.root_nodes['baked_color'] = NS(image=object())
    with pytest.raises(ValueError) if export_fails else nullcontext():
        with paint_textures.prepared_paint_textures([paint.obj]):
            assert paint.root_nodes['baked_color'].image is paint.image
            if export_fails:
                raise ValueError('export failed')
    assert len(paint.calls) == 1
    assert paint.calls[0]['export_target_names'] == '["Cube"]'
    assert paint.tree.mp.use_baked is False
    assert_restored(paint)


@pytest.mark.parametrize('status', [{'CANCELLED'}, {'FINISHED'}])
def test_unsuccessful_bake_never_reaches_export(paint, status):
    paint.behavior.status = status
    paint.behavior.create_image = False
    with pytest.raises(RuntimeError, match='did not finish|missing baked'):
        with paint_textures.prepared_paint_textures([paint.obj]):
            pytest.fail('An incomplete bake must not export or upload a gray model')
    assert paint.tree.mp.use_baked is False
    assert_restored(paint)


def test_material_already_showing_valid_bake_is_not_rebaked(paint):
    paint.tree.mp.use_baked = True
    paint.root_nodes['baked_color'] = NS(image=paint.image)
    with paint_textures.prepared_paint_textures([paint.obj]):
        assert paint.tree.mp.use_baked is True
    assert paint.calls == []
    assert_restored(paint)
