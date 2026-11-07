# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Edit-mesh refresh after an agent script that used bmesh (bpy/bmesh faked)."""
import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

CORE = Path(__file__).parents[1] / "src/scripts/mixar/modules/space_mixie_chat/core"


@pytest.fixture
def editmesh(monkeypatch):
    updates = []
    fake_bmesh = ModuleType("bmesh")

    def update_edit_mesh(mesh, loop_triangles=True, destructive=True):
        if mesh.broken:
            raise RuntimeError("not in edit mode")
        updates.append((mesh.name_full, loop_triangles, destructive))
    fake_bmesh.update_edit_mesh = update_edit_mesh
    fake_bpy = ModuleType("bpy")
    fake_bpy.data = SimpleNamespace(objects=[])
    monkeypatch.setitem(sys.modules, "bmesh", fake_bmesh)
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    pkg = ModuleType("_editmesh_tests")
    pkg.__path__ = [str(CORE)]
    monkeypatch.setitem(sys.modules, pkg.__name__, pkg)
    monkeypatch.delitem(sys.modules, "_editmesh_tests.sandbox_editmesh", raising=False)
    module = importlib.import_module("_editmesh_tests.sandbox_editmesh")
    return module, fake_bpy, updates


def _mesh(name, *, editmode=True, broken=False):
    return SimpleNamespace(name_full=name, is_editmode=editmode, broken=broken)


def test_only_a_script_that_names_bmesh_triggers_the_refresh(editmesh):
    module, _, _ = editmesh
    assert module.may_edit_bmesh("import bmesh\nbm = bmesh.from_edit_mesh(me)")
    assert not module.may_edit_bmesh("bpy.ops.mesh.primitive_cube_add()")
    assert module.may_edit_bmesh(None)  # source unknown: refresh


def test_every_edit_mode_mesh_gets_its_loop_triangles_recomputed_once(editmesh):
    module, bpy, updates = editmesh
    shared = _mesh("Shared")
    bpy.data.objects = [
        SimpleNamespace(type="MESH", mode="EDIT", data=shared),
        SimpleNamespace(type="MESH", mode="EDIT", data=shared),          # linked duplicate
        SimpleNamespace(type="MESH", mode="OBJECT", data=_mesh("Idle", editmode=False)),
        SimpleNamespace(type="CURVE", mode="EDIT", data=_mesh("Curve")),
        SimpleNamespace(type="MESH", mode="EDIT", data=_mesh("Broken", broken=True)),
        SimpleNamespace(type="MESH", mode="EDIT", data=_mesh("Other")),
    ]
    assert module.refresh_edit_meshes() == 2
    assert updates == [("Shared", True, True), ("Other", True, True)]
