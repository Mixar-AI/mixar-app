# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for operation_history.core.scene_diff — snapshot + diff (pure)."""

import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_scripts_dir = os.path.abspath(os.path.join(_test_dir, "..", "..", ".."))  # -> src/scripts
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from types import SimpleNamespace

from mixar.modules.operation_history.core import scene_diff as SD


def _mat(name, node_count):
    return SimpleNamespace(name=name, node_tree=SimpleNamespace(nodes=list(range(node_count))))


def _mesh(vertices=0, edges=0, faces=0):
    return SimpleNamespace(vertices=list(range(vertices)), edges=list(range(edges)),
                           polygons=list(range(faces)))


def _mod(name, mod_type, **props):
    values = {"name": name, "type": mod_type}
    values.update(props)
    return SimpleNamespace(**values)


def _obj(name, loc=(0, 0, 0), materials=(), mesh=None, modifiers=()):
    slots = [SimpleNamespace(material=m) for m in materials]
    return SimpleNamespace(name=name, type="MESH", location=list(loc),
                           rotation_euler=[0, 0, 0], scale=[1, 1, 1],
                           material_slots=slots, data=mesh, modifiers=list(modifiers))


def _scene(objs):
    return SimpleNamespace(objects=objs)


def test_diff_detects_created_modified_deleted():
    before = SD.snapshot_scene(_scene([_obj("A"), _obj("B", mesh=_mesh(4, 4, 1))]))
    after = SD.snapshot_scene(_scene([_obj("A", loc=(1, 0, 0)), _obj("C", mesh=_mesh(8, 12, 6))]))
    delta = SD.diff_snapshots(before, after)
    assert delta["created"] == ["C"]
    assert delta["deleted"] == ["B"]
    assert delta["modified"] == ["A"]


def test_empty_diff():
    s = SD.snapshot_scene(_scene([_obj("A")]))
    d = SD.diff_snapshots(s, s)
    assert d["created"] == [] and d["modified"] == [] and d["deleted"] == []
    assert d["materials_created"] == [] and d["materials_modified"] == [] and d["materials_deleted"] == []


def test_snapshot_captures_material_node_counts():
    s = SD.snapshot_scene(_scene([_obj("A", materials=[_mat("Mat", 2)])]))
    assert s["materials"] == {"Mat": 2}


def test_diff_detects_material_node_change():
    # A node was added to "Mat" (2 -> 3 nodes): a material edit with no object change.
    before = {"objects": {}, "materials": {"Mat": 2}}
    after = {"objects": {}, "materials": {"Mat": 3}}
    d = SD.diff_snapshots(before, after)
    assert d["materials_modified"] == ["Mat"]
    assert d["created"] == [] and d["modified"] == [] and d["deleted"] == []


def test_diff_detects_mesh_topology_change():
    before = SD.snapshot_scene(_scene([_obj("Cube", mesh=_mesh(8, 12, 6))]))
    after = SD.snapshot_scene(_scene([_obj("Cube", mesh=_mesh(12, 16, 7))]))
    d = SD.diff_snapshots(before, after)
    assert d["modified"] == ["Cube"]
    change = d["object_changes"]["Cube"]
    assert "mesh_topology" in change["fields"]
    assert change["mesh_delta"] == {"vertices": 4, "edges": 4, "faces": 1}


def test_diff_detects_object_rename():
    before = SD.snapshot_scene(_scene([_obj("Cube")]))
    after = SD.snapshot_scene(_scene([_obj("HeroCube")]))
    d = SD.diff_snapshots(before, after)
    assert d["created"] == []
    assert d["deleted"] == []
    assert d["modified"] == ["HeroCube"]
    assert d["renamed"] == [{"from": "Cube", "to": "HeroCube"}]
    assert d["object_changes"]["HeroCube"]["previous_name"] == "Cube"
    assert "rename" in d["object_changes"]["HeroCube"]["fields"]


def test_diff_detects_modifier_add_remove_and_parameter_change():
    before = SD.snapshot_scene(_scene([
        _obj("Cube", modifiers=[_mod("Bevel", "BEVEL", width=0.1), _mod("Mirror", "MIRROR")]),
    ]))
    after = SD.snapshot_scene(_scene([
        _obj("Cube", modifiers=[_mod("Bevel", "BEVEL", width=0.25), _mod("Subsurf", "SUBSURF", levels=2)]),
    ]))
    d = SD.diff_snapshots(before, after)
    change = d["object_changes"]["Cube"]
    assert "modifiers" in change["fields"]
    assert change["modifiers_added"] == ["Subsurf"]
    assert change["modifiers_removed"] == ["Mirror"]
    assert change["modifiers_modified"] == ["Bevel"]


def test_snapshot_uses_bmesh_counts_for_edit_mode(monkeypatch):
    bm = SimpleNamespace(verts=list(range(12)), edges=list(range(16)), faces=list(range(7)))
    monkeypatch.setitem(sys.modules, "bmesh",
                        SimpleNamespace(from_edit_mesh=lambda _data: bm))
    obj = _obj("Cube", mesh=_mesh(8, 12, 6))
    obj.mode = "EDIT"
    s = SD.snapshot_scene(_scene([obj]))
    assert s["objects"]["Cube"]["mesh"] == {"vertices": 12, "edges": 16, "faces": 7}
