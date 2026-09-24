# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure-Python tests for the agent's slot-targeted texturing helpers.

The Blender-side paths (fresh datablock per call, exact slots, real-scale UV)
were validated against the real paint module in Blender; these pin the pure
pieces and the source contracts the backend templates rely on:

- ``normalize_slot_targets`` / ``manifest_tile_size`` (``layered_slots``);
- ``channel_index`` (``layer_authoring``) — names, aliases and indices;
- ``AGENT_TOOLS_FEATURES`` — the capability flag the backend reads;
- no module writes ``uniform_scale_value`` with a plain attribute assignment:
  enabling uniform scale creates the node input at 1.0, and a plain write
  after that never reached the shader (every layer rendered at scale 1.0).
"""

import ast
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAINT = ROOT / "src/scripts/mixar/modules/paint"
AGENT_TOOLS = PAINT / "core/agent_tools"
PKG = "_agent_tools_under_test"


def _load(monkeypatch, name):
    """Load one ``agent_tools`` module against stubbed dependencies."""
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [str(AGENT_TOOLS)]
    monkeypatch.setitem(sys.modules, PKG, pkg)
    monkeypatch.setitem(sys.modules, f"{PKG}._common", MagicMock())
    log_mod = types.ModuleType("mixar.config.logging_config")
    log_mod.get_logger = lambda *a, **k: MagicMock()
    entity_mod = types.ModuleType("mixar.modules.paint.utils.common_entity")
    entity_mod.set_entity_prop_value = MagicMock()
    for stub in ("mixar", "mixar.config", "mixar.modules", "mixar.modules.paint",
                 "mixar.modules.paint.utils"):
        monkeypatch.setitem(sys.modules, stub, types.ModuleType(stub))
    monkeypatch.setitem(sys.modules, "mixar.config.logging_config", log_mod)
    monkeypatch.setitem(sys.modules, "mixar.modules.paint.utils.common_entity", entity_mod)
    spec = importlib.util.spec_from_file_location(f"{PKG}.{name}", AGENT_TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def slots(monkeypatch):
    return _load(monkeypatch, "layered_slots")


@pytest.fixture
def authoring(monkeypatch):
    return _load(monkeypatch, "layer_authoring")


# --- slot targets ------------------------------------------------------------


def test_slot_targets_merge_duplicates_and_sort(slots):
    slot_map, errors = slots.normalize_slot_targets([
        {"object_name": " Cabinet ", "slot_indices": [2, 0]},
        {"object_name": "Cabinet", "slot_indices": [0, 1]},
        {"object_name": "Floor", "slot_indices": [0]},
    ])
    assert slot_map == {"Cabinet": [0, 1, 2], "Floor": [0]}
    assert errors == []


@pytest.mark.parametrize("item", [
    {"object_name": "", "slot_indices": [0]},
    {"object_name": "A", "slot_indices": []},
    {"object_name": "A"},
    "A",
])
def test_malformed_targets_are_errors_not_guesses(slots, item):
    slot_map, errors = slots.normalize_slot_targets([item])
    assert slot_map == {} and len(errors) == 1


def test_invalid_indices_are_reported_and_dropped(slots):
    slot_map, errors = slots.normalize_slot_targets(
        [{"object_name": "A", "slot_indices": [True, -1, "2", 1.0, 3]}])
    assert slot_map == {"A": [3]}
    assert len(errors) == 4 and all(e["object"] == "A" for e in errors)


# --- physical tile size -----------------------------------------------------


@pytest.mark.parametrize("manifest, expected", [
    ({"scale": {"tile_size_m": 0.6}}, 0.6),
    ({"scale": {"tile_size_m": "1.5"}}, 1.5),
    ({"scale": {"tile_size_m": 0.0001}}, 0.01),
    ({"scale": {"tile_size_m": 5000}}, 100.0),
    ({"scale": {"tile_size_m": 0}}, None),
    ({"scale": {"tile_size_m": -2}}, None),
    ({"scale": {"tile_size_m": float("nan")}}, None),
    ({"scale": {"tile_size_m": "wide"}}, None),
    ({"scale": {"base_tiling": 4.0}}, None),
    ({}, None),
])
def test_manifest_tile_size(slots, manifest, expected):
    assert slots.manifest_tile_size(manifest) == expected


def test_real_scale_uv_name_is_shared(slots):
    assert slots.REAL_SCALE_UV_NAME == "MixarRealScaleUV"
    assert slots.PRESEED_KEY == "mixar_agent_preseed"


# --- channels ---------------------------------------------------------------


def _mp(*names):
    return types.SimpleNamespace(channels=[types.SimpleNamespace(name=n) for n in names])


@pytest.mark.parametrize("channel, expected", [
    ("Roughness", 2), ("roughness ", 2), ("Base Color", 0), ("albedo", 0),
    ("AO", 3), (1, 1),
])
def test_channel_index_accepts_names_aliases_and_indices(authoring, channel, expected):
    mp = _mp("Color", "Metallic", "Roughness", "Ambient Occlusion")
    assert authoring.channel_index(mp, channel) == expected


@pytest.mark.parametrize("channel", ["Sheen", 7, -1])
def test_channel_index_rejects_unknown_channels(authoring, channel):
    with pytest.raises(ValueError):
        authoring.channel_index(_mp("Color", "Roughness"), channel)


def test_live_mask_types_cover_the_wear_vocabulary(authoring):
    for mask_type in ("EDGE_DETECT", "AO", "HEMI", "NOISE", "VORONOI"):
        assert mask_type in authoring.LIVE_MASK_TYPES


# --- source contracts -------------------------------------------------------


def test_agent_tools_advertise_their_features():
    tree = ast.parse((AGENT_TOOLS / "__init__.py").read_text(encoding="utf-8"))
    features = next(
        ast.literal_eval(node.value) for node in tree.body
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", "") == "AGENT_TOOLS_FEATURES" for t in node.targets)
    )
    assert features == {"slot_targets": 1, "real_scale": 1, "layer_authoring": 1, "map_prefetch": 1}
    exported = (AGENT_TOOLS / "__init__.py").read_text(encoding="utf-8")
    for name in ("apply_layered_material_manifest", "inspect_material_slots", "focus_material_slot",
                 "add_fill_layer", "add_layer_mask", "set_layer_channel", "add_library_layer",
                 "prefetch_layered_maps"):
        assert name in exported, name


def test_manifest_apply_accepts_exact_slot_targets():
    tree = ast.parse((AGENT_TOOLS / "layered_manifest.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "apply_layered_material_manifest")
    params = [a.arg for a in fn.args.args]
    assert params[:2] == ["manifest", "object_names"]
    assert "material_slot_targets" in params


def test_uniform_scale_is_never_written_with_a_plain_setattr():
    offenders = []
    for folder in (PAINT / "layered_build", AGENT_TOOLS):
        for path in folder.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                targets = node.targets if isinstance(node, ast.Assign) else (
                    [node.target] if isinstance(node, (ast.AugAssign, ast.AnnAssign)) else [])
                if any(isinstance(t, ast.Attribute) and t.attr == "uniform_scale_value" for t in targets):
                    offenders.append(f"{path.name}:{node.lineno}")
                if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setattr"
                        and len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
                        and node.args[1].value == "uniform_scale_value"):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []
