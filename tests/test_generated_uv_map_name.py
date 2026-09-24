# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A generated mesh's UV map is usable in the Texturing tab whatever the engine.

glTF stores no UV layer names, so every GLB engine lands as Blender's
synthesised ``UV Map``. Tripo Quad (P2, ``quad: true``) forces FBX output,
and FBX DOES carry layer names — its mesh arrived with ``tripo____``, while
the paint system resolved a new layer's UV from Blender's default new-layer
name (a temp mesh), never from the mesh in front of it. The paint layer was
bound to a UV map the mesh did not have.

Two contracts pinned here:

A. ``rename_generated_model`` (the ONE post-import step every Model Gen
   path runs) canonicalises the generated mesh's UV layers to ``UV Map``
   and repoints material nodes that named the old layer — generation
   imports only, never a user's own mesh.
B. ``get_default_uv_name`` reads the mesh's ACTIVE layer, then index 0,
   and only mints Blender's default name when there is no mesh UV to read.
"""

import ast
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# The paint package imports ``bpy_extras``, which the root conftest's minimal
# stub set does not cover — the fuller mock does (same as the queue tests).
from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.job_queue.core import uv_layer_names as uvn  # noqa: E402


# --------------------------------------------------------------------------- #
# Fakes — a UV layer collection that de-duplicates names like Blender does.
# --------------------------------------------------------------------------- #

class _FakeUV:
    def __init__(self, coll, name):
        self._coll = coll
        self._name = name

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        self._name = self._coll._unique(value, self)


class _FakeUVLayers:
    """List-like with ``.active`` / ``.get`` and Blender's ``.001`` suffixing."""

    def __init__(self, names, active_index=0):
        self._items = []
        for n in names:
            self._items.append(_FakeUV(self, n))
        self.active = self._items[active_index] if self._items and active_index is not None else None

    def _unique(self, name, owner):
        taken = {uv._name for uv in self._items if uv is not owner}
        if name not in taken:
            return name
        i = 1
        while f"{name}.{i:03d}" in taken:
            i += 1
        return f"{name}.{i:03d}"

    def __len__(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, i):
        return self._items[i]

    def get(self, name):
        return next((uv for uv in self._items if uv.name == name), None)

    def names(self):
        return [uv.name for uv in self._items]


class _FakeNode:
    def __init__(self, bl_idname, uv_map=""):
        self.bl_idname = bl_idname
        self.uv_map = uv_map


def _material(*nodes):
    return types.SimpleNamespace(node_tree=types.SimpleNamespace(nodes=list(nodes)))


def _mesh_obj(uv_names, materials=(), type_="MESH"):
    data = types.SimpleNamespace(
        uv_layers=_FakeUVLayers(uv_names), materials=list(materials))
    return types.SimpleNamespace(type=type_, data=data, name="gen")


# --------------------------------------------------------------------------- #
# A. The normaliser
# --------------------------------------------------------------------------- #

def test_fbx_vendor_layer_name_becomes_canonical():
    obj = _mesh_obj(["tripo____"])
    renames = uvn.normalize_object_uv_layer_names(obj)
    assert renames == [("tripo____", "UV Map")]
    assert obj.data.uv_layers.names() == ["UV Map"]


def test_glb_import_is_already_canonical_and_untouched():
    obj = _mesh_obj(["UV Map"])
    assert uvn.normalize_object_uv_layer_names(obj) == []
    assert obj.data.uv_layers.names() == ["UV Map"]


def test_second_layer_takes_blenders_suffix_not_a_clash():
    obj = _mesh_obj(["tripo____", "tripo_lightmap"])
    renames = uvn.normalize_object_uv_layer_names(obj)
    assert renames == [("tripo____", "UV Map"), ("tripo_lightmap", "UV Map.001")]


def test_material_nodes_naming_the_old_layer_are_repointed():
    uv_node = _FakeNode("ShaderNodeUVMap", "tripo____")
    normal_node = _FakeNode("ShaderNodeNormalMap", "tripo____")
    other_layer_node = _FakeNode("ShaderNodeUVMap", "somebody_else")
    tex_node = _FakeNode("ShaderNodeTexImage")  # no uv_map semantics
    obj = _mesh_obj(
        ["tripo____"],
        materials=[_material(uv_node, normal_node, other_layer_node, tex_node), None],
    )

    uvn.normalize_object_uv_layer_names(obj)

    assert uv_node.uv_map == "UV Map"
    assert normal_node.uv_map == "UV Map"
    assert other_layer_node.uv_map == "somebody_else"


def test_non_mesh_and_uvless_objects_are_no_ops():
    assert uvn.normalize_object_uv_layer_names(None) == []
    assert uvn.normalize_object_uv_layer_names(_mesh_obj([], type_="EMPTY")) == []
    assert uvn.normalize_object_uv_layer_names(_mesh_obj([])) == []


