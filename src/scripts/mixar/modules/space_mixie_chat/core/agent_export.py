# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Non-destructive Blender-native export execution for the export agent."""

from __future__ import annotations

import os
from contextlib import contextmanager

import bpy

from .export_destination import pop_destination
from .export_preflight import (
    active_mixar_nodes,
    clear_repair_cache,
    repair_export,
    resolve_targets,
    run_preflight,
)

_EXTENSIONS = {"fbx": ".fbx", "glb": ".glb", "obj": ".obj", "usd": ".usd"}


def _required_armatures(meshes) -> set:
    armatures = set()
    for mesh in meshes:
        if mesh.parent and mesh.parent.type == 'ARMATURE':
            armatures.add(mesh.parent)
        for modifier in mesh.modifiers:
            if modifier.type == 'ARMATURE' and modifier.object:
                armatures.add(modifier.object)
    return armatures


def _run_operator(fmt: str, filepath: str, use_case: str) -> set:
    if fmt == "fbx":
        return bpy.ops.export_scene.fbx(
            filepath=filepath, use_selection=True, object_types={'MESH', 'ARMATURE'},
            axis_forward='-Z', axis_up='Y', apply_unit_scale=True,
            use_mesh_modifiers=True, bake_anim=True,
            add_leaf_bones=False, use_armature_deform_only=True,
            path_mode='COPY', embed_textures=True,
            bake_anim_use_all_bones=(use_case == "unreal"),
        )
    if fmt == "glb":
        return bpy.ops.export_scene.gltf(
            filepath=filepath, export_format='GLB', use_selection=True,
            export_texcoords=True, export_normals=True, export_materials='EXPORT',
            export_image_format='AUTO', export_animations=True,
            export_cameras=False, export_lights=False,
            export_apply=False,
        )
    if fmt == "obj":
        return bpy.ops.wm.obj_export(
            filepath=filepath, export_selected_objects=True,
            export_uv=True, export_normals=True, export_materials=True,
            path_mode='AUTO',
        )
    if fmt == "usd":
        return bpy.ops.wm.usd_export(
            filepath=filepath, selected_objects_only=True,
            export_materials=True, export_uvmaps=True, export_normals=True,
            export_animation=True, export_armatures=True,
            export_cameras=False, export_lights=False,
        )
    raise ValueError(f"Unsupported export format: {fmt}")


@contextmanager
def _temporary_export_materials(meshes):
    """Swap every Mixar slot to a Principled/image material for export."""
    from mixar.modules.paint.core.asset_export.bake_and_assign import (
        create_export_material,
    )

    assignments, created = [], []
    try:
        for obj in meshes:
            original_index = obj.active_material_index
            try:
                for index, material in enumerate(list(obj.data.materials)):
                    nodes = active_mixar_nodes(material)
                    if not nodes:
                        continue
                    obj.active_material_index = index
                    export_material = create_export_material(
                        obj, nodes[0].node_tree.mp, nodes[0].node_tree,
                    )
                    if export_material:
                        assignments.append((obj, index, material))
                        created.append(export_material)
            finally:
                obj.active_material_index = original_index
        yield
    finally:
        for obj, index, material in reversed(assignments):
            try:
                obj.data.materials[index] = material
            except Exception:
                pass
        for material in created:
            try:
                if material.users == 0:
                    bpy.data.materials.remove(material)
            except Exception:
                pass


def run_export(session_id: str, spec: dict) -> dict:
    """Consume the local destination and export while restoring UI state."""
    filepath = pop_destination(session_id)
    if not filepath:
        return {"success": False, "error": "No export destination was selected"}
    fmt = str(spec.get("format") or "").lower()
    extension = _EXTENSIONS.get(fmt)
    if extension is None or os.path.splitext(filepath)[1].lower() != extension:
        return {"success": False, "error": "Export destination extension mismatch"}

    active = bpy.context.view_layer.objects.active
    selected = list(bpy.context.selected_objects)
    mode = active.mode if active else 'OBJECT'
    try:
        if active and mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        meshes = resolve_targets(
            str(spec.get("target_scope") or "scene"),
            list(spec.get("object_names") or []),
        )
        armatures = _required_armatures(meshes)
        export_objects = set(meshes) | armatures
        if bpy.ops.object.select_all.poll():
            bpy.ops.object.select_all(action='DESELECT')
        for obj in export_objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        with _temporary_export_materials(meshes):
            result = _run_operator(fmt, filepath, str(spec.get("use_case") or "other"))
        if 'FINISHED' not in result:
            raise RuntimeError(f"Blender exporter returned {sorted(result)}")
        warning = "OBJ is static-only; rigs and animation were omitted." if fmt == "obj" else ""
        return {
            "success": True,
            "filepath_basename": os.path.basename(filepath),
            "mesh_count": len(meshes),
            "warning": warning.strip(),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        clear_repair_cache(session_id)
        try:
            if bpy.ops.object.select_all.poll():
                bpy.ops.object.select_all(action='DESELECT')
            for obj in selected:
                if obj.name in bpy.context.view_layer.objects:
                    obj.select_set(True)
            if active and active.name in bpy.context.view_layer.objects:
                bpy.context.view_layer.objects.active = active
                if mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode=mode)
        except Exception:
            pass


def inspect_export(spec: dict) -> dict:
    """RPC entrypoint used before the native save picker is opened."""
    try:
        return run_preflight(spec)
    except Exception as exc:
        return {"success": False, "ready": False, "error": str(exc)}
