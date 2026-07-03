# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared internals for the agent-facing Mixar Paint layer-stack workflows."""

from __future__ import annotations

from typing import Iterable

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.paint.utils.constants import MP_GROUP_PREFIX

logger = get_logger(__name__)


def _as_name_list(names) -> list[str]:
    if not names:
        return []
    if isinstance(names, str):
        return [names]
    return [str(name) for name in names if str(name).strip()]


def _object_children_recursive(obj) -> Iterable:
    try:
        return obj.children_recursive
    except Exception:
        return ()


def _add_mesh_target(obj, out: dict[str, object]) -> None:
    if getattr(obj, "type", "") == "MESH":
        out[obj.name] = obj
    for child in _object_children_recursive(obj):
        if getattr(child, "type", "") == "MESH":
            out[child.name] = child


def _resolve_mesh_objects(object_names=None) -> tuple[list[object], list[str]]:
    targets: dict[str, object] = {}
    missing: list[str] = []
    names = _as_name_list(object_names)

    if names:
        for name in names:
            obj = bpy.data.objects.get(name)
            if obj is None:
                missing.append(name)
                continue
            _add_mesh_target(obj, targets)
        return list(targets.values()), missing

    selected = [
        obj for obj in getattr(bpy.context, "selected_objects", [])
        if getattr(obj, "type", "") == "MESH" or list(_object_children_recursive(obj))
    ]
    if selected:
        for obj in selected:
            _add_mesh_target(obj, targets)
        return list(targets.values()), []

    active = getattr(bpy.context, "active_object", None)
    if active is not None:
        _add_mesh_target(active, targets)
    if targets:
        return list(targets.values()), []

    # Scope the final fallback to the active scene. bpy.data.objects includes
    # every object across all scenes and unlinked datablocks.
    scene = getattr(bpy.context, "scene", None)
    for obj in getattr(scene, "objects", []):
        _add_mesh_target(obj, targets)
    return list(targets.values()), []


def _selection_snapshot() -> tuple[str, list[str]]:
    active = getattr(bpy.context, "active_object", None)
    selected = getattr(bpy.context, "selected_objects", [])
    return (
        getattr(active, "name", ""),
        [getattr(obj, "name", "") for obj in selected],
    )


def _restore_selection(snapshot: tuple[str, list[str]]) -> None:
    active_name, selected_names = snapshot
    try:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    try:
        for obj in bpy.context.scene.objects:
            obj.select_set(obj.name in selected_names)
        active = bpy.data.objects.get(active_name)
        if active is not None:
            bpy.context.view_layer.objects.active = active
    except Exception:
        logger.debug("Could not restore selection", exc_info=True)


def _activate_object(obj) -> None:
    try:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    for scene_obj in getattr(bpy.context.scene, "objects", []):
        try:
            scene_obj.select_set(False)
        except Exception:
            pass
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _is_finished(result) -> bool:
    return result == {"FINISHED"} or "FINISHED" in set(result or ())


def _ensure_basic_uv_map(obj) -> bool:
    """Create a simple box-projected UV map for primitive meshes without UVs."""
    mesh = getattr(obj, "data", None)
    if mesh is None or getattr(obj, "type", "") != "MESH":
        return False
    if len(getattr(mesh, "uv_layers", [])) > 0:
        return False
    if not getattr(mesh, "vertices", None) or not getattr(mesh, "polygons", None):
        return False

    try:
        uv_layer = mesh.uv_layers.new(name="UVMap")
        coords = [vertex.co for vertex in mesh.vertices]
        mins = [min(co[i] for co in coords) for i in range(3)]
        maxs = [max(co[i] for co in coords) for i in range(3)]
        spans = [max(maxs[i] - mins[i], 1e-6) for i in range(3)]

        for poly in mesh.polygons:
            dominant_axis = max(range(3), key=lambda axis: abs(poly.normal[axis]))
            if dominant_axis == 0:
                axis_u, axis_v = 1, 2
            elif dominant_axis == 1:
                axis_u, axis_v = 0, 2
            else:
                axis_u, axis_v = 0, 1
            for loop_index in poly.loop_indices:
                vertex_index = mesh.loops[loop_index].vertex_index
                co = mesh.vertices[vertex_index].co
                uv_layer.data[loop_index].uv = (
                    (co[axis_u] - mins[axis_u]) / spans[axis_u],
                    (co[axis_v] - mins[axis_v]) / spans[axis_v],
                )
        mesh.update()
        return True
    except Exception:
        logger.debug("Could not create basic UV map for %s", getattr(obj, "name", ""), exc_info=True)
        return False


def _find_mpaint_node(obj):
    if not obj or not getattr(obj, "active_material", None):
        return None
    mat = obj.active_material
    if not getattr(mat, "use_nodes", False) or not getattr(mat, "node_tree", None):
        return None
    for node in mat.node_tree.nodes:
        if node.type == "GROUP" and node.node_tree and hasattr(node.node_tree, "mp"):
            return node
    return None


