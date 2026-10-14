# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The glTF import guard: a file with several scenes is confined to its default
scene and to what that scene reaches, and a scene the importer still creates
is removed (its objects kept).

Background: client 4.1.1 exported job uploads with every open tab as a glTF
scene; Tripo echoed them back (and textured a mesh from another tab that was
in no scene at all); the importer turned each into an empty ``<tab>.001``
scene tab (prod, 2026-09-28).
"""

import importlib.util
import json
import struct
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[2] / "src" / "scripts" / "mixar"
_MODULE = _ROOT / "modules" / "common" / "gltf_import.py"


@pytest.fixture
def guard(monkeypatch):
    """Load modules/common/gltf_import.py under a fake bpy and stubbed logging."""
    for name, path in (("mixar", _ROOT), ("mixar.modules", _ROOT / "modules"),
                       ("mixar.modules.common", _ROOT / "modules" / "common")):
        package = ModuleType(name)
        package.__path__ = [str(path)]
        monkeypatch.setitem(sys.modules, name, package)
    stubs = {
        "mixar.config": {},
        "mixar.config.logging_config": {"get_logger": lambda _n: MagicMock()},
        "mixar.modules.common.scenes_log": {"slog": MagicMock()},
    }
    for name, attrs in stubs.items():
        module = ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
    bpy = MagicMock(name="bpy")
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    spec = importlib.util.spec_from_file_location("mixar.modules.common.gltf_import", _MODULE)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return SimpleNamespace(m=module, bpy=bpy, slog=sys.modules["mixar.modules.common.scenes_log"].slog)


def _doc(names, default=None):
    """One root node with its own mesh per scene."""
    nodes = [{"name": f"node{i}", "mesh": i} for i in range(len(names))]
    meshes = [{"name": f"mesh{i}"} for i in range(len(names))]
    scenes = [{"name": n, "nodes": [i]} for i, n in enumerate(names)]
    doc = {"asset": {"version": "2.0"}, "nodes": nodes, "meshes": meshes, "scenes": scenes}
    if default is not None:
        doc["scene"] = default
    return doc


def _glb(doc, binary=b"\x01\x02\x03\x04\x05"):
    payload = json.dumps(doc).encode()
    payload += b" " * (-len(payload) % 4)
    binary += b"\x00" * (-len(binary) % 4)
    body = struct.pack("<II", len(payload), 0x4E4F534A) + payload
    body += struct.pack("<II", len(binary), 0x004E4942) + binary
    return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body


def _read(glb: bytes):
    magic, version, length = struct.unpack_from("<III", glb, 0)
    assert magic == 0x46546C67 and length == len(glb)
    jl, jt = struct.unpack_from("<II", glb, 12)
    doc = json.loads(glb[20:20 + jl])
    bl, bt = struct.unpack_from("<II", glb, 20 + jl)
    return doc, glb[28 + jl:28 + jl + bl]


# --- strip_gltf_json -------------------------------------------------------

def test_keeps_the_default_scene_and_prunes_the_rest(guard):
    doc = _doc(["Character Sheet Of A MMA", "Image Of Chair", "Scene", "Scene 4"], default=1)
    stripped = guard.m.strip_gltf_json(doc)
    assert stripped.scenes == ["Character Sheet Of A MMA", "Scene", "Scene 4"]
    assert stripped.nodes == ["node0", "node2", "node3"]
    assert doc["scenes"] == [{"name": "Image Of Chair", "nodes": [0]}] and doc["scene"] == 0
    assert doc["nodes"] == [{"name": "node1", "mesh": 0}]
    assert [m["name"] for m in doc["meshes"]] == ["mesh1"]


def test_orphan_nodes_are_pruned_even_with_one_scene(guard):
    doc = _doc(["Scene"])
    doc["nodes"].append({"name": "foreign_cube", "mesh": 1})        # in no scene at all
    doc["meshes"].append({"name": "cube_mesh"})
    stripped = guard.m.strip_gltf_json(doc)
    assert stripped.scenes == [] and stripped.nodes == ["foreign_cube"]
    assert [n["name"] for n in doc["nodes"]] == ["node0"]
    assert [m["name"] for m in doc["meshes"]] == ["mesh0"]


def test_single_scene_and_missing_scene_index_are_left_alone(guard):
    one = _doc(["Scene"])
    assert not guard.m.strip_gltf_json(one) and one["scenes"][0]["name"] == "Scene"
    assert guard.m.strip_gltf_json(_doc(["A", "B"])).scenes == ["B"]               # no "scene" key
    assert guard.m.strip_gltf_json(_doc(["A", "B"], default=7)).scenes == ["B"]    # out of range
    assert not guard.m.strip_gltf_json({"asset": {}})


def test_children_skins_and_animations_are_remapped(guard):
    doc = {
        "asset": {"version": "2.0"}, "scene": 0,
        "scenes": [{"name": "Kept", "nodes": [0]}, {"name": "Other", "nodes": [2]}],
        "nodes": [
            {"name": "root", "children": [1, 4]},
            {"name": "body", "mesh": 1, "skin": 0},
            {"name": "foreign", "mesh": 0, "children": [3]},
            {"name": "foreign_joint"},
            {"name": "joint"},
        ],
        "meshes": [{"name": "foreign_mesh"}, {"name": "body_mesh"}],
        "skins": [{"joints": [4, 3], "skeleton": 0}, {"joints": [3]}],
        "animations": [
            {"name": "walk", "channels": [
                {"sampler": 0, "target": {"node": 4, "path": "rotation"}},
                {"sampler": 1, "target": {"node": 3, "path": "rotation"}},
            ], "samplers": [{}, {}]},
            {"name": "foreign_only", "channels": [{"sampler": 0, "target": {"node": 2, "path": "translation"}}],
             "samplers": [{}]},
        ],
    }
    stripped = guard.m.strip_gltf_json(doc)
    assert stripped.scenes == ["Other"] and stripped.nodes == ["foreign", "foreign_joint"]
    assert doc["nodes"] == [{"name": "root", "children": [1, 2]}, {"name": "body", "mesh": 0, "skin": 0},
                            {"name": "joint"}]
    assert doc["meshes"] == [{"name": "body_mesh"}]
    assert doc["skins"] == [{"joints": [2], "skeleton": 0}]
    assert [a["name"] for a in doc["animations"]] == ["walk"]
    assert doc["animations"][0]["channels"] == [{"sampler": 0, "target": {"node": 2, "path": "rotation"}}]


# --- keep_default_scene ----------------------------------------------------

def test_glb_is_rewritten_with_the_binary_chunk_intact(guard, tmp_path):
    path = tmp_path / "model.glb"
    path.write_bytes(_glb(_doc(["4 Cubes", "Scene", "Scene 4"], default=1), binary=b"BINARYDATA!"))
    stripped = guard.m.keep_default_scene(str(path))
    assert stripped.scenes == ["4 Cubes", "Scene 4"] and stripped.nodes == ["node0", "node2"]
    doc, binary = _read(path.read_bytes())
    assert [s["name"] for s in doc["scenes"]] == ["Scene"] and doc["scene"] == 0
    assert doc["nodes"] == [{"name": "node1", "mesh": 0}]
    assert binary.rstrip(b"\x00") == b"BINARYDATA!"
    assert not guard.m.keep_default_scene(str(path))   # idempotent


def test_gltf_json_is_rewritten_too(guard, tmp_path):
    path = tmp_path / "model.gltf"
    path.write_text(json.dumps(_doc(["A", "B"], default=0)))
    assert guard.m.keep_default_scene(str(path)).scenes == ["B"]
    assert [s["name"] for s in json.loads(path.read_text())["scenes"]] == ["A"]


def test_unparseable_file_is_left_unchanged(guard, tmp_path):
    path = tmp_path / "model.glb"
    path.write_bytes(b"glTF" + b"\x00" * 3)
    assert not guard.m.keep_default_scene(str(path))
    assert path.read_bytes() == b"glTF" + b"\x00" * 3
    assert not guard.m.keep_default_scene(str(tmp_path / "missing.glb"))


# --- import_gltf -----------------------------------------------------------

class _Objects(dict):
    """bpy_prop_collection shape: iterates OBJECTS, `name in` checks keys."""
    def __iter__(self):
        return iter(list(self.values()))


class _Scene:
    def __init__(self, name, objects=()):
        self.name = name
        self.objects = _Objects((o.name, o) for o in objects)
        self.collection = SimpleNamespace(objects=SimpleNamespace(link=lambda o: self.objects.__setitem__(o.name, o)))

    def as_pointer(self):
        return id(self)


def test_scenes_the_importer_creates_are_removed_and_their_objects_kept(guard, tmp_path):
    path = tmp_path / "result.glb"
    path.write_bytes(_glb(_doc(["Scene", "Scene 4"], default=0)))
    active = _Scene("Scene")
    stray = SimpleNamespace(name="Cube")

    class Scenes(list):                      # bpy.data.scenes: iterable with .remove(scene, do_unlink)
        def remove(self, scene, do_unlink=True):
            list.remove(self, scene)

    scenes = Scenes([active])
    bpy = guard.bpy
    bpy.context.scene = active
    bpy.data.scenes = scenes

    def fake_import(filepath, **_kw):
        # The importer still spawns a scene (as it would for a file the sanitiser
        # could not parse) and parks an object in it.
        scenes.append(_Scene("Scene 4.001", objects=[stray]))
        return {"FINISHED"}
    bpy.ops.import_scene.gltf.side_effect = fake_import

    result = guard.m.import_gltf(str(path), guess_original_bind_pose=False)

    assert result == {"FINISHED"}
    bpy.ops.import_scene.gltf.assert_called_once_with(filepath=str(path), guess_original_bind_pose=False)
    assert [s.name for s in scenes] == ["Scene"]           # the phantom is gone
    assert "Cube" in active.objects                         # its object moved to the active scene
    guard.slog.assert_called_once()
    event, scene = guard.slog.call_args.args[:2]
    assert event == "import.scenes_stripped" and scene is active
    assert guard.slog.call_args.kwargs["in_file"] == ["Scene 4"]
    assert guard.slog.call_args.kwargs["orphan_nodes"] == ["node1"]
    assert guard.slog.call_args.kwargs["created"] == ["Scene 4.001"]


def test_clean_import_logs_nothing(guard, tmp_path):
    path = tmp_path / "result.glb"
    path.write_bytes(_glb(_doc(["Scene"])))
    active = _Scene("Scene")
    guard.bpy.context.scene = active
    guard.bpy.data.scenes = [active]
    guard.bpy.ops.import_scene.gltf.return_value = {"FINISHED"}
    assert guard.m.import_gltf(str(path)) == {"FINISHED"}
    guard.slog.assert_not_called()