def test_repoint_with_nothing_renamed_touches_nothing():
    node = _FakeNode("ShaderNodeUVMap", "UV Map")
    assert uvn.repoint_uv_map_nodes([_material(node)], []) == 0
    assert node.uv_map == "UV Map"


# --------------------------------------------------------------------------- #
# A. Wiring: every Model Gen import runs it, and only generation imports do.
# --------------------------------------------------------------------------- #

MODEL_IO = SCRIPTS / "mixar/modules/common/job_queue/core/model_io.py"
IMAGE_TO_3D_UTILS = SCRIPTS / "mixar/modules/moodboard/core/image_to_3d_utils.py"
UV_UTILS = SCRIPTS / "mixar/modules/paint/core/element/uv_utils.py"


def _function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _calls(func):
    out = []
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            f = node.func
            out.append(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
    return out


def test_rename_generated_model_normalises_both_provider_shapes():
    tree = ast.parse(MODEL_IO.read_text())
    calls = _calls(_function(tree, "rename_generated_model"))
    # Trellis (Empty-parented) branch AND the single-mesh Hunyuan/Tripo branch.
    assert calls.count("_normalize_generated_uv_names") == 2


def test_user_mesh_paths_never_rename_uv_layers():
    """Re-texture and retopology hooks act on the user's own geometry."""
    tree = ast.parse(MODEL_IO.read_text())
    for name in ("rename_imported_object", "post_import_rename_and_setup"):
        assert "_normalize_generated_uv_names" not in _calls(_function(tree, name))
        assert "normalize_object_uv_layer_names" not in _calls(_function(tree, name))


def test_legacy_image_to_3d_importers_normalise_too():
    tree = ast.parse(IMAGE_TO_3D_UTILS.read_text())
    for name in ("download_and_import_glb", "download_and_import_model"):
        assert "_select_and_normalize_imported" in _calls(_function(tree, name))
    helper = _function(tree, "_select_and_normalize_imported")
    assert "normalize_object_uv_layer_names" in _calls(helper)


# --------------------------------------------------------------------------- #
# B. The Texturing tab's default UV comes from the mesh, not a literal.
# --------------------------------------------------------------------------- #

@pytest.fixture
def uv_utils(monkeypatch):
    from mixar.modules.paint.core.element import uv_utils as mod

    minted = []

    class _TempMeshes:
        def new(self, name):
            layers = _FakeUVLayers([])
            layers.new = lambda: (minted.append("UVMap"), _FakeUV(layers, "UVMap"))[1]
            return types.SimpleNamespace(uv_layers=layers)

    monkeypatch.setattr(mod, "get_bpy_data", lambda: types.SimpleNamespace(meshes=_TempMeshes()))
    monkeypatch.setattr(mod, "remove_datablock", lambda coll, block: None)
    monkeypatch.setattr(mod, "get_active_object", lambda: None)
    mod._minted = minted
    return mod


def test_active_layer_wins_whatever_it_is_called(uv_utils):
    obj = _mesh_obj(["tripo____"])
    assert uv_utils.get_default_uv_name(obj) == "tripo____"
    assert uv_utils._minted == []


def test_bare_call_reads_the_active_object(uv_utils, monkeypatch):
    """add_new_layer / add_new_mask call it with no object at all."""
    obj = _mesh_obj(["tripo____"])
    monkeypatch.setattr(uv_utils, "get_active_object", lambda: obj)
    assert uv_utils.get_default_uv_name() == "tripo____"


def test_no_active_layer_falls_back_to_index_zero(uv_utils):
    obj = _mesh_obj(["first", "second"])
    obj.data.uv_layers.active = None
    assert uv_utils.get_default_uv_name(obj) == "first"


def test_temp_uv_active_uses_the_paint_layers_map_then_index_zero(uv_utils):
    temp = uv_utils.TEMP_UV
    obj = _mesh_obj(["real_uv", temp])
    obj.data.uv_layers.active = obj.data.uv_layers[1]

    mp = types.SimpleNamespace(
        layers=[types.SimpleNamespace(uv_name="real_uv")], active_layer_index=0)
    assert uv_utils.get_default_uv_name(obj, mp) == "real_uv"

    stale = types.SimpleNamespace(
        layers=[types.SimpleNamespace(uv_name="gone")], active_layer_index=0)
    assert uv_utils.get_default_uv_name(obj, stale) == "real_uv"
    assert uv_utils.get_default_uv_name(obj) == "real_uv"


def test_blenders_default_name_only_when_no_mesh_uv_exists(uv_utils):
    assert uv_utils.get_default_uv_name(_mesh_obj([])) == "UVMap"
    assert uv_utils.get_default_uv_name(None) == "UVMap"
    assert uv_utils.get_default_uv_name(_mesh_obj(["x"], type_="EMPTY")) == "UVMap"
    assert uv_utils._minted == ["UVMap"] * 3


def test_uv_utils_carries_no_literal_default_uv_name():
    src = UV_UTILS.read_text()
    assert '"UV Map"' not in src and "'UV Map'" not in src
    assert '"UVMap"' not in src and "'UVMap'" not in src
