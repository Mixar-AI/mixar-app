# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Complex UV shaders must be evaluated, never replaced by their first image."""
from types import SimpleNamespace as NS

import pytest

from mixar.modules.web_publish.core import shader_textures as shader
from mixar.modules.space_mixie_chat.core import export_preflight


class Sockets(dict):
    def __iter__(self):
        return iter(self.values())


class Node:
    def __init__(self, kind, **values):
        self.type = kind
        self.inputs = Sockets()
        self.__dict__.update(values)


def socket(node=None):
    return NS(links=[NS(from_node=node)] if node else [], is_linked=bool(node))


@pytest.fixture
def graph(monkeypatch):
    monkeypatch.setattr(export_preflight, 'active_mixar_nodes', lambda _: [])
    uv = Node('UVMAP', uv_map='PaintUV')
    texture = Node('TEX_IMAGE', image=NS(source='FILE'))
    texture.inputs['Vector'] = socket(uv)
    mix = Node('MIX_RGB')
    mix.inputs['Color'] = socket(texture)
    bsdf = Node('BSDF_PRINCIPLED', name='Surface')
    bsdf.inputs = {name: socket() for name in shader.CHANNELS}
    bsdf.inputs['Base Color'] = socket(mix)
    output = Node('OUTPUT_MATERIAL', is_active_output=True)
    output.inputs['Surface'] = socket(bsdf)
    material = NS(name='Painted Floor', node_tree=NS(nodes=[output, bsdf, mix, texture, uv]))
    return NS(material=material, shader=bsdf, mix=mix, texture=texture, uv=uv)


def test_color_operations_are_baked_instead_of_following_the_first_image(graph):
    plan = shader.material_plan(graph.material)
    assert plan == {'material': 'Painted Floor', 'shader': 'Surface',
                    'channels': ['Base Color'], 'uvs': {'Base Color': 'PaintUV'}}


def test_direct_image_pbr_keeps_the_existing_export_path(graph):
    graph.shader.inputs['Base Color'] = socket(graph.texture)
    assert shader.material_plan(graph.material) is None


def test_channel_uv_maps_remain_independent(graph):
    uv = Node('UVMAP', uv_map='RoughnessUV')
    image = Node('TEX_IMAGE', image=NS(source='FILE'))
    image.inputs['Vector'] = socket(uv)
    remap = Node('MAP_RANGE')
    remap.inputs['Value'] = socket(image)
    graph.shader.inputs['Roughness'] = socket(remap)
    assert shader.material_plan(graph.material)['uvs'] == {
        'Base Color': 'PaintUV', 'Roughness': 'RoughnessUV'}


@pytest.mark.parametrize('kind', ['NEW_GEOMETRY', 'TEX_COORD', 'GROUP', 'SHADERTORGB'])
def test_geometry_dependent_inputs_stop_publication_instead_of_sampling_a_plane(graph, kind):
    graph.texture.inputs['Vector'] = socket(Node(kind))
    with pytest.raises(RuntimeError, match='geometry-dependent'):
        shader.material_plan(graph.material)


def test_implicit_generated_coordinates_cannot_be_reinterpreted_as_uv(graph):
    graph.texture.type = 'TEX_NOISE'
    graph.texture.inputs['Vector'] = socket()
    with pytest.raises(RuntimeError, match='explicit UV'):
        shader.material_plan(graph.material)


def test_two_maps_in_one_channel_require_an_object_bake(graph):
    graph.mix.inputs['Other'] = socket(Node('UVMAP', uv_map='OtherUV'))
    with pytest.raises(RuntimeError, match='single UV'):
        shader.material_plan(graph.material)


@pytest.mark.parametrize('image', [None, NS(source='TILED')])
def test_missing_and_udim_images_stop_preparation(graph, image):
    graph.texture.image = image
    with pytest.raises(RuntimeError, match='non-tiled image'):
        shader.material_plan(graph.material)


def test_mixar_paint_remains_owned_by_existing_paint_preparation(graph, monkeypatch):
    monkeypatch.setattr(export_preflight, 'active_mixar_nodes', lambda _: [object()])
    assert shader.material_plan(graph.material) is None


def test_unconnected_image_vectors_use_the_render_uv(graph):
    graph.texture.inputs['Vector'] = socket()
    assert shader.material_plan(graph.material)['uvs'] == {'Base Color': ''}
