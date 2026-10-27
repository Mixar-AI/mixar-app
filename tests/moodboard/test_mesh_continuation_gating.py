# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The mesh `+` menu offers a feature only when its card can run a service.

Node Templates and Shift+A gate each template with
``capability_available(cap, action_type=...)``, which keeps only the services
the card executes (``node_schema.services_for_action``). The `+` continuation
menu used to ask about the capability alone, so ``uv_unwrapping`` serving only
``hunyuan_uv`` still listed Smart UV, and the new card read "Model
unavailable". Mesh Segmentation had the same mismatch: its card runs
``hunyuan_part`` only, while the catalog serves ``tripo_segment``.
"""

from types import SimpleNamespace as NS

import pytest

from mixar.modules.moodboard.core import node_templates
from mixar.modules.moodboard.ui import moodboard_menu_actions as actions

ALL_MESH_FEATURES = ['PBR_GEN', 'RETOPOLOGY', 'MESH_SEGMENT', 'UV_UNWRAP', 'AUTO_RIG']


def _service(key):
    return {"key": key, "models": [{"slug": f"{key}_v1"}]}


@pytest.fixture
def catalog(monkeypatch):
    """A live catalog: {capability: [service keys]}; edit it per test."""
    from mixar.bootstrap import generation_catalog_cache as cache

    services = {
        "pbr_generation": ["tripo_texture"],
        "retopology": ["retopology"],
        "mesh_segmentation": ["hunyuan_part"],
        "uv_unwrapping": ["tripo_uv"],
        "animate": ["tripo_rig"],
    }
    monkeypatch.setattr(cache, "get_capability", lambda key: {"key": key})
    monkeypatch.setattr(cache, "get_services", lambda capability, surface=None: [
        _service(key) for key in services.get(capability, [])])
    monkeypatch.setattr(cache, "get_models", lambda key: [{"slug": f"{key}_v1"}])
    return services


def _offered(scene_source="mesh"):
    scene = NS(mixie_moodboard_action_nodes=[], mixie_moodboard_asset_nodes=[
        NS(node_id=scene_source, preview_object=None)], mixie_moodboard_links=[],
        mixie_moodboard_images=[])
    return [entry[0] for entry in actions.mesh_continuations_for(scene, scene_source)]


def _templates():
    return [template[0] for template in node_templates.available_templates()]


def test_every_runnable_mesh_feature_is_offered(catalog):
    assert _offered() == ALL_MESH_FEATURES


def test_smart_uv_is_hidden_when_uv_unwrapping_serves_only_hunyuan_uv(catalog):
    catalog["uv_unwrapping"] = ["hunyuan_uv"]
    assert 'UV_UNWRAP' not in _offered()
    assert 'UV_UNWRAP' not in _templates()
    catalog["uv_unwrapping"] = ["hunyuan_uv", "tripo_uv"]
    assert 'UV_UNWRAP' in _offered() and 'UV_UNWRAP' in _templates()


def test_mesh_segmentation_follows_the_same_rule(catalog):
    catalog["mesh_segmentation"] = ["tripo_segment"]
    assert 'MESH_SEGMENT' not in _offered()
    assert 'MESH_SEGMENT' not in _templates()


def test_the_plus_menu_and_templates_agree_for_every_mesh_feature(catalog):
    for capability, keys in (("uv_unwrapping", ["hunyuan_uv"]),
                             ("mesh_segmentation", ["tripo_segment"]),
                             ("retopology", []), ("animate", ["tripo_rig"])):
        catalog[capability] = keys
        offered, templates = set(_offered()), set(_templates())
        assert offered == templates & set(ALL_MESH_FEATURES), (capability, keys)
