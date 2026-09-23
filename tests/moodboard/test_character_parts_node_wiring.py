# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Character Parts preserves saved type indices and consumes one masked still."""

from types import SimpleNamespace as NS

import pytest

from mixar.modules.moodboard.core.character_parts_schema import require_character_image
from mixar.modules.moodboard.core.node_graph import (
    _ACCEPTED_SOURCE_TYPES, _selected_media, create_connected_action,
)
from mixar.modules.moodboard.core.node_schema import (
    _PROMPTLESS_ACTION_TYPES, _capability_for_action, output_type_for_action,
    services_for_action,
)
from mixar.modules.moodboard.ui.moodboard_graph_properties import (
    ACTION_TYPES, capability_for_action,
)


def test_append_only_character_type_and_mesh_output():
    assert [item[0] for item in ACTION_TYPES] == [
        'IMAGE_GEN', 'VIDEO_GEN', 'MODEL_3D', 'MASK_DETAIL', 'PBR_GEN',
        'RETOPOLOGY', 'MESH_SEGMENT', 'AUTO_RIG', 'VIDEO_UPSCALE', 'WORLD_LABS',
        'CHARACTER_PARTS', 'ASSEMBLE',
    ]
    assert output_type_for_action('CHARACTER_PARTS') == 'MESH'
    assert capability_for_action('CHARACTER_PARTS') == 'character_parts'
    assert _capability_for_action('CHARACTER_PARTS') == 'character_parts'
    assert 'CHARACTER_PARTS' in _PROMPTLESS_ACTION_TYPES
    assert _ACCEPTED_SOURCE_TYPES['CHARACTER_PARTS'] == {'IMAGE'}


def test_only_scene_gen_is_executable_for_character_parts():
    allowed = {'key': 'scene_gen'}
    assert services_for_action('CHARACTER_PARTS', [
        {'key': 'image_gen'}, allowed, {'key': 'model_3d'},
    ]) == [allowed]


def test_missing_catalog_socket_still_requires_one_image():
    contract = {'sockets': [], 'limits': {}}
    require_character_image(contract)
    assert contract['limits'] == {'IMAGE': 1}
    assert contract['sockets'] == [{
        'id': 'image', 'label': 'Image', 'group_id': 'image',
        'accepted_types': ['IMAGE'], 'required': True, 'repeatable': False,
    }]


def test_catalog_socket_identity_survives_required_single_image_contract():
    contract = {'sockets': [{'id': 'source:0', 'label': 'Character reference',
                             'accepted_types': ['IMAGE'], 'required': False},
                            {'id': 'source:1', 'accepted_types': ['IMAGE']}],
                'limits': {'IMAGE': 2}}
    require_character_image(contract)
    assert len(contract['sockets']) == 1
    assert contract['sockets'][0]['id'] == 'source:0'
    assert contract['sockets'][0]['required']
    assert not contract['sockets'][0]['repeatable']
    assert contract['limits'] == {'IMAGE': 1}


def test_character_source_selection_ignores_movies_and_uses_one_still():
    movie = NS(selected=True, image=NS(source='MOVIE'))
    first = NS(selected=True, image=NS(source='FILE'))
    second = NS(selected=True, image=NS(source='FILE'))
    scene = NS(mixie_moodboard_images=[movie, first, second])
    assert _selected_media(scene, 'CHARACTER_PARTS') == [first]


def test_missing_source_explains_masks_before_allocating_node():
    scene = NS(mixie_moodboard_images=[])
    with pytest.raises(ValueError, match='selected image with component masks'):
        create_connected_action(scene, 'CHARACTER_PARTS')