def _find_mpaint_node_for_material(mat):
    if mat is None or not getattr(mat, "node_tree", None):
        return None
    for node in getattr(mat.node_tree, "nodes", []):
        tree = getattr(node, "node_tree", None)
        mp = getattr(tree, "mp", None) if tree is not None else None
        if getattr(mp, "is_mpaint_node", False):
            return node
    return None


def _sync_layer_stack_ui(node, mp) -> None:
    try:
        from mixar.modules.paint.ui.utils.ui_refresh import simple_update_mixar_tree_ui
        simple_update_mixar_tree_ui(bpy.context, node, node.node_tree, mp)
    except Exception:
        logger.debug("Could not sync Mixar layer UI", exc_info=True)


def _clean_material_name(name: str, fallback: str) -> str:
    raw = (name or fallback or "Scene Material").strip()
    safe = "".join(ch if ch.isalnum() or ch in " _-." else "_" for ch in raw)
    safe = " ".join(safe.split()) or "Scene Material"
    return safe[:80]


def _unique_material_datablock_name(base: str, current=None) -> str:
    name = _clean_material_name(base, "Shared Material")
    existing = bpy.data.materials.get(name)
    if existing is None or existing == current:
        return name
    suffix = 2
    while True:
        candidate = f"{name} ({suffix})"
        existing = bpy.data.materials.get(candidate)
        if existing is None or existing == current:
            return candidate
        suffix += 1


def _unique_node_group_name(base: str, current=None) -> str:
    name = _clean_material_name(base, "Shared Material")
    if not name.startswith(MP_GROUP_PREFIX):
        name = MP_GROUP_PREFIX + name
    existing = bpy.data.node_groups.get(name)
    if existing is None or existing == current:
        return name
    suffix = 2
    while True:
        candidate = f"{name} ({suffix})"
        existing = bpy.data.node_groups.get(candidate)
        if existing is None or existing == current:
            return candidate
        suffix += 1


def _assign_material_to_object(obj, mat) -> None:
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)
    try:
        obj.active_material_index = 0
    except Exception:
        pass


def _semanticize_shared_material(mat, semantic_name: str, source_prompt: str = "") -> str:
    if mat is None:
        return ""
    material_name = _unique_material_datablock_name(semantic_name, mat)
    mat.name = material_name
    mat["mixar_semantic_material_name"] = semantic_name
    mat["mixar_shared_texture_set"] = True
    if source_prompt:
        mat["mixar_source_prompt"] = source_prompt

    node = _find_mpaint_node_for_material(mat)
    if node is not None and node.node_tree is not None:
        node.node_tree.name = _unique_node_group_name(material_name, node.node_tree)
    return mat.name


def _material_layer_snapshot(layer) -> dict:
    return {
        "name": getattr(layer, "name", ""),
        "type": getattr(layer, "type", ""),
        "source_type": getattr(layer, "source_type", ""),
        "procedural_material_id": getattr(layer, "procedural_material_id", ""),
    }


def _material_application_snapshot(
    object_names=None,
    expected_material_id: str = "",
    expected_layer_name: str = "",
    placeholder_material_name: str = "",
) -> dict:
    """Summarize current material/layer state after an agent material pass."""
    targets, missing = _resolve_mesh_objects(object_names)
    expected_material_id = (expected_material_id or "").strip()
    expected_layer_name = (expected_layer_name or "").strip()
    placeholder_material_name = (placeholder_material_name or "").strip()

    objects = []
    for obj in targets:
        slots = [
            getattr(getattr(slot, "material", None), "name", "")
            for slot in getattr(obj, "material_slots", [])
        ]
        mat = getattr(obj, "active_material", None)
        node = _find_mpaint_node_for_material(mat)
        layers = []
        channels = []
        if node is not None:
            mp = node.node_tree.mp
            layers = [_material_layer_snapshot(layer) for layer in mp.layers]
            channels = [channel.name for channel in mp.channels]

        layer_ids = {layer.get("procedural_material_id", "") for layer in layers}
        layer_names = {layer.get("name", "") for layer in layers}
        has_expected_procedural_layer = bool(
            (expected_material_id and expected_material_id in layer_ids)
            or (expected_layer_name and expected_layer_name in layer_names)
        )
        has_expected_placeholder = bool(
            placeholder_material_name and placeholder_material_name in slots
        )

        objects.append({
            "object": obj.name,
            "active_material": getattr(mat, "name", ""),
            "material_slots": slots,
            "mpaint_node": getattr(node, "name", "") if node else "",
            "layers": layers,
            "channels": channels,
            "has_expected_procedural_layer": has_expected_procedural_layer,
            "has_expected_placeholder": has_expected_placeholder,
        })

    expects_procedural = bool(expected_material_id or expected_layer_name)
    expects_placeholder = bool(placeholder_material_name)
    verified = bool(objects) and not missing
    if expects_procedural:
        verified = verified and all(item["has_expected_procedural_layer"] for item in objects)
    if expects_placeholder:
        verified = verified and all(item["has_expected_placeholder"] for item in objects)

    return {
        "verified": verified,
        "expected_material_id": expected_material_id,
        "expected_layer_name": expected_layer_name,
        "placeholder_material_name": placeholder_material_name,
        "objects": objects,
        "missing": missing,
    }
