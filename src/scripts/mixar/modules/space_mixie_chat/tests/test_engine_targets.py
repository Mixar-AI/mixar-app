# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""``engine_targets``: collision naming, game-semantics tags and engine
readiness for ``export_asset(engine=…)`` packages, pinned outside Blender."""

import os
import sys
from unittest.mock import MagicMock

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), *([".."] * 4)))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

for _dep in ("keyring", "websocket", "requests", "jwt", "sentry_sdk"):
    sys.modules.setdefault(_dep, MagicMock(name=_dep))

from mixar.modules.space_mixie_chat.core import engine_targets as et  # noqa: E402
from mixar.modules.space_mixie_chat.core import export_package, export_verify  # noqa: E402


class _Obj(dict):
    def __init__(self, name, **props):
        super().__init__(props)
        self.name = name


def test_engines_and_their_formats():
    assert et.ENGINES == ("godot", "unreal", "uefn")
    assert et.normalise_engine(" Godot ") == "godot"
    assert et.normalise_engine("unity") is None
    assert et.ENGINE_FORMATS["unreal"] == ("fbx",) == et.ENGINE_FORMATS["uefn"]
    assert "glb" in et.ENGINE_FORMATS["godot"]


def test_tags_are_validated_never_guessed():
    door = _Obj("Door", mixar_role="Door", mixar_body="kinematic", mixar_pivot="hinge_z",
                mixar_nav="sometimes")
    tags, issues = et.read_tags(door)
    assert tags == {"role": "door", "body": "kinematic", "pivot": "hinge_z"}
    assert len(issues) == 1 and "mixar_nav 'sometimes'" in issues[0] and issues[0].startswith("Door:")
    # The package renames originals while it exports; issues carry the real name.
    _, issues = et.read_tags(_Obj("Door.mixar_export_src", mixar_body="wobbly"), "Door")
    assert issues[0].startswith("Door:")
    assert et.read_tags(_Obj("Plain")) == ({}, [])


def test_collision_shape_defaults():
    assert et.collision_shape({}, skinned=False) == "convex"
    assert et.collision_shape({}, skinned=True) == "none"
    assert et.collision_shape({"body": "none"}, skinned=False) == "none"
    assert et.collision_shape({"collision": "box"}, skinned=True) == "box"


def test_collision_names_follow_each_importer():
    assert et.collision_names("godot", "Crate", "box") == ["Crate_col-convcolonly"]
    assert et.collision_names("godot", "Crate", "convex") == ["Crate_col-convcolonly"]
    assert et.collision_names("godot", "Floor", "mesh") == ["Floor_col-colonly"]
    assert et.collision_names("unreal", "Crate", "convex") == ["UCX_Crate_00"]
    assert et.collision_names("uefn", "Crate", "box") == ["UCX_Crate_00"]
    # An Unreal trimesh is the render mesh itself (complex as simple).
    assert et.collision_names("unreal", "Floor", "mesh") == []
    assert et.collision_entry("unreal", "Floor", "mesh", [])["complex_as_simple"] is True
    assert "complex_as_simple" not in et.collision_entry("godot", "Floor", "mesh", ["Floor_col-colonly"])
    for engine in et.ENGINES:
        assert et.collision_names(engine, "Hero", "none") == []


def test_readiness_reports_what_degrades_on_import():
    textures = [("textures/wood.png", (1000, 1000)), ("textures/stone.png", (1024, 512))]
    meshes = [("Crate", True, True), ("Sign", False, True), ("Blob", False, False)]
    objects = [{"name": "Lift", "body": "kinematic", "collision": {"shape": "none", "nodes": []}},
               {"name": "Crate", "collision": {"shape": "convex", "nodes": ["UCX_Crate_00"]}}]
    unreal = et.readiness_issues("unreal", textures=textures, meshes=meshes, objects=objects)
    assert any("wood.png is 1000x1000" in i for i in unreal)
    assert not any("stone.png" in i for i in unreal)
    assert any(i.startswith("Sign has image textures but no UV map") for i in unreal)
    assert not any("Blob" in i for i in unreal)
    assert any(i.startswith("Lift: mixar_body 'kinematic' has no collision") for i in unreal)
    # Godot imports non-power-of-two textures fine.
    godot = et.readiness_issues("godot", textures=textures, meshes=meshes, objects=objects)
    assert not any("1000x1000" in i for i in godot)


def test_manifest_section_counts_collision_nodes():
    objects = [{"name": "A", "collision": {"shape": "convex", "nodes": ["UCX_A_00"]}},
               {"name": "B", "collision": {"shape": "none", "nodes": []}}]
    section = et.manifest_section("unreal", objects, ["x"])
    assert section["target"] == "unreal" and section["version"] == et.MANIFEST_VERSION
    assert section["collision_nodes"] == 1 and section["issues"] == ["x"]
    assert section["axes"] == "blender_z_up"


def test_engine_packages_keep_extras_and_unreal_fbx_takes_the_unreal_preset():
    kw, _, _ = export_package.exporter_kwargs("glb", [], "godot")
    assert kw["export_extras"] is True
    kw, _, _ = export_package.exporter_kwargs("glb", [])
    assert "export_extras" not in kw
    kw, _, _ = export_package.exporter_kwargs("fbx", [], "uefn")
    assert kw["apply_scale_options"] == "FBX_SCALE_NONE" and kw["primary_bone_axis"] == "Y"
    kw, _, _ = export_package.exporter_kwargs("fbx", [])
    assert kw["apply_scale_options"] == "FBX_SCALE_ALL"


def test_every_package_export_carries_the_engine():
    src = open(export_package.__file__, encoding="utf-8").read()
    body = src[src.index("def export_package("):]
    calls = [line for line in body.splitlines() if "_export(fmt," in line]
    assert len(calls) == 2 and all(line.rstrip().endswith("engine)") for line in calls)
    assert "exported = list(copies) + hulls + armatures" in body
    assert '"extra_meshes": len(hulls)' in body


def test_package_refuses_a_wrong_engine_or_format_before_touching_the_scene(monkeypatch):
    import pytest

    scene = MagicMock()
    monkeypatch.setattr(export_package.bpy, "context", MagicMock(scene=scene))
    with pytest.raises(ValueError, match="engine must be one of"):
        export_package.export_package(["Crate"], fmt="glb", engine="unity")
    with pytest.raises(ValueError, match="unreal package is fbx"):
        export_package.export_package(["Crate"], fmt="glb", engine="unreal")
    scene.objects.__getitem__.assert_not_called()


def test_verification_counts_collision_meshes():
    def issues(meshes, **expected):
        result = {"issues": [], "meshes": meshes}
        export_verify._compare(result, expected, "glb")
        return result["issues"]
    assert issues(3, mesh_count=2, extra_meshes=1) == []
    assert issues(2, mesh_count=2, extra_meshes=1)
    assert issues(2, mesh_count=3, joined=True, extra_meshes=1) == []
    assert issues(2, mesh_count=2) == []
