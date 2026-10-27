# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Headless proof that an engine package keeps a rigged character skinned,
against the REAL Blender 5.2 glTF exporter.

Run inside the built app, no backend and no credits::

    <Mixar.app>/Contents/MacOS/Mixar -b --python tests/qa/skinned_export_blender_smoke.py

It builds the shape an Auto Rig + Animate pair leaves in a scene (an armature
sized to real height by an object scale, a mesh parented to it with an
Armature modifier and vertex groups, ``walk`` / ``run`` as muted NLA tracks)
plus a stray bone action nobody asked for, then runs
``export_package(engine="godot", animations=["walk", "run"])`` and checks:
the mesh primitives carry JOINTS_0 / WEIGHTS_0 and the mesh node names the
skin, the file holds exactly the two clips, verification passes with one
skinned mesh, the package is real height, and the user's objects are left
as they were. The Oct 26 CS:GO run exported the soldier three times with
the skeleton and clips but no weights; Godot bound no skin.

The ``src/`` modules are loaded over the bundle's (possibly stale) copies
by file, so this proves the working tree, not the last build. Prints one
``__RESULT__`` JSON line.
"""

import importlib.util
import json
import os
import shutil
import struct
import sys
import traceback

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "src", "scripts")
CORE = "mixar.modules.space_mixie_chat.core"
SRC_MODULES = tuple(f"{CORE}.{m}" for m in (
    "export_verification_status", "export_gltf_bounds", "export_verify", "export_clips",
    "export_materials", "export_bake_cache", "export_bake", "engine_targets", "export_package",
))
SCALE = 1.8


def _load_src(dotted: str):
    path = os.path.join(SRC, *dotted.split(".")) + ".py"
    spec = importlib.util.spec_from_file_location(dotted, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = module
    spec.loader.exec_module(module)
    return module


def _glb(path):
    with open(path, "rb") as handle:
        data = handle.read()
    size = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + size])


def _clip(rig, name, offset):
    action = bpy.data.actions.new(name)
    rig.animation_data.action = action
    slot = action.slots.new(rig.id_type, rig.name)
    rig.animation_data.action_slot = slot
    bone = rig.pose.bones["Thigh"]
    for frame, angle in ((1, 0.0), (12, offset), (24, 0.0)):
        bone.rotation_mode = "XYZ"
        bone.rotation_euler = (angle, 0.0, 0.0)
        bone.keyframe_insert("rotation_euler", frame=frame)
    rig.animation_data.action = None
    return action, slot


def main() -> dict:
    sys.path.insert(0, SRC)
    for dotted in SRC_MODULES:
        _load_src(dotted)
    package = sys.modules[f"{CORE}.export_package"]

    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.ops.object.armature_add(enter_editmode=True)
    rig = bpy.context.object
    rig.name = "Rig"
    hip = rig.data.edit_bones[0]
    hip.name, hip.head, hip.tail = "Hip", (0, 0, 0.5), (0, 0, 0.6)
    thigh = rig.data.edit_bones.new("Thigh")
    thigh.head, thigh.tail, thigh.parent = (0, 0, 0.5), (0, 0, 0.0), hip
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.mesh.primitive_cube_add(size=0.2, location=(0, 0, 0.5))
    body = bpy.context.object
    body.name = "Body"
    bpy.ops.transform.resize(value=(1, 1, 5))
    bpy.ops.object.transform_apply(scale=True)
    body.parent = rig
    mod = body.modifiers.new("Armature", "ARMATURE")
    mod.object = rig
    top = [v.index for v in body.data.vertices if v.co.z > 0]
    low = [v.index for v in body.data.vertices if v.co.z <= 0]
    body.vertex_groups.new(name="Hip").add(top, 1.0, "REPLACE")
    body.vertex_groups.new(name="Thigh").add(low, 1.0, "REPLACE")
    rig.animation_data_create()
    for name, offset in (("walk", 0.6), ("run", 1.1)):
        action, slot = _clip(rig, name, offset)
        track = rig.animation_data.nla_tracks.new()
        track.name = name
        strip = track.strips.new(name, 1, action)
        strip.action_slot = slot
        track.mute = True
    stray, _ = _clip(rig, "soldier_motion_reference_walk", 0.3)
    stray.use_fake_user = True
    rig.scale = (SCALE, SCALE, SCALE)
    bpy.context.view_layer.update()

    res = package.export_package(["Body", "Rig"], fmt="glb", filename="skinned_smoke",
                                 engine="godot", animations=["walk", "run"])
    root = package.destination("mixar_exports", "skinned_smoke", create=False)
    doc = _glb(os.path.join(root, "skinned_smoke.glb"))
    shutil.rmtree(root, ignore_errors=True)
    attrs = sorted({a for m in doc["meshes"] for p in m["primitives"] for a in p["attributes"]})
    body_node = next(n for n in doc["nodes"] if n.get("name") == "Body")
    verification = res["verification"]
    checks = {
        "joint_weights": {"JOINTS_0", "WEIGHTS_0"} <= set(attrs),
        "skin_bound": body_node.get("skin") is not None,
        "clips_exact": sorted(a["name"] for a in doc.get("animations", [])) == ["run", "walk"],
        "reported_clips": sorted(res["animations"]["clips"]) == ["run", "walk"],
        "verified": bool(verification.get("passed")) and verification.get("skinned_meshes") == 1,
        "real_height": abs(res["dimensions_m"][2] - SCALE) < 0.02,
        "source_untouched": (body.parent is rig and [m.type for m in body.modifiers] == ["ARMATURE"]
                             and body.name == "Body" and rig.animation_data.action is None
                             and sorted(o.name for o in bpy.data.objects) == ["Body", "Rig"]),
    }
    return {"ok": all(checks.values()), "checks": checks, "attrs": attrs,
            "animations": [a["name"] for a in doc.get("animations", [])],
            "dimensions_m": res["dimensions_m"], "issues": verification.get("issues")}


if __name__ == "__main__":
    try:
        out = main()
    except Exception:
        out = {"ok": False, "error": traceback.format_exc()}
    print("__RESULT__ " + json.dumps(out))
    sys.stdout.flush()
