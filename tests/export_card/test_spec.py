# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Export card's settings → the export lane's spec and pinned exporter
kwargs, and the engine presets loaded back into the settings."""

from types import SimpleNamespace

import pytest

from mixar.modules.export_card import constants as C
from mixar.modules.export_card.core import spec, targets
from mixar.modules.space_mixie_chat.core.export_presets import preset_kwargs


def card(**overrides):
    values = dict(
        target=C.GLTF, engine='web', scope='SCENE', animation='ALL', gltf_file='GLB',
        usd_file='USDZ', cameras_lights=False, texture_format='AUTO', draco=False,
        apply_modifiers=True, y_up=True, fbx_embed=True, fbx_scale='FBX_SCALE_NONE',
        leaf_bones=False, smoothing='FACE', obj_copy_textures=True, stl_units='MM',
        stl_scale=1.0, stl_ascii=False, renderer='EEVEE', quality='GOOD', width=1920,
        height=1080, camera='Camera', render_format='PNG', transparent=False,
        frame_start=1, frame_end=48, fps=24)
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("target, extra, fmt", [
    (C.GLTF, {}, "glb"), (C.GLTF, {"gltf_file": 'GLTF'}, "gltf"), (C.FBX, {}, "fbx"),
    (C.USD, {}, "usdz"), (C.USD, {"usd_file": 'USDC'}, "usdc"),
    (C.OBJ, {}, "obj"), (C.STL, {}, "stl"),
])
def test_each_3d_target_names_its_lane_format(target, extra, fmt):
    p = card(target=target, **extra)
    assert spec.model_format(p) == fmt
    assert targets.extension(target, p.gltf_file, p.usd_file) == "." + fmt


def test_lane_knows_every_extension_the_card_writes():
    from mixar.modules.space_mixie_chat.core.agent_export import EXTENSIONS
    for target in C.MODEL_TARGETS:
        for gltf_file in ('GLB', 'GLTF'):
            for usd_file in ('USDZ', 'USDC'):
                assert targets.model_format(target, gltf_file, usd_file) in EXTENSIONS


def test_spec_carries_scope_animation_and_no_session_ids():
    """No session / request ids: the lane resolves targets afresh from the
    live scene or selection every time (never a stale remembered set)."""
    built = spec.model_spec(card(scope='SELECTED', animation='NONE', engine='unity'), "chair")
    assert built["target_scope"] == "selected"
    assert built["animations"] == []
    assert built["use_case"] == "unity"
    assert built["suggested_filename"] == "chair"
    assert "session_id" not in built and "request_id" not in built
    assert spec.model_spec(card(), "x")["animations"] is None


@pytest.mark.parametrize("units, scale, expected", [('MM', 1.0, 1000.0), ('CM', 2.0, 200.0),
                                                   ('M', 0.5, 0.5)])
def test_stl_units_become_the_exporters_scale(units, scale, expected):
    built = spec.model_spec(card(target=C.STL, stl_units=units, stl_scale=scale, stl_ascii=True),
                            "part")
    assert built["stl"] == {"scale": expected, "ascii": True}
    assert built["use_case"] == "other"


@pytest.mark.parametrize("target, extra", [
    (C.GLTF, {}), (C.FBX, {}), (C.USD, {}), (C.OBJ, {}),
])
@pytest.mark.parametrize("engine", ['web', 'unreal', 'unity', 'godot', 'ar', 'other'])
def test_synced_settings_reproduce_the_preset(target, extra, engine):
    """After an engine pick the pinned overrides equal the preset's own
    values: picking an engine and exporting writes exactly that preset."""
    p = card(target=target, engine=engine, **extra)
    spec.sync_preset(p)
    preset = preset_kwargs(engine, spec.model_format(p))
    for key, value in spec.overrides(p).items():
        if key in preset:
            assert preset[key] == value, key


def test_user_changes_after_the_preset_are_what_gets_pinned():
    p = card(target=C.GLTF, engine='web')
    spec.sync_preset(p)
    assert p.cameras_lights is True          # the three.js preset carries them
    p.cameras_lights, p.draco, p.texture_format = False, True, 'WEBP'
    pinned = spec.overrides(p)
    assert pinned["export_cameras"] is False and pinned["export_lights"] is False
    assert pinned["export_draco_mesh_compression_enable"] is True
    assert pinned["export_image_format"] == 'WEBP'


def test_usd_z_up_turns_orientation_off():
    assert spec.overrides(card(target=C.USD, y_up=False))["convert_orientation"] is False
    assert spec.overrides(card(target=C.USD, y_up=True))["export_global_up_selection"] == "Y"


def test_stl_pins_nothing_but_the_lanes_own_scale():
    assert spec.overrides(card(target=C.STL)) == {}


@pytest.mark.parametrize("renderer, quality, samples", [('EEVEE', 'DRAFT', 16),
                                                        ('CYCLES', 'FINAL', 512)])
def test_render_options(renderer, quality, samples):
    image = spec.render_options(card(target=C.IMAGE, renderer=renderer, quality=quality,
                                     render_format='JPEG', transparent=True))
    assert image["samples"] == samples
    assert image["engine"] == renderer.lower()
    assert image["image_format"] == 'JPEG' and image["transparent"] is True
    assert "frame_start" not in image
    video = spec.render_options(card(target=C.VIDEO, camera='NONE'))
    assert video["camera"] == ""
    assert (video["frame_start"], video["frame_end"], video["fps"]) == (1, 48, 24)
    assert "image_format" not in video
