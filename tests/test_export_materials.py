# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Both export lanes swap Mixar paint slots to their baked materials.

``export_scene`` (agent_export) always did; ``export_asset`` packages
(export_package) exported the node-group material, so a Mixar-painted mesh
shipped untextured even when its stack was baked (NB-1).
"""

import ast
import sys
import types
from pathlib import Path

import pytest

from mixar.modules.space_mixie_chat.core import export_materials

ROOT = Path(__file__).parents[1]
CORE = ROOT / "src/scripts/mixar/modules/space_mixie_chat/core"


class _Materials(list):
    """obj.data.materials stand-in (assignable slots)."""


class _Obj:
    def __init__(self, name, materials):
        self.name = name
        self.data = types.SimpleNamespace(materials=_Materials(materials))
        self.active_material_index = 0


class _Mat:
    def __init__(self, name, mixar=False):  # mixar: False | "baked" | "unbaked"
        self.name = name
        self.mixar = mixar
        self.users = 0


@pytest.fixture
def swap_env(monkeypatch):
    created, removed = [], []

    def create_export_material(obj, mp, tree):
        index = obj.active_material_index
        mat = _Mat(obj.data.materials[index].name + "_BakedExport")
        obj.data.materials[index] = mat
        created.append((obj.name, index, mat))
        return mat

    module = types.ModuleType("bake_and_assign")
    module.create_export_material = create_export_material
    monkeypatch.setitem(
        sys.modules, "mixar.modules.paint.core.asset_export.bake_and_assign", module)
    def stack(baked):
        channel = types.SimpleNamespace(baked="Baked_Color")
        nodes = {"Baked_Color": types.SimpleNamespace(image=object() if baked else None)}
        return types.SimpleNamespace(node_tree=types.SimpleNamespace(
            mp=types.SimpleNamespace(channels=[channel]), nodes=nodes))
    monkeypatch.setattr(export_materials, "active_mixar_nodes",
                        lambda m: [stack(m.mixar == "baked")] if getattr(m, "mixar", False) else [])
    fake_bpy = types.SimpleNamespace(
        data=types.SimpleNamespace(materials=types.SimpleNamespace(remove=removed.append)))
    monkeypatch.setattr(export_materials, "bpy", fake_bpy)
    return created, removed


def test_swaps_only_mixar_slots_then_restores_and_frees(swap_env):
    created, removed = swap_env
    painted, plain = _Mat("Painted", mixar="baked"), _Mat("Plain")
    obj = _Obj("Copy", [plain, painted])
    obj.active_material_index = 0
    with export_materials.temporary_export_materials([obj]):
        assert obj.data.materials[0] is plain
        assert obj.data.materials[1].name == "Painted_BakedExport"
        assert obj.active_material_index == 0  # restored after the swap
    assert list(obj.data.materials) == [plain, painted]
    assert [m.name for m in removed] == ["Painted_BakedExport"]


def test_restores_even_when_the_export_fails(swap_env):
    painted = _Mat("Painted", mixar="baked")
    obj = _Obj("Copy", [painted])
    with pytest.raises(RuntimeError):
        with export_materials.temporary_export_materials([obj]):
            raise RuntimeError("exporter failed")
    assert obj.data.materials[0] is painted


def test_both_lanes_share_the_one_swap():
    agent = (CORE / "agent_export.py").read_text(encoding="utf-8")
    assert "def _temporary_export_materials" not in agent
    assert "from .export_materials import temporary_export_materials" in agent
    # The STL preset wraps it in nullcontext(); the swap itself is the one helper.
    assert "_temporary_export_materials(meshes)" in agent


def test_package_swaps_the_copies_before_reading_their_materials():
    source = (CORE / "export_package.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.parse(source).body
              if isinstance(n, ast.FunctionDef) and n.name == "export_package")
    body = ast.get_source_segment(source, fn)
    copies = body.index("_copies(meshes, join")
    swap = body.index("swap.enter_context(temporary_export_materials(copies, keep_unbaked=bool(engine)))")
    bake = body.index("swap.enter_context(baked_procedural_materials(copies)) if engine else None")
    mats = body.index("images = _material_images(mats)")
    assert copies < swap < bake < mats, "materials/textures must be read after the swap and the bake"
    # Unwound before the copies are deleted, on success and on failure.
    final = body[body.index("    finally:\n        swap.close()"):]
    assert final.index("swap.close()") < final.index("_cleanup(col, renamed)")


def test_an_unbaked_stack_is_left_for_the_package_bake(swap_env):
    """cs-go iter 4: the swap turned unbaked layered materials into flat
    Principled copies, the package bake saw nothing procedural, and the map
    package wrote 0 images. Unbaked, the stack stays and gets baked."""
    created, removed = swap_env
    fresh = _Mat("Plaster", mixar="unbaked")
    obj = _Obj("Copy", [fresh])
    with export_materials.temporary_export_materials([obj], keep_unbaked=True):
        assert obj.data.materials[0] is fresh
    assert created == [] and removed == []


def test_an_ordinary_export_swaps_an_unbaked_stack_as_before(swap_env):
    """Only an engine package bakes, so only it keeps the stack for the bake."""
    created, _ = swap_env
    fresh = _Mat("Plaster", mixar="unbaked")
    obj = _Obj("Copy", [fresh])
    with export_materials.temporary_export_materials([obj]):
        assert obj.data.materials[0] is not fresh
    assert [(name, index) for name, index, _ in created] == [("Copy", 0)]
    assert obj.data.materials[0] is fresh


def test_only_an_engine_package_bakes_its_materials():
    """The bake (a Smart UV project and Cycles bakes on the main thread) ran
    on every export_asset; ordinary packages export as they did before it."""
    import inspect
    from mixar.modules.space_mixie_chat.core import export_package
    params = inspect.signature(export_package.export_package).parameters
    assert "bake_materials" not in params
    source = (CORE / "export_package.py").read_text(encoding="utf-8")
    assert "baked_procedural_materials(copies)) if engine else None" in source
    assert '**({"baked_materials": baked} if baked is not None else {})' in source
