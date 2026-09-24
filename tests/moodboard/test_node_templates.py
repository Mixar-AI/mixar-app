# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Templates remain catalog gated and preserve click/drop placement semantics."""

from types import SimpleNamespace as NS

import pytest


def test_unavailable_or_unknown_template_cannot_mutate_the_board(monkeypatch):
    from mixar.modules.moodboard.core import node_templates as templates

    monkeypatch.setattr(templates, 'capability_available', lambda key, **kwargs: False)
    for template in ('IMAGE_GEN', 'VIDEO_GEN', 'UNKNOWN'):
        with pytest.raises(ValueError, match='available generation model'):
            templates.create_template(None, template, (0, 0))


def test_catalog_gate_filters_the_surface_and_requires_a_model(monkeypatch):
    from mixar.bootstrap import generation_catalog_cache as catalog
    from mixar.modules.moodboard.core.capabilities import capability_available

    calls = []

    def services(capability, *, surface):
        calls.append((capability, surface))
        return [{'key': 'draft_only'}]

    monkeypatch.setattr(catalog, 'get_services', services)
    monkeypatch.setattr(catalog, 'get_models', lambda key: [])
    assert not capability_available('image_gen')
    monkeypatch.setattr(catalog, 'get_models', lambda key: [{'slug': 'available'}])
    assert capability_available('image_gen')
    assert calls == [('image_gen', 'moodboard')] * 2


def _scene():
    class Nodes(list):
        def add(self):
            node = NS(node_id='', width=520., height=260., position_x=0., position_y=0.,
                      selected=False, input_sockets=[], state='DRAFT', prompt='',
                      job_id='', preview_image=None)
            self.append(node)
            return node

    class Links(list):
        def add(self):
            link = NS(link_id='', from_node_id='', to_node_id='', from_socket='',
                      to_socket='', input_order=0)
            self.append(link)
            return link

        def remove(self, index):
            del self[index]

    return NS(mixie_moodboard_images=[], mixie_moodboard_action_nodes=Nodes(),
              mixie_moodboard_asset_nodes=[], mixie_moodboard_links=Links(),
              mixie_moodboard_active_node_id='')


def test_clicks_avoid_overlap_and_drops_use_the_release_position(monkeypatch):
    from mixar.modules.moodboard.core import node_graph, node_templates

    scene = _scene()
    monkeypatch.setattr(node_templates, 'capability_available', lambda key, **kwargs: True)
    monkeypatch.setattr(node_graph, '_initialize_catalog_selection', lambda scene, node: None)
    first = node_templates.create_template(scene, 'IMAGE_GEN', (100, 200))
    second = node_templates.create_template(scene, 'IMAGE_GEN', (100, 200))
    assert first.node_id != second.node_id
    assert not first.selected and second.selected
    assert (first.position_x, first.position_y) != (second.position_x, second.position_y)
    assert all(n.state == 'DRAFT' and not n.job_id for n in (first, second))
    assert scene.mixie_moodboard_active_node_id == second.node_id
    dropped = node_templates.create_template(scene, 'IMAGE_GEN', (100, 200),
                                             exact_position=True)
    assert dropped.position_x + dropped.width / 2 == 100
    assert dropped.position_y + dropped.height / 2 == 200
    assert (dropped.position_x, dropped.position_y) == (first.position_x, first.position_y)
    assert dropped.state == 'DRAFT' and not dropped.job_id


def test_drop_onto_image_attaches_beside_the_source(monkeypatch):
    from mixar.modules.moodboard.core import node_graph, node_templates
    from mixar.modules.moodboard.core.node_graph import ACTION_NODE_GAP

    scene = _scene()
    image = NS(size=(100, 80), source='FILE')
    media = NS(node_id='img-1', image=image, scale=1.0, position_x=0.0, position_y=0.0,
               selected=False, embedded_node_id='')
    scene.mixie_moodboard_images.append(media)
    monkeypatch.setattr(node_templates, 'capability_available', lambda key, **kwargs: True)
    monkeypatch.setattr(node_graph, '_initialize_catalog_selection', lambda scene, node: None)
    links = []

    def connect(scene, from_id, to_id):
        links.append((from_id, to_id))
        return NS()

    monkeypatch.setattr(node_graph, 'connect_to_next_input', connect)

    # Drop centre sits inside the still (700×560 display at scale 1).
    node = node_templates.create_template(scene, 'MODEL_3D', (350, 280), exact_position=True)
    assert links == [('img-1', node.node_id)]
    assert node.position_x == pytest.approx(700.0 + ACTION_NODE_GAP)
    assert node.position_y == pytest.approx(280.0 - node.height * 0.5)
    # The source card stays uncovered so the noodle reads as an attachment.
    assert node.position_x >= 700.0


def test_parameter_explanations_keep_catalog_description_bounds_and_required():
    from mixar.modules.moodboard.core.parameter_help import parameter_help

    help_text = parameter_help(NS(label='Duration', name='duration',
                                 description='Length of the generated clip.',
                                 parameter_type='INTEGER', minimum=2., maximum=12.,
                                 required=True))
    assert 'Length of the generated clip.' in help_text
    assert 'Range: 2 to 12' in help_text
    assert 'Required' in help_text
