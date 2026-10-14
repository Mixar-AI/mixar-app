# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene → GLB for web publishing (Blender's main thread).

Thin by design: the bytes come from the shared agent export lane
(``space_mixie_chat.core.agent_export.export_to_path``) with
``use_case="web"``, ``format="glb"``, ``target_scope="scene"`` and the
``web_publish`` preset profile (Draco level 6, WebP textures, modifiers
applied). That lane already stages the scene's cameras, punctual lights and
EMPTY-ancestor groups, writes physical (``SPEC``) light units and custom
properties, swaps Mixar Paint slots to exportable materials, restores
selection/mode and verifies the written file. This module only picks the
visible meshes and gathers the manifest's statistics and camera block.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import bpy

from mixar.modules.web_publish.constants import (
    EXPORT_FORMAT,
    EXPORT_PROFILE,
    EXPORT_SCOPE,
    EXPORT_TELEMETRY_TOOL,
    EXPORT_TELEMETRY_VIA,
    EXPORT_USE_CASE,
)
from mixar.modules.web_publish.core.publish_state import (
    build_scene_meta,
    camera_pose_to_config,
)


class ExportError(Exception):
    pass


def visible_meshes(scene) -> List[Any]:
    """The scene meshes a visitor would see (hidden objects stay private)."""
    meshes = []
    for obj in scene.objects:
        if obj.type != 'MESH':
            continue
        try:
            if obj.visible_get() and not obj.hide_render:
                meshes.append(obj)
        except RuntimeError:  # not in the active view layer
            continue
    return meshes


def build_export_spec(mesh_names: List[str], include_animation: bool) -> Dict[str, Any]:
    """The shared export lane's spec for a publish (pure; pinned by tests).

    ``mesh_names`` pins the visible meshes (scope ``scene`` alone would take
    hidden ones too); ``animations`` ``None`` = every clip, ``[]`` = none."""
    return {
        "format": EXPORT_FORMAT,
        "use_case": EXPORT_USE_CASE,
        "target_scope": EXPORT_SCOPE,
        "profile": EXPORT_PROFILE,
        "mesh_names": list(mesh_names),
        "animations": None if include_animation else [],
        "destination": "web_publish",
    }


def export_glb(filepath: str, meshes, include_animation: bool = True) -> Dict[str, Any]:
    """Export to ``filepath`` through the shared lane; returns its result
    (``warning``, ``verification``, ``scene_objects``…). Raises ExportError."""
    if not meshes:
        raise ExportError("No visible mesh objects to publish")
    from mixar.modules.space_mixie_chat.core.agent_export import export_to_path

    spec = build_export_spec([obj.name for obj in meshes], include_animation)
    result = export_to_path(filepath, spec, via=EXPORT_TELEMETRY_VIA,
                            tool=EXPORT_TELEMETRY_TOOL)
    if not result.get("success"):
        raise ExportError(str(result.get("error") or "Export failed"))
    return result


def _triangles(mesh_data) -> int:
    polygons = getattr(mesh_data, "polygons", None)
    if not polygons:
        return 0
    try:
        import numpy as np

        counts = np.empty(len(polygons), dtype=np.int32)
        polygons.foreach_get("loop_total", counts)
        return int(np.clip(counts - 2, 0, None).sum())
    except Exception:  # noqa: BLE001 — statistics are best-effort
        return 0


def collect_scene_meta(scene, meshes) -> Dict[str, Any]:
    """Cheap statistics for the manifest (no depsgraph evaluation)."""
    triangles = 0
    materials, textures = set(), set()
    has_animation = bool(scene.animation_data and scene.animation_data.action)
    for obj in meshes:
        data = obj.data
        if data is not None:
            triangles += _triangles(data)
            for material in data.materials:
                if material is None:
                    continue
                materials.add(material.name)
                tree = getattr(material, "node_tree", None)
                for node in getattr(tree, "nodes", ()) or ():
                    image = getattr(node, "image", None)
                    if image is not None:
                        textures.add(image.name)
        if obj.animation_data and obj.animation_data.action:
            has_animation = True
    return build_scene_meta(len(meshes), triangles, len(materials), len(textures),
                            has_animation)


def collect_camera_config(scene) -> Optional[Dict[str, Any]]:
    """Viewer camera block from the active camera, if the scene has one."""
    camera = scene.camera
    if camera is None:
        return None
    data = camera.data
    return camera_pose_to_config(camera.matrix_world, getattr(data, "lens", 0.0),
                                 getattr(data, "sensor_width", 0.0)) or None
