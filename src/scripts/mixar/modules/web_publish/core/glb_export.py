# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene export for web publishing (runs on Blender's main thread).

Produces a viewer-optimized GLB: modifiers applied, Mixar paint slots baked to
plain materials (reusing the export lane's swap), Draco mesh compression, WEBP
textures, and animation preserved. Also renders a viewport thumbnail and
collects scene statistics for the manifest.

The heavy lifting delegates to Blender's glTF exporter; this module owns only
Mixar-specific preparation and restoration.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.web_publish.constants import (
    DRACO_COMPRESSION_LEVEL,
    GLB_EXPORT_FILENAME,
    THUMBNAIL_FILENAME,
    THUMBNAIL_RESOLUTION,
)

_logger = get_logger(__name__)


class ExportError(Exception):
    pass


def collect_meshes(context) -> List[bpy.types.Object]:
    """Exportable mesh objects: visible scene meshes (whole scene publish)."""
    scene = context.scene
    return [obj for obj in scene.objects if obj.type == "MESH" and obj.visible_get()]


def make_export_workspace() -> Tuple[str, str]:
    """A temp directory for the GLB + thumbnail. Caller cleans it up."""
    workspace = tempfile.mkdtemp(prefix="mixar_web_publish_")
    return workspace, os.path.join(workspace, GLB_EXPORT_FILENAME)


def export_glb(context, filepath: str, include_animation: bool = True) -> None:
    """Export the whole visible scene to a Draco-compressed GLB.

    Restores selection/active object and any swapped materials afterwards;
    failures always clean up (the swap is a context manager).
    """
    meshes = collect_meshes(context)
    if not meshes:
        raise ExportError("No visible mesh objects to publish")

    active = context.view_layer.objects.active
    previous_mode = active.mode if active else "OBJECT"
    selected = list(context.selected_objects)
    try:
        if active and previous_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        if bpy.ops.object.select_all.poll():
            bpy.ops.object.select_all(action="DESELECT")

        armatures = _required_armatures(meshes)
        for obj in set(meshes) | armatures:
            obj.select_set(True)
        context.view_layer.objects.active = meshes[0]

        with _temporary_export_materials(meshes):
            result = bpy.ops.export_scene.gltf(
                filepath=filepath,
                export_format="GLB",
                use_selection=True,
                export_apply=True,
                export_texcoords=True,
                export_normals=True,
                export_materials="EXPORT",
                export_image_format="WEBP",
                export_animations=include_animation,
                export_cameras=False,
                export_lights=False,
                export_yup=True,
                export_draco_mesh_compression_enable=True,
                export_draco_mesh_compression_level=DRACO_COMPRESSION_LEVEL,
            )
        if "FINISHED" not in result:
            raise ExportError(f"Blender exporter returned {sorted(result)}")
        if not os.path.isfile(filepath) or os.path.getsize(filepath) == 0:
            raise ExportError("Exporter produced an empty file")
    finally:
        _restore_selection(context, active, previous_mode, selected)


def _required_armatures(meshes) -> set:
    armatures = set()
    for mesh in meshes:
        if mesh.parent and mesh.parent.type == "ARMATURE":
            armatures.add(mesh.parent)
        for modifier in mesh.modifiers:
            if modifier.type == "ARMATURE" and modifier.object:
                armatures.add(modifier.object)
    return armatures


def _temporary_export_materials(meshes):
    """Reuse the export lane's Mixar-slot swap (same contract as chat exports)."""
    from mixar.modules.space_mixie_chat.core.agent_export import (
        _temporary_export_materials as _swap,
    )

    return _swap(meshes)


def _restore_selection(context, active, previous_mode, selected) -> None:
    try:
        if bpy.ops.object.select_all.poll():
            bpy.ops.object.select_all(action="DESELECT")
        for obj in selected:
            if obj.name in context.view_layer.objects:
                obj.select_set(True)
        if active and active.name in context.view_layer.objects:
            context.view_layer.objects.active = active
            if previous_mode != "OBJECT":
                bpy.ops.object.mode_set(mode=previous_mode)
    except Exception:  # noqa: BLE001 - restoration is best-effort
        _logger.warning("web_publish selection restore failed", exc_info=True)


def render_thumbnail(context, filepath: str) -> Optional[str]:
    """Render a small still for the share page / gallery card.

    Prefers the current 3D viewport framing; falls back to the scene camera.
    Returns the filepath, or None when no thumbnail could be produced
    (thumbnail failure never fails a publish).
    """
    try:
        scene = context.scene
        render = scene.render
        original = (render.resolution_x, render.resolution_y, render.filepath,
                    render.image_settings.file_format, render.film_transparent)

        render.resolution_x, render.resolution_y = THUMBNAIL_RESOLUTION
        render.resolution_percentage = 100
        render.filepath = filepath
        render.image_settings.file_format = "PNG"

        override = {}
        area = getattr(context, "area", None)
        region = getattr(context, "region", None)
        if area is not None and getattr(area, "type", None) == "VIEW_3D":
            override = {"area": area, "region": region}
            with context.temp_override(**override):
                bpy.ops.render.opengl(write_still=True, use_viewport=True)
        else:
            bpy.ops.render.opengl(write_still=True)

        _restore_render_settings(render, original)
        if os.path.isfile(filepath) and os.path.getsize(filepath) > 0:
            return filepath
        return None
    except Exception as exc:  # noqa: BLE001 - thumbnails are best-effort
        _logger.warning(f"web_publish thumbnail render failed: {exc}")
        return None


def _restore_render_settings(render, original) -> None:
    try:
        render.resolution_x, render.resolution_y, render.filepath, \
            render.image_settings.file_format, render.film_transparent = original
    except Exception:  # noqa: BLE001
        pass


def collect_scene_meta(context) -> Dict[str, Any]:
    """Cheap statistics for the manifest (no depsgraph evaluation)."""
    meshes = collect_meshes(context)
    triangles = 0
    materials = set()
    textures = set()
    has_animation = False

    for mesh in meshes:
        mesh_data = mesh.data
        if mesh_data:
            triangles += sum(
                max(len(p.vertices) - 2, 0) for p in mesh_data.polygons
            )
            for material in mesh_data.materials:
                if material:
                    materials.add(material.name)
                    if material.use_nodes:
                        for node in material.node_tree.nodes:
                            image = getattr(node, "image", None)
                            if image:
                                textures.add(image.name)
        if mesh.animation_data and mesh.animation_data.action:
            has_animation = True

    return {
        "objects": len(meshes),
        "triangles": triangles,
        "materials": len(materials),
        "textures": len(textures),
        "animations": 1 if (has_animation or bool(context.scene.animation_data and
                                                context.scene.animation_data.action)) else 0,
    }


def collect_camera_config(context) -> Optional[Dict[str, Any]]:
    """Viewer camera block from the active camera, if the scene has one."""
    camera = context.scene.camera
    if camera is None:
        return None
    from mixar.modules.web_publish.core.publish_state import camera_pose_to_config

    data = camera.data
    return camera_pose_to_config(
        camera.matrix_world,
        getattr(data, "lens", 0.0),
        getattr(data, "sensor_width", 0.0),
    )


def cleanup_workspace(workspace: str) -> None:
    try:
        if workspace and os.path.isdir(workspace):
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
