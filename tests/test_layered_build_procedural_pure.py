# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pure-Python unit tests for procedural_layer.py (no Blender runtime needed).

Uses importlib to load the module in isolation. Relative imports in the module
are satisfied by injecting MagicMock stubs for the parent packages into
sys.modules before exec_module is called.
"""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "src/scripts/mixar/modules/paint/layered_build/procedural_layer.py"


def _inject_parent_stubs():
    """Inject MagicMock parent packages so relative imports resolve without error."""
    # Package hierarchy that procedural_layer.py needs to satisfy its relative imports.
    # The actual implementations are replaced with MagicMocks — we only test the
    # pure sanitize_blend_type helper which has no real dependencies.
    pkg_names = [
        "paint",
        "paint.core",
        "paint.core.node",
        "paint.core.node.node_utils",
        "paint.core.io",
        "paint.core.io.connections",
        "paint.core.io.connections.layer_connections",
        "paint.core.io.arrangements",
        "paint.core.io.arrangements.layer_arrangements",
        "paint.procedural_materials",
        "paint.procedural_materials.material_registry",
        "paint.ui",
        "paint.ui.mask",
        "paint.ui.mask.mask_creation",
        "paint.layered_build",
        "paint.layered_build.download",
    ]
    for pkg in pkg_names:
        if pkg not in sys.modules:
            sys.modules[pkg] = MagicMock()

    # Ensure the relatively-imported symbols exist as attrs on their stub modules.
    sys.modules["paint.core.node.node_utils"].get_active_mpaint_node = MagicMock()
    sys.modules["paint.procedural_materials.material_registry"].get_registry = MagicMock()
    sys.modules["paint.procedural_materials.material_registry"].ProceduralMaterial = MagicMock()
    sys.modules["paint.layered_build.download"].load_image = MagicMock()
    sys.modules["paint.ui.mask.mask_creation"].add_new_mask = MagicMock()
    sys.modules["paint.core.io.connections.layer_connections"].reconnect_layer_nodes = MagicMock()
    sys.modules["paint.core.io.connections.layer_connections"].reconnect_mp_nodes = MagicMock()
    sys.modules["paint.core.io.arrangements.layer_arrangements"].rearrange_layer_nodes = MagicMock()
    sys.modules["paint.core.io.arrangements.layer_arrangements"].rearrange_mp_nodes = MagicMock()

    # Register the layered_build package itself so the relative import resolves
    pkg_mod = types.ModuleType("paint.layered_build")
    pkg_mod.__path__ = [str(P.parent)]
    pkg_mod.__package__ = "paint.layered_build"
    sys.modules["paint.layered_build"] = pkg_mod


_inject_parent_stubs()


def _load(name, path):
    spec = importlib.util.spec_from_file_location(
        name, path,
        submodule_search_locations=[],
    )
    spec.submodule_search_locations = None  # it's a module, not a package
    mod = importlib.util.module_from_spec(spec)
    # Set __package__ so relative imports resolve against our stubs
    mod.__package__ = "paint.layered_build"
    spec.loader.exec_module(mod)
    return mod


mod = _load("paint.layered_build.procedural_layer", P)


def test_sanitize_blend_type_uppercase():
    assert mod.sanitize_blend_type("MULTIPLY") == "MULTIPLY"


def test_sanitize_blend_type_lowercase():
    assert mod.sanitize_blend_type("multiply") == "MULTIPLY"


def test_sanitize_blend_type_nonsense():
    assert mod.sanitize_blend_type("nonsense") == "MIX"


def test_sanitize_blend_type_none():
    assert mod.sanitize_blend_type(None) == "MIX"


def test_sanitize_blend_type_all_valid():
    """Every identifier in _VALID_BLENDS must round-trip cleanly."""
    for ident in mod._VALID_BLENDS:
        assert mod.sanitize_blend_type(ident) == ident
        assert mod.sanitize_blend_type(ident.lower()) == ident


def test_sanitize_blend_type_exclusion():
    """EXCLUSION is in BLEND_TYPE_ITEMS (statics.py) — must be accepted."""
    assert mod.sanitize_blend_type("EXCLUSION") == "EXCLUSION"
    assert mod.sanitize_blend_type("exclusion") == "EXCLUSION"


def test_valid_bake_types_match_backend_vocabulary():
    """BAKED-mask bake types must match the backend planner's BakeType literal
    (AO/CAVITY/DUST/POINTINESS) and the paint module's bake_type_items identifiers."""
    assert mod._VALID_BAKE_TYPES == {"AO", "CAVITY", "POINTINESS", "DUST"}
    assert set(mod._BAKE_CONFIG) == mod._VALID_BAKE_TYPES | {"BEVEL_MASK"}


def _recording_entity_setter(monkeypatch):
    calls = []
    common_entity = types.ModuleType("paint.utils.common_entity")
    common_entity.set_entity_prop_value = lambda entity, prop, value: calls.append((entity, prop, value))
    monkeypatch.setitem(sys.modules, "paint.utils", types.ModuleType("paint.utils"))
    monkeypatch.setitem(sys.modules, "paint.utils.common_entity", common_entity)
    return calls


def test_uniform_scale_is_written_where_the_shader_reads_it(monkeypatch):
    """Enabling uniform scale creates the node input at 1.0; a plain attribute
    write after that never reached it, so every layer rendered at scale 1.0."""
    calls = _recording_entity_setter(monkeypatch)
    layer = types.SimpleNamespace(enable_uniform_scale=False)
    mod.set_uniform_scale(layer, 3)
    assert layer.enable_uniform_scale is True
    assert calls == [(layer, "uniform_scale_value", 3.0)]
    assert not hasattr(layer, "uniform_scale_value")


def test_mask_repeats_follow_the_mapping_direction(monkeypatch):
    """Masks get TEXTURE Mapping nodes (inverse transform): 4 repeats = scale 0.25."""
    calls = _recording_entity_setter(monkeypatch)
    vector_type = {"value": "TEXTURE"}
    mappings = types.ModuleType("paint.core.layer.mappings")
    mappings.get_entity_mapping = lambda entity: types.SimpleNamespace(vector_type=vector_type["value"])
    monkeypatch.setitem(sys.modules, "paint.core.layer", types.ModuleType("paint.core.layer"))
    monkeypatch.setitem(sys.modules, "paint.core.layer.mappings", mappings)
    mask = types.SimpleNamespace(enable_uniform_scale=False)
    mod.set_mask_repeats(mask, 4.0)
    vector_type["value"] = "POINT"
    mod.set_mask_repeats(mask, 4.0)
    assert calls == [(mask, "uniform_scale_value", 0.25), (mask, "uniform_scale_value", 4.0)]
