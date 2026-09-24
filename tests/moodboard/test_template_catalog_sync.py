# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Live catalog changes must reach every template entry point immediately."""

import pytest

from mixar.bootstrap import generation_catalog_cache as catalog
from mixar.modules.moodboard.core.node_templates import available_templates, create_template


def capability(key, service_key, **service_overrides):
    service = {'key': service_key, 'surface': 'moodboard',
               'models': [{'slug': 'ready'}]}
    service.update(service_overrides)
    return {'key': key, 'services': [service]}


def visible():
    return {item[0] for item in available_templates()}


def test_refresh_removal_and_logout_are_not_cached(monkeypatch):
    monkeypatch.setattr(catalog, '_catalog', {'capabilities': []})
    assert visible() == {'MESH_REFERENCE'}
    catalog._catalog = {'capabilities': [capability('image_gen', 'image_gen')]}
    assert visible() == {'IMAGE_GEN', 'MESH_REFERENCE'}
    catalog._catalog = {'capabilities': [capability('video_gen', 'video_gen')]}
    assert visible() == {'VIDEO_GEN', 'MESH_REFERENCE'}
    with pytest.raises(ValueError, match='available generation model'):
        create_template(None, 'IMAGE_GEN', (0, 0))
    catalog._catalog = None
    assert visible() == {'MESH_REFERENCE'}


def test_progressive_strip_fits_only_currently_available_templates(monkeypatch):
    from mixar.modules.moodboard.core.canvas_template_fit import (
        canvas_template_strip_items, templates_that_fit,
    )

    monkeypatch.setattr(catalog, '_catalog', {'capabilities': [
        capability('video_gen', 'video_gen'),
    ]})
    items = canvas_template_strip_items(available_templates())
    assert [item[0] for item in items] == ['MESH_REFERENCE', 'VIDEO_GEN']
    assert templates_that_fit(
        240, items, widths={item[0]: 100 for item in items}, more_width=32, gap=4,
    ) == list(items)
    catalog._catalog = None
    assert [item[0] for item in canvas_template_strip_items(available_templates())] == [
        'MESH_REFERENCE',
    ]


@pytest.mark.parametrize('overrides', [
    {'surface': 'agent'}, {'models': []}, {'enabled': False},
    {'models': [{'slug': 'disabled', 'enabled': False}]},
    {'models': [{'slug': 'disabled', 'is_enabled': False}]},
    {'models': [{}]},
])
def test_unavailable_services_never_offer_templates(monkeypatch, overrides):
    monkeypatch.setattr(catalog, '_catalog', {
        'capabilities': [capability('image_gen', 'image_gen', **overrides)]})
    assert visible() == {'MESH_REFERENCE'}


def test_disabled_capability_and_unsupported_service_fail_closed(monkeypatch):
    image = capability('image_gen', 'image_gen')
    image['enabled'] = False
    monkeypatch.setattr(catalog, '_catalog', {'capabilities': [
        image, capability('model_gen', 'text_to_3d'),
        capability('mesh_segmentation', 'sam3'),
    ]})
    assert visible() == {'MESH_REFERENCE'}
    catalog._catalog['capabilities'] = [
        capability('model_gen', 'image_to_3d'),
        capability('mesh_segmentation', 'hunyuan_part'),
    ]
    assert visible() == {'MODEL_3D', 'MESH_SEGMENT', 'MESH_REFERENCE'}


def test_one_enabled_model_is_sufficient(monkeypatch):
    monkeypatch.setattr(catalog, '_catalog', {'capabilities': [
        capability('image_gen', 'image_gen', models=[
            {'slug': 'disabled', 'enabled': False}, {'slug': 'ready'},
        ]),
    ]})
    assert visible() == {'IMAGE_GEN', 'MESH_REFERENCE'}


@pytest.mark.parametrize(('capability_key', 'service_key', 'action'), [
    ('video_upscale', 'video_upscale', 'VIDEO_UPSCALE'),
    ('world_labs', 'world_labs', 'WORLD_LABS'),
])
def test_secondary_generation_templates_follow_live_catalog(
        monkeypatch, capability_key, service_key, action):
    monkeypatch.setattr(catalog, '_catalog', {'capabilities': [
        capability(capability_key, service_key),
    ]})
    assert visible() == {action, 'MESH_REFERENCE'}
