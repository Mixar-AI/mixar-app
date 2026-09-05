# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export the live Mixar scene for Unreal (USD / FBX / GLB)."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

import bpy

from .constants import UNREAL_FBX_AXIS_FORWARD, UNREAL_FBX_AXIS_UP

_EXTENSIONS = {"usd": ".usd", "fbx": ".fbx", "glb": ".glb"}


def _select_export_objects(object_names: list[str] | None) -> list:
    view_layer = bpy.context.view_layer
    if bpy.ops.object.select_all.poll():
        bpy.ops.object.select_all(action="DESELECT")
    objects = []
    if object_names:
        for name in object_names:
            obj = bpy.data.objects.get(name)
            if obj is not None:
                objects.append(obj)
    else:
        objects = [
            obj
            for obj in bpy.context.scene.objects
            if obj.type in {"MESH", "ARMATURE", "EMPTY", "LIGHT", "CAMERA"}
            and obj.visible_get()
        ]
    meshes = [obj for obj in objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("No mesh objects are available to export")
    for obj in objects:
        try:
            obj.select_set(True)
        except RuntimeError:
            pass
    view_layer.objects.active = meshes[0]
    return meshes


def _run_operator(fmt: str, filepath: str) -> set:
    if fmt == "fbx":
        return bpy.ops.export_scene.fbx(
            filepath=filepath,
            use_selection=True,
            object_types={"MESH", "ARMATURE", "EMPTY", "CAMERA", "LIGHT"},
            axis_forward=UNREAL_FBX_AXIS_FORWARD,
            axis_up=UNREAL_FBX_AXIS_UP,
            apply_unit_scale=True,
            use_mesh_modifiers=True,
            bake_anim=True,
            add_leaf_bones=False,
            use_armature_deform_only=True,
            path_mode="COPY",
            embed_textures=True,
            bake_anim_use_all_bones=True,
        )
    if fmt == "glb":
        return bpy.ops.export_scene.gltf(
            filepath=filepath,
            export_format="GLB",
            use_selection=True,
            export_texcoords=True,
            export_normals=True,
            export_materials="EXPORT",
            export_cameras=True,
            export_lights=True,
            export_apply=True,
        )
    if fmt == "usd":
        return bpy.ops.wm.usd_export(
            filepath=filepath,
            selected_objects_only=True,
            export_materials=True,
            export_uvmaps=True,
            export_normals=True,
            export_animation=True,
            export_armatures=True,
            export_cameras=True,
            export_lights=True,
        )
    raise ValueError(f"Unsupported format: {fmt}")


def export_scene_for_unreal(fmt: str = "usd", object_names: list[str] | None = None, directory: str | None = None) -> dict:
    """Export the current Mixar scene with Unreal-friendly axes and materials."""
    fmt = fmt.lower()
    extension = _EXTENSIONS.get(fmt)
    if extension is None:
        raise ValueError(f"Unsupported format: {fmt}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    scene_name = bpy.context.scene.name or "mixar_scene"
    directory = directory or os.path.join(tempfile.gettempdir(), "mixar-connector")
    os.makedirs(directory, exist_ok=True)
    filepath = os.path.join(directory, f"{scene_name}_{stamp}{extension}")

    active = bpy.context.view_layer.objects.active
    selected = list(bpy.context.selected_objects)
    mode = active.mode if active else "OBJECT"
    try:
        if active and mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        meshes = _select_export_objects(object_names)
        result = _run_operator(fmt, filepath)
        if "FINISHED" not in result:
            raise RuntimeError(f"Mixar exporter returned {sorted(result)}")
        return {
            "ok": True,
            "format": fmt,
            "filepath": filepath,
            "filename": os.path.basename(filepath),
            "mesh_count": len(meshes),
            "bytes": os.path.getsize(filepath) if os.path.isfile(filepath) else 0,
        }
    finally:
        try:
            if bpy.ops.object.select_all.poll():
                bpy.ops.object.select_all(action="DESELECT")
            for obj in selected:
                if obj.name in bpy.context.view_layer.objects:
                    obj.select_set(True)
            if active and active.name in bpy.context.view_layer.objects:
                bpy.context.view_layer.objects.active = active
                if mode != "OBJECT":
                    bpy.ops.object.mode_set(mode=mode)
        except Exception:
            pass
