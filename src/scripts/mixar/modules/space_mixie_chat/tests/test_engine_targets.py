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
    # Packages keep Blender's axes with the transform baked into the vertices
    # (Unreal imports each object locally); a plain Unreal scene export does not.
    assert (kw["axis_up"], kw["axis_forward"], kw["bake_space_transform"]) == ("Z", "Y", True)
    from mixar.modules.space_mixie_chat.core.export_presets import PRESETS
    assert "bake_space_transform" not in PRESETS["unreal"]["fbx"]
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


def test_engine_packages_keep_each_objects_origin():
    src = open(export_package.__file__, encoding="utf-8").read()
    body = src[src.index("def export_package("):]
    assert "_copies(meshes, join, keep_origins=bool(engine))" in body
    copies = src[src.index("def _copies("):src.index("def _cleanup(")]
    assert "me.transform(Matrix.Translation(-origin))" in copies and "c.location = origin" in copies
    # Hulls stand in their copy's space either way.
    hull = open(et.__file__, encoding="utf-8").read()
    assert "obj.parent = copy" in hull and "obj.matrix_world = copy.matrix_world.copy()" in hull


# The real Tripo auto-rig v3.0 bone list (78 bones, uat4 rig job, 28 Oct).
TRIPO_V3 = (
    "BoneRoot Hip Pelvis L_Thigh L_Calf L_Foot L_ToeBase L_CalfTwist01 L_CalfTwist02 L_KneeShareBone "
    "L_ThighTwist01 L_ThighTwist02 R_Thigh R_Calf R_KneeShareBone R_Foot R_ToeBase R_CalfTwist01 "
    "R_CalfTwist02 R_ThighTwist01 R_ThighTwist02 Waist Spine01 Spine02 NeckTwist01 NeckTwist02 Head "
    "FacialBone R_Eye L_Eye L_Clavicle L_Upperarm L_Forearm L_ForearmTwist01 L_ForearmTwist02 "
    "L_ElbowShareBone L_Hand L_Pinky1 L_Pinky2 L_Pinky3 L_Ring1 L_Ring2 L_Ring3 L_Mid1 L_Mid2 L_Mid3 "
    "L_Index1 L_Index2 L_Index3 L_Thumb1 L_Thumb2 L_Thumb3 L_UpperarmTwist01 L_UpperarmTwist02 "
    "R_Clavicle R_Upperarm R_Forearm R_ElbowShareBone R_ForearmTwist01 R_ForearmTwist02 R_Hand R_Ring1 "
    "R_Ring2 R_Ring3 R_Mid1 R_Mid2 R_Mid3 R_Thumb1 R_Thumb2 R_Thumb3 R_Index1 R_Index2 R_Index3 R_Pinky1 "
    "R_Pinky2 R_Pinky3 R_UpperarmTwist01 R_UpperarmTwist02").split()


def test_a_tripo_rig_maps_onto_the_godot_humanoid_and_the_ue_mannequin():
    from mixar.modules.space_mixie_chat.core import engine_targets as et
    assert len(TRIPO_V3) == 78
    godot = et.skeleton_map("godot", "SK_Attacker", TRIPO_V3)
    assert godot["naming"] == "tripo" and godot["profile"] == "godot_humanoid"
    assert len(godot["bones"]) == 55  # the body, eyes and every finger joint
    assert godot["bones"]["Hips"] == "Hip" and godot["bones"]["LeftUpperArm"] == "L_Upperarm"
    assert godot["bones"]["LeftThumbMetacarpal"] == "L_Thumb1"
    assert godot["bones"]["RightLittleDistal"] == "R_Pinky3"
    ue = et.skeleton_map("unreal", "SK_Attacker", TRIPO_V3)
    assert ue["profile"] == "ue5_mannequin"
    assert ue["bones"]["pelvis"] == "Hip" and ue["bones"]["ball_l"] == "L_ToeBase"
    assert (ue["bones"]["neck_01"], ue["bones"]["neck_02"]) == ("NeckTwist01", "NeckTwist02")
    assert ue["bones"]["middle_02_r"] == "R_Mid2" and ue["bones"]["upperarm_twist_01_l"] == "L_UpperarmTwist01"
    assert set(ue["bones"].values()) <= set(TRIPO_V3)
    assert et.skeleton_map("uefn", "SK", TRIPO_V3)["profile"] == "ue5_mannequin"


