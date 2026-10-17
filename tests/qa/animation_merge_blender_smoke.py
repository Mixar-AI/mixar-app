# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Headless proof of the retarget merge against the REAL Blender 5.2 API.

Run inside the built app, no backend and no credits::

    <Mixar.app>/Contents/MacOS/Mixar -b --python tests/qa/animation_merge_blender_smoke.py

It builds a stamped "rig" (armature + skinned cube), authors two clips on a
COPY of that armature, exports the copy alone as a GLB (the shape a
``tripo_retarget`` result has: skin + animations, no mesh), imports it with
``ANIMATE_IMPORT_OPTIONS`` exactly like the queue does, runs the merge hook,
and checks: the clips sit on the rig as locked, muted tracks named after
them with their slots assigned, the newest is the active action and its
slot animates the bones, the frame range follows it, the import is gone and
the hook reports the character. Prints one ``__RESULT__`` JSON line.

The ``src/`` modules are loaded over the bundle's (possibly stale) copies
by file, so this proves the working tree, not the last build.
"""

import importlib.util
import json
import os
import sys
import tempfile
import traceback

import bpy

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "src", "scripts")
SRC_MODULES = (
    "mixar.modules.hunyuan.constants",
    "mixar.modules.hunyuan.core.animate_presets",
    "mixar.modules.hunyuan.core.animation_merge",
    "mixar.modules.hunyuan.core.animate_enqueue",
)


def _load_src(dotted: str):
    path = os.path.join(SRC, *dotted.split(".")) + ".py"
    spec = importlib.util.spec_from_file_location(dotted, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[dotted] = module
    spec.loader.exec_module(module)
    return module


def _keyframe_clip(armature, name, frames, offsets):
    action = bpy.data.actions.new(name)
    armature.animation_data.action = action
    slot = action.slots.new(armature.id_type, armature.name)
    armature.animation_data.action_slot = slot
    for frame, offset in zip(frames, offsets):
        for bone in armature.pose.bones:
            bone.location = (0.0, offset, 0.0)
            bone.keyframe_insert("location", frame=frame)
    return action, slot


def _stash(armature, action, slot):
    track = armature.animation_data.nla_tracks.new()
    track.name = action.name
    strip = track.strips.new(action.name, int(action.frame_range[0]), action)
    strip.action_slot = slot
    track.lock = track.mute = True


def main() -> dict:
    sys.path.insert(0, SRC)
    for dotted in SRC_MODULES:
        _load_src(dotted)
    from mixar.modules.hunyuan.constants import (
        ANIMATE_IMPORT_OPTIONS, ANIMATE_RIG_JOB_PROP, ANIMATE_RIG_SKELETON_PROP,
    )
    from mixar.modules.hunyuan.core.animation_merge import merge_hook
    from mixar.modules.common.gltf_import import import_gltf

    bpy.ops.wm.read_homefile(use_empty=True)
    scene = bpy.context.scene

    # --- the rig an Auto Rig job imported: armature + skinned mesh, stamped ---
    bpy.ops.object.armature_add(enter_editmode=True)
    rig = bpy.context.object
    rig.name = "Rig"
    rig.data.edit_bones[0].name = "Hip"
    thigh = rig.data.edit_bones.new("L_Thigh")
    thigh.head, thigh.tail, thigh.parent = (0, 0, 1), (0, 0, 2), rig.data.edit_bones[0]
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.mesh.primitive_cube_add()
    body = bpy.context.object
    body.name = "Body"
    body.parent = rig
    modifier = body.modifiers.new("Armature", 'ARMATURE')
    modifier.object = rig
    group = body.vertex_groups.new(name="Hip")
    group.add(list(range(len(body.data.vertices))), 1.0, 'REPLACE')
    for obj in (rig, body):
        obj[ANIMATE_RIG_JOB_PROP] = "rig-job-1"
        obj[ANIMATE_RIG_SKELETON_PROP] = "biped"

    # A clip the user already had, active and never stashed.
    rig.animation_data_create()
    mine, mine_slot = _keyframe_clip(rig, "my_pose", [1, 10], [0.0, 0.5])

    # --- the retarget result: the same skeleton with two clips, no mesh ---
    clip_rig = rig.copy()
    clip_rig.data = rig.data.copy()
    clip_rig.name = "ClipRig"
    clip_rig.animation_data_clear()
    scene.collection.objects.link(clip_rig)
    clip_rig.animation_data_create()
    walk, walk_slot = _keyframe_clip(clip_rig, "walk", [1, 24], [0.0, 1.0])
    _stash(clip_rig, walk, walk_slot)
    idle, idle_slot = _keyframe_clip(clip_rig, "idle", [1, 60], [0.0, -1.0])
    _stash(clip_rig, idle, idle_slot)
    clip_rig.animation_data.action = None

    path = os.path.join(tempfile.mkdtemp(), "clips.glb")
    bpy.ops.object.select_all(action='DESELECT')
    clip_rig.select_set(True)
    bpy.context.view_layer.objects.active = clip_rig
    bpy.ops.export_scene.gltf(
        filepath=path, use_selection=True, use_active_scene=True,
        export_animations=True, export_animation_mode='NLA_TRACKS', export_skins=True,
    )
    clip_data = clip_rig.data
    bpy.data.objects.remove(clip_rig, do_unlink=True)
    bpy.data.armatures.remove(clip_data)
    for action in (walk, idle):
        bpy.data.actions.remove(action)

    before = {obj.name for obj in bpy.data.objects}
    armatures_before = sorted(a.name for a in bpy.data.armatures)
    import_gltf(path, **ANIMATE_IMPORT_OPTIONS)
    imported = sorted({obj.name for obj in bpy.data.objects} - before)
    armatures_imported = sorted(set(a.name for a in bpy.data.armatures) - set(armatures_before))

    merged = []
    hook = merge_hook("rig-job-1", "Rig", on_merged=lambda job, names: merged.append(names))
    # A real job carries the result's clip names in request order; the importer
    # stashes the tracks reversed, so the merge must follow this list.
    job = type("Job", (), {"scene_name": scene.name, "agent_ref": None,
                           "result_data": {"animations": ["walk", "idle"]}})()
    result_names = hook(job, ", ".join(imported))

    anim = rig.animation_data
    tracks = [(t.name, t.lock, t.mute, t.strips[0].action.name,
               t.strips[0].action_slot.identifier if t.strips[0].action_slot else None)
              for t in anim.nla_tracks]
    scene.frame_set(scene.frame_end)
    bpy.context.view_layer.update()
    posed = [round(v, 3) for v in rig.pose.bones["Hip"].location]
    return {
        "imported": imported,
        "armatures_imported": armatures_imported,
        "result_names": result_names,
        "on_merged": merged,
        "tracks": tracks,
        "active_action": anim.action.name if anim.action else None,
        "active_slot": anim.action_slot.identifier if anim.action_slot else None,
        "frame_range": [scene.frame_start, scene.frame_end, scene.frame_current],
        "hip_at_end": posed,
        "objects_left": sorted(obj.name for obj in bpy.data.objects),
        "armatures_left": sorted(a.name for a in bpy.data.armatures),
        "actions_left": sorted(a.name for a in bpy.data.actions),
        "my_pose_stashed": "my_pose" in [t[0] for t in tracks],
    }


if __name__ == "__main__":
    try:
        print("__RESULT__" + json.dumps(main()))
    except Exception:  # noqa: BLE001 — the smoke reports every failure
        print("__RESULT__" + json.dumps({"error": traceback.format_exc()}))
