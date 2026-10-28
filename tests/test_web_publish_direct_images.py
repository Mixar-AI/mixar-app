# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Direct maps must be equivalent to the live fill and leave no staged state."""

from contextlib import nullcontext
import sys
from types import ModuleType, SimpleNamespace as NS

import pytest

from mixar.modules.web_publish.core import direct_paint_images as direct
from mixar.modules.space_mixie_chat.core import export_preflight


@pytest.fixture
def pbr(monkeypatch):
    class Nodes(dict):
        active = None

        def new(self, kind):
            node = NS(name=f'Temporary_{len(self)}', image=None)
            self[node.name] = node
            return node

        def remove(self, node):
            del self[node.name]

    names = ['Color', 'Metallic', 'Roughness', 'Normal']
    targets = dict(zip(names, ['Base Color', 'Metallic', 'Roughness', 'Normal']))
    roots = [NS(name=name, type='NORMAL' if name == 'Normal' else 'RGB',
                modifiers=[], enable_alpha=False, baked='Old_'+name) for name in names]
    images = [NS(name=name, source='FILE') for name in names]
    channels = [NS(enable=True, modifiers=[], blend_type='MIX', intensity_value=1,
                   override=True, override_type='IMAGE', normal_map_type='NORMAL_MAP',
                   override_1=True, override_1_type='IMAGE', normal_strength=1,
                   image_node=NS(type='TEX_IMAGE', image=image,
                                 interpolation='Cubic' if i == 3 else 'Linear'))
                for i, image in enumerate(images)]
    layer = NS(enable=True, type='COLOR', parent_idx=-1, texcoord_type='UV', masks=[],
               modifiers=[], translation=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1),
               intensity_value=1, blend_linked=True, linked_blend_type='MIX', uv_name='UV Map',
               channels=channels, enable_uniform_scale=False, uniform_scale_value=1)
    mp = NS(use_baked=False, halt_update=False, channels=roots, layers=[layer])
    nodes = Nodes({root.baked: NS(name=root.baked, image=None) for root in roots})
    tree = NS(nodes=nodes, mp=mp, as_pointer=lambda: 34)
    shader = NS(type='BSDF_PRINCIPLED', inputs={'Alpha': NS(is_linked=False, default_value=1)})
    output = NS(type='OUTPUT_MATERIAL', is_active_output=True,
                inputs={'Surface': NS(links=[NS(from_node=shader)])})
    node = NS(node_tree=tree, inputs=[], id_data=NS(nodes=[output]),
              outputs={name: NS(links=[NS(to_node=shader, to_socket=NS(name=targets[name]))])
                       for name in names})
    material = NS(name='PBR')
    obj = NS(data=NS(materials=[material], uv_layers=[NS(name='UV Map', active_render=True)]))

    def module(name, **attrs):
        value = ModuleType(name)
        value.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, value)

    prefix = 'mixar.modules.paint.'
    module(prefix+'core.layer.check_layers', is_any_layer_using_channel=lambda *_: True)
    module(prefix+'core.node.get_nodes', get_channel_source=lambda ch, _: ch.image_node,
           get_channel_source_1=lambda ch, _: ch.image_node)
    module(prefix+'core.io.utils.bsdf_connections', get_bsdf_socket_name=targets.get)
    module(prefix+'utils.common_entity', get_entity_prop_value=lambda entity, prop: getattr(entity, prop))
    monkeypatch.setattr(export_preflight, 'active_mixar_nodes', lambda mat: [node] if mat is material else [])
    return NS(obj=obj, node=node, tree=tree, layer=layer, channels=channels, images=images,
              roots=roots, mp=mp, shader=shader)


def test_existing_pbr_maps_include_the_normal_override_image(pbr):
    assert direct.direct_images(pbr.obj, pbr.node) == list(zip(pbr.roots, pbr.images))


@pytest.mark.parametrize('change', ['mask', 'layer', 'opacity', 'translation', 'uniform_scale',
                                  'uv', 'modifier', 'normal_strength', 'transparent', 'tiled'])
def test_compositing_and_nonidentity_materials_stay_on_bake_path(pbr, change):
    if change == 'mask': pbr.layer.masks.append(object())
    if change == 'layer': pbr.mp.layers.append(pbr.layer)
    if change == 'opacity': pbr.channels[0].intensity_value = 0.5
    if change == 'translation': pbr.layer.translation = (1, 0, 0)
    if change == 'uniform_scale':
        pbr.layer.enable_uniform_scale = True
        pbr.layer.uniform_scale_value = 2
    if change == 'uv': pbr.obj.data.uv_layers[0].name = 'Different'
    if change == 'modifier': pbr.roots[0].modifiers.append(object())
    if change == 'normal_strength': pbr.channels[3].normal_strength = 2
    if change == 'transparent': pbr.shader.inputs['Alpha'].default_value = 0.5
    if change == 'tiled': pbr.images[0].source = 'TILED'
    assert direct.direct_images(pbr.obj, pbr.node) is None


@pytest.mark.parametrize('export_fails', [False, True])
def test_export_bindings_are_temporary_even_on_failure(pbr, export_fails):
    old_bindings = [root.baked for root in pbr.roots]
    with pytest.raises(ValueError) if export_fails else nullcontext():
        with direct.staged_direct_paint_images([pbr.obj]):
            assert pbr.mp.use_baked
            assert [pbr.tree.nodes[root.baked].image for root in pbr.roots] == pbr.images
            if export_fails: raise ValueError('export failure')
    assert not pbr.mp.use_baked and not pbr.mp.halt_update
    assert [root.baked for root in pbr.roots] == old_bindings
    assert list(pbr.tree.nodes) == old_bindings


def test_shared_stack_requires_matching_uvs_on_every_exported_object(pbr):
    other = NS(data=NS(materials=pbr.obj.data.materials,
                       uv_layers=[NS(name='Other UV', active_render=True)]))
    with direct.staged_direct_paint_images([pbr.obj, other]):
        assert not pbr.mp.use_baked
        assert all(pbr.tree.nodes[root.baked].image is None for root in pbr.roots)


def test_default_white_emission_color_is_inert_with_zero_strength(pbr):
    pbr.shader.inputs['Emission Color'] = NS(is_linked=False, default_value=(1, 1, 1, 1))
    pbr.shader.inputs['Emission Strength'] = NS(is_linked=False, default_value=0)
    assert direct.direct_images(pbr.obj, pbr.node)
    pbr.shader.inputs['Emission Strength'].default_value = 1
    assert direct.direct_images(pbr.obj, pbr.node) is None