def test_a_mixamo_rig_maps_with_either_prefix_and_an_unknown_rig_does_not():
    from mixar.modules.space_mixie_chat.core import engine_targets as et
    for prefix in ("mixamorig:", "mixamorig_"):
        names = [prefix + n for n in ("Hips", "Spine", "LeftArm", "LeftForeArm", "RightUpLeg", "LeftHandIndex1")]
        m = et.skeleton_map("godot", "Rig", names)
        assert m["naming"] == "mixamo"
        assert m["bones"]["LeftUpperArm"] == prefix + "LeftArm"
        assert m["bones"]["LeftIndexProximal"] == prefix + "LeftHandIndex1"
    assert et.skeleton_map("godot", "Rig", ["Bone", "Bone.001"]) is None
    # A custom rig still rides in the manifest, so the engine imports it skinned.
    assert et.skeleton_entry("unreal", "Robot_Rig", ["Root", "Torso", "Head"]) == {
        "armature": "Robot_Rig", "naming": "custom", "profile": "ue5_mannequin", "bones": {}}
    assert et.skeleton_entry("unreal", "SK", TRIPO_V3)["naming"] == "tripo"
    assert et.manifest_section("godot", [], [])  .get("skeletons") is None


def test_an_enemy_or_player_moves_by_code():
    assert et.default_tags({"role": "enemy"}) == {"role": "enemy", "body": "kinematic"}
    assert et.default_tags({"role": "player"})["body"] == "kinematic"
    assert et.default_tags({"role": "enemy", "body": "rigid"})["body"] == "rigid"
    assert et.default_tags({"role": "door"}) == {"role": "door"}


def test_material_report_names_what_a_game_look_lacks():
    report, issues = et.material_report([
        ("Stone", True, "sRGB", True, True),
        ("Flat", False, None, False, False),
        ("Door", True, "Non-Color", False, False),
    ], object_count=2)
    assert report["count"] == 3 and report["per_object"] == 1.5
    assert report["untextured"] == ["Flat"]
    assert report["no_normal_map"] == ["Door"] and report["flat_roughness"] == ["Door"]
    assert len(issues) == 1 and "Door" in issues[0] and "Non-Color" in issues[0]


def test_tagged_empties_become_manifest_markers():
    """Spawn points and bomb sites are empties: the file drops them, so the
    manifest lists them (uat4 2026-10-30: ten tagged spawn empties of a map
    never reached Unreal and the level made do with one marker a side)."""
    import math

    class _Matrix:
        def __init__(self, at, yaw):
            self.translation = at
            self._yaw = yaw

        def to_euler(self):
            return type("E", (), {"z": self._yaw})()

    def empty(name, tags, at=(0.0, 0.0, 0.0), yaw=0.0, kind="EMPTY", children=()):
        o = _Obj(name, **{f"mixar_{k}": v for k, v in tags.items()})
        o.type, o.matrix_world, o.children_recursive = kind, _Matrix(at, yaw), list(children)
        return o

    spawn = empty("Spawn_T_1", {"role": "spawn", "team": "t"}, (1.0, -24.0, 0.0), math.radians(90))
    site = empty("Site_A", {"role": "bombsite"}, (21.0, 16.0, 2.0))
    loose = empty("Group", {})
    bad = empty("Spawn_X", {"role": "spawn", "team": "blue"})
    wall = empty("Wall", {"role": "prop"}, kind="MESH")
    root = empty("Map", {}, children=[spawn, site, loose, bad, wall])
    names = {o.name for o in (root, spawn, site, loose, bad, wall)}
    found, issues = et.markers([root], names)
    assert [m["name"] for m in found] == ["Spawn_T_1", "Site_A", "Spawn_X"]
    assert found[0] == {"name": "Spawn_T_1", "role": "spawn", "team": "t", "position": [1.0, -24.0, 0.0],
                        "yaw_deg": 90.0}
    assert "team" not in found[2] and any("blue" in i for i in issues)
    assert et.manifest_section("unreal", [], [], markers_list=found)["markers"] == found
    assert "markers" not in et.manifest_section("unreal", [], [])
