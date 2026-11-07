# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Post-script mesh topology repair (bpy faked; the real validator is exercised
by tests/qa/topology_repair_e2e.py in a built Mixar)."""
import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

CORE = Path(__file__).parents[1] / "src/scripts/mixar/modules/space_mixie_chat/core"


class _Mesh:
    def __init__(self, name, ptr, sizes, *, invalid=False, editmode=False, library=None,
                 broken=False):
        self.name_full, self._ptr, self.invalid = name, ptr, invalid
        self.vertices, self.edges, self.loops, self.polygons = (range(n) for n in sizes)
        self.is_editmode, self.library, self.broken = editmode, library, broken
        self.validated = []

    def as_pointer(self):
        return self._ptr

    def validate(self, verbose=False, clean_customdata=True):
        if self.broken:
            raise RuntimeError("cannot validate")
        self.validated.append(clean_customdata)
        return self.invalid


@pytest.fixture
def topology(monkeypatch):
    fake_bpy = ModuleType("bpy")
    fake_bpy.data = SimpleNamespace(meshes=[])
    monkeypatch.setitem(sys.modules, "bpy", fake_bpy)
    pkg = ModuleType("_topology_tests")
    pkg.__path__ = [str(CORE)]
    monkeypatch.setitem(sys.modules, pkg.__name__, pkg)
    monkeypatch.delitem(sys.modules, "_topology_tests.sandbox_topology", raising=False)
    return importlib.import_module("_topology_tests.sandbox_topology"), fake_bpy


def test_only_created_or_resized_meshes_are_validated_and_custom_data_is_kept(topology):
    module, bpy = topology
    same = _Mesh("Same", 1, (8, 12, 24, 6))
    grown = _Mesh("Grown", 2, (8, 12, 24, 6), invalid=True)
    bpy.data.meshes = [same, grown]
    before = module.snapshot_mesh_sizes()
    grown.loops = range(48)                                   # script grew it
    new = _Mesh("New", 3, (3, 3, 3, 1))                       # script created it
    empty = _Mesh("Empty", 4, (0, 0, 0, 0))                   # bpy.data.meshes.new()
    bpy.data.meshes = [same, grown, new, empty]

    assert module.repair_changed_meshes(before) == ["Grown"]
    assert same.validated == [] and empty.validated == []
    assert grown.validated == [False] and new.validated == [False]


def test_edit_mode_linked_and_failing_meshes_are_skipped_without_blocking_others(topology):
    module, bpy = topology
    bpy.data.meshes = []
    before = module.snapshot_mesh_sizes()
    edit = _Mesh("Edit", 1, (4, 4, 4, 1), invalid=True, editmode=True)
    linked = _Mesh("Linked", 2, (4, 4, 4, 1), invalid=True, library=object())
    broken = _Mesh("Broken", 3, (4, 4, 4, 1), broken=True)
    bad = _Mesh("Bad", 4, (4, 4, 4, 1), invalid=True)
    bpy.data.meshes = [edit, linked, broken, bad]

    assert module.repair_changed_meshes(before) == ["Bad"]
    assert edit.validated == [] and linked.validated == []


def test_nothing_is_validated_when_the_script_never_ran(topology):
    module, bpy = topology
    mesh = _Mesh("New", 1, (3, 3, 3, 1), invalid=True)
    bpy.data.meshes = [mesh]
    assert module.repair_changed_meshes(None) == []
    assert mesh.validated == []
