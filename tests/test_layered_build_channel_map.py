# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # repo root (tests/ is one level down)
MANIFEST_PY = ROOT / "src/scripts/mixar/modules/paint/layered_build/manifest.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


manifest = _load("lb_manifest", MANIFEST_PY)
map_to_channel_binding = manifest.map_to_channel_binding
validate_manifest = manifest.validate_manifest
ManifestError = manifest.ManifestError


def test_basecolor_binds_to_color_srgb_regular_slot():
    b = map_to_channel_binding("basecolor")
    assert b.channel_name == "Color"
    assert b.non_color is False
    assert b.override_slot == "source"
    assert b.normal_map_type is None


def test_normal_binds_to_normal_channel_source1_normalmap():
    b = map_to_channel_binding("normal")
    assert b.channel_name == "Normal"
    assert b.non_color is True
    assert b.override_slot == "source_1"
    assert b.normal_map_type == "NORMAL_MAP"


def test_height_binds_to_normal_channel_regular_slot_bump():
    b = map_to_channel_binding("height")
    assert b.channel_name == "Normal"
    assert b.override_slot == "source"
    assert b.normal_map_type == "BUMP_MAP"


def test_roughness_metallic_noncolor_value_channels():
    assert map_to_channel_binding("roughness").channel_name == "Roughness"
    assert map_to_channel_binding("metallic").channel_name == "Metallic"
    assert map_to_channel_binding("roughness").non_color is True


def test_validate_manifest_rejects_non_pbr_index0():
    bad = {"layers": [{"index": 0, "type": "PROCEDURAL"}]}
    try:
        validate_manifest(bad)
        assert False, "expected ManifestError"
    except ManifestError:
        pass
