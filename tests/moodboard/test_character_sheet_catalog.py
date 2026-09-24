# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""The Character Sheet to 3D template is offered only when its build can wire."""

import pytest

from mixar.bootstrap import generation_catalog_cache as catalog
from mixar.modules.moodboard.core import node_templates
from mixar.modules.moodboard.core.character_sheet_catalog import preflight

REFERENCES = {'inputs': [{'kind': 'image', 'name': 'reference_images', 'multiple': True}],
              'cost_multiplier_param': 'number_of_images'}
ONE_IMAGE = {'inputs': [{'kind': 'image', 'name': 'image'}]}


def image_model(slug, refs=4, **extra):
    model = {'slug': slug, 'max_reference_images': refs}
    model.update(extra)
    return model


def capability(key, service_key, models, **service):
    record = {'key': service_key, 'surface': 'moodboard', 'models': models}
    record.update(service)
    return {'key': key, 'services': [record]}


def rich(image_models=None, image_key='image_gen', image_spec=REFERENCES,
         model3d_spec=ONE_IMAGE, model3d_models=None, rig=True):
    capabilities = [
        capability('image_gen', image_key, image_models or [image_model('qa')],
                   input_spec=image_spec),
        capability('model_gen', 'image_to_3d', model3d_models or [{'slug': 'qa3d'}],
                   input_spec=model3d_spec),
    ]
    if rig:
        capabilities.append(capability('animate', 'animate', [{'slug': 'rig'}]))
    return {'capabilities': capabilities}


@pytest.fixture
def board(monkeypatch):
    def use(payload):
        monkeypatch.setattr(catalog, '_catalog', payload)
    return use


def visible():
    return {item[0] for item in node_templates.available_templates()}


def test_rich_catalog_offers_the_workflow_with_its_models(board):
    board(rich())
    assert preflight() == ('qa', 4, 'image_to_3d', 'qa3d')
    assert 'CHARACTER_SHEET_3D' in visible()
    assert node_templates.template_available('CHARACTER_SHEET_3D')


def test_hidden_without_an_image_gen_reference_socket(board):
    board(rich(image_spec={'inputs': []}))
    assert preflight() is None
    assert 'CHARACTER_SHEET_3D' not in visible()
    # A repeatable input without a published ceiling mints no socket either,
    # and the run refuses references the model publishes no limit for.
    board(rich(image_models=[{'slug': 'qa'}]))
    assert preflight() is None
    assert 'IMAGE_GEN' in visible() and 'CHARACTER_SHEET_3D' not in visible()


def test_hidden_without_a_model_3d_image_socket(board):
    board(rich(model3d_spec={'inputs': [{'kind': 'text', 'name': 'prompt'}]}))
    assert preflight() is None
    assert 'MODEL_3D' in visible() and 'CHARACTER_SHEET_3D' not in visible()


def test_hidden_when_the_image_service_is_not_image_gen(board):
    board(rich(image_key='flux_gen'))
    assert preflight() is None
    assert 'IMAGE_GEN' in visible() and 'CHARACTER_SHEET_3D' not in visible()


def test_prefers_the_default_image_model(board):
    board(rich(image_models=[image_model('wide', refs=8),
                             image_model('house', refs=2, is_default=True)]))
    assert preflight()[:2] == ('house', 2)


def test_prefers_gpt_image_sunburst_over_the_default(board):
    board(rich(image_models=[image_model('house', refs=2, is_default=True),
                             image_model('gpt-image-2.5-sunburst', refs=16)]))
    assert preflight()[:2] == ('gpt-image-2.5-sunburst', 16)


@pytest.mark.parametrize('sunburst', [
    image_model('gpt-image-2.5-sunburst', refs=16, enabled=False),
    image_model('gpt-image-2.5-sunburst', refs=0),
])
def test_unusable_sunburst_leaves_the_catalog_default(board, sunburst):
    board(rich(image_models=[image_model('house', refs=2, is_default=True), sunburst]))
    assert preflight()[:2] == ('house', 2)


def test_falls_back_to_the_model_taking_the_most_references(board):
    board(rich(image_models=[image_model('house', refs=0, is_default=True),
                             image_model('three', refs=3), image_model('five', refs=5),
                             image_model('off', refs=9, enabled=False)]))
    assert preflight()[:2] == ('five', 5)


def test_model_3d_prefers_the_default_model_with_an_image_input(board):
    board(rich(model3d_models=[{'slug': 'first'}, {'slug': 'chosen', 'is_default': True}]))
    assert preflight()[2:] == ('image_to_3d', 'chosen')
    board(rich(model3d_models=[
        {'slug': 'text_only', 'is_default': True, 'input_spec': {'inputs': []}},
        {'slug': 'image'},
    ]))
    assert preflight()[2:] == ('image_to_3d', 'image')


def test_auto_rig_is_optional(board):
    board(rich(rig=False))
    assert 'AUTO_RIG' not in visible()
    assert 'CHARACTER_SHEET_3D' in visible()


def test_template_available_follows_the_members(board, monkeypatch):
    board(rich())
    monkeypatch.setattr(node_templates, 'capability_available',
                        lambda key, **kwargs: key != 'model_gen')
    assert not node_templates.template_available('CHARACTER_SHEET_3D')
    monkeypatch.setattr(node_templates, 'capability_available',
                        lambda key, **kwargs: key != 'image_gen')
    assert not node_templates.template_available('CHARACTER_SHEET_3D')
    monkeypatch.setattr(node_templates, 'capability_available', lambda key, **kwargs: True)
    assert node_templates.template_available('CHARACTER_SHEET_3D')


def test_unavailable_workflow_cannot_mutate_the_board(board):
    board({'capabilities': []})
    with pytest.raises(ValueError, match='available generation model'):
        node_templates.create_template(None, 'CHARACTER_SHEET_3D', (0, 0))
