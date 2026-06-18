# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent-facing helpers for Mixar Paint layer-stack workflows."""

from __future__ import annotations

from typing import Iterable

import bpy

from ....config.logging_config import get_logger
from ..procedural_materials import material_registry
from ..utils.constants import MP_GROUP_PREFIX
from .node.node_utils import get_active_mpaint_node

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

    for obj in bpy.data.objects:
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


def _unique_layer_name(base: str, layers, current=None) -> str:
    if not base:
        return ""
    existing = {
        layer.name for layer in layers
        if current is None or layer != current
    }
    if base not in existing:
        return base
    index = 2
    while f"{base} ({index})" in existing:
        index += 1
    return f"{base} ({index})"


def _ensure_registry_loaded() -> None:
    if material_registry.get_all_materials():
        return
    for loader_name in (
        "load_showcase_v7_materials",
        "load_showcase_v8_materials",
        "load_showcase_substance_materials",
        "load_matgen_materials",
    ):
        loader = getattr(material_registry, loader_name, None)
        if callable(loader):
            try:
                loader()
            except Exception:
                logger.warning("Failed procedural material loader: %s", loader_name, exc_info=True)


def _material_summary(material) -> dict:
    ready = bool(
        material.script
        or material.script_path
        or bpy.data.node_groups.get(material.node_group_name)
    )
    return {
        "material_id": material.material_id,
        "name": material.name,
        "category": material.category,
        "node_group_name": material.node_group_name,
        "ready": ready,
    }


def find_procedural_material(material_id: str = "", material_name: str = ""):
    _ensure_registry_loaded()
    if material_id:
        material = material_registry.get_material(material_id)
        if material:
            return material

    needle = (material_name or material_id or "").strip().lower()
    if not needle:
        return None

    materials = material_registry.get_all_materials()
    for material in materials:
        if material.name.lower() == needle or material.material_id.lower() == needle:
            return material
    for material in materials:
        if (
            material.name.lower().startswith(needle)
            or material.material_id.lower().startswith(needle)
        ):
            return material
    for material in materials:
        haystack = " ".join(
            [material.name, material.material_id, material.category]
        ).lower()
        if needle in haystack:
            return material
    return None


def list_procedural_materials(query: str = "", category: str = "", limit: int = 20) -> dict:
    """Return procedural materials available to the layer stack."""
    _ensure_registry_loaded()
    query_l = (query or "").strip().lower()
    category_l = (category or "").strip().lower()
    limit = max(1, min(int(limit or 20), 100))

    materials = material_registry.get_all_materials()
    if category_l:
        materials = [
            material for material in materials
            if material.category.lower() == category_l
        ]
    if query_l:
        materials = [
            material for material in materials
            if query_l in " ".join(
                [material.name, material.material_id, material.category]
            ).lower()
        ]

    materials = sorted(materials, key=lambda mat: (mat.category.lower(), mat.name.lower()))
    total = len(materials)
    return {
        "success": True,
        "total": total,
        "returned": min(total, limit),
        "categories": material_registry.get_categories(),
        "materials": [_material_summary(material) for material in materials[:limit]],
    }


def initialize_layer_paint_project(
    object_names=None,
    material_name: str = "",
    include_ao: bool = False,
) -> dict:
    """Create Mixar Paint nodes, core channels, and a default layer for targets."""
    targets, missing = _resolve_mesh_objects(object_names)
    if not targets:
        return {
            "success": False,
            "error": "No mesh objects found for layer paint initialization",
            "missing": missing,
        }

    snapshot = _selection_snapshot()
    initialized: list[dict] = []
    already_initialized: list[dict] = []
    errors: list[dict] = []

    try:
        for obj in targets:
            _activate_object(obj)
            node = get_active_mpaint_node()
            if node:
                already_initialized.append({
                    "object": obj.name,
                    "node": node.name,
                    "layers": len(node.node_tree.mp.layers),
                })
                continue

            base_name = (material_name or getattr(getattr(obj, "active_material", None), "name", "") or obj.name).strip()
            tree_name = base_name if base_name.startswith(MP_GROUP_PREFIX) else MP_GROUP_PREFIX + base_name
            try:
                result = bpy.ops.layers.create_material(
                    "EXEC_DEFAULT",
                    tree_name=tree_name,
                    set_material_name_from_tree_name=False,
                    type="BSDF_PRINCIPLED",
                    color=True,
                    ao=bool(include_ao),
                    metallic=True,
                    roughness=True,
                    normal=True,
                    switch_to_material_view=False,
                )
            except Exception as exc:
                errors.append({"object": obj.name, "error": str(exc)})
                continue

            if not _is_finished(result):
                errors.append({"object": obj.name, "error": f"create_material returned {result}"})
                continue

            node = get_active_mpaint_node()
            if not node:
                errors.append({"object": obj.name, "error": "Mixar Paint node was not created"})
                continue

            initialized.append({
                "object": obj.name,
                "node": node.name,
                "material": getattr(obj.active_material, "name", ""),
                "layers": len(node.node_tree.mp.layers),
                "channels": [channel.name for channel in node.node_tree.mp.channels],
            })
    finally:
        _restore_selection(snapshot)

    return {
        "success": not errors,
        "initialized": initialized,
        "already_initialized": already_initialized,
        "missing": missing,
        "errors": errors,
    }


def add_procedural_material_layer(
    material_id: str = "",
    material_name: str = "",
    object_names=None,
    layer_name: str = "",
    apply_to_existing: bool = False,
    initialize_if_needed: bool = True,
) -> dict:
    """Add a procedural material to the Mixar Paint layer stack for targets."""
    material = find_procedural_material(material_id=material_id, material_name=material_name)
    if material is None:
        return {
            "success": False,
            "error": "Procedural material not found",
            "material_id": material_id,
            "material_name": material_name,
        }

    targets, missing = _resolve_mesh_objects(object_names)
    if not targets:
        return {
            "success": False,
            "error": "No mesh objects found for procedural material layer",
            "missing": missing,
        }

    snapshot = _selection_snapshot()
    applied: list[dict] = []
    errors: list[dict] = []

    try:
        for obj in targets:
            _activate_object(obj)
            node = get_active_mpaint_node()
            if not node and initialize_if_needed:
                init_result = initialize_layer_paint_project([obj.name])
                if not init_result.get("success"):
                    errors.append({"object": obj.name, "error": init_result.get("error") or init_result.get("errors")})
                    continue
                _activate_object(obj)
                node = get_active_mpaint_node()

            if not node:
                errors.append({"object": obj.name, "error": "No active Mixar Paint node"})
                continue

            try:
                result = bpy.ops.layers.add_custom_procedural_layer(
                    "EXEC_DEFAULT",
                    material_id=material.material_id,
                    apply_to_existing=bool(apply_to_existing),
                )
            except Exception as exc:
                errors.append({"object": obj.name, "error": str(exc)})
                continue

            if not _is_finished(result):
                errors.append({"object": obj.name, "error": f"add_custom_procedural_layer returned {result}"})
                continue

            node = get_active_mpaint_node()
            mp = node.node_tree.mp
            active_layer = None
            if 0 <= mp.active_layer_index < len(mp.layers):
                active_layer = mp.layers[mp.active_layer_index]
                if layer_name:
                    active_layer.name = _unique_layer_name(layer_name, mp.layers, active_layer)

            applied.append({
                "object": obj.name,
                "material_id": material.material_id,
                "material_name": material.name,
                "layer": getattr(active_layer, "name", ""),
                "layers": len(mp.layers),
                "channels": [channel.name for channel in mp.channels],
            })
    finally:
        _restore_selection(snapshot)

    return {
        "success": not errors and bool(applied),
        "applied": applied,
        "missing": missing,
        "errors": errors,
    }


def enqueue_procedural_material_generation(
    prompt: str,
    pipeline: str = "fast",
    object_names=None,
    add_to_layer_stack: bool = False,
    layer_name: str = "",
    apply_to_existing: bool = False,
) -> dict:
    """Queue AI material generation and optionally auto-apply on completion."""
    prompt = (prompt or "").strip()
    if not prompt:
        return {"success": False, "error": "prompt is required"}

    from ..procedural_materials.matgen_queue import enqueue_matgen_job, model_for_pipeline

    target_names: list[str] = []
    missing: list[str] = []
    if add_to_layer_stack:
        targets, missing = _resolve_mesh_objects(object_names)
        if not targets:
            return {
                "success": False,
                "error": "No mesh objects found for generated material auto-apply",
                "missing": missing,
            }
        target_names = [obj.name for obj in targets]

    job = enqueue_matgen_job(
        prompt=prompt,
        model=model_for_pipeline(pipeline),
        pipeline=pipeline,
        apply_to_object_names=target_names,
        layer_name=layer_name,
        apply_to_existing=bool(apply_to_existing),
    )
    if job is None:
        return {
            "success": False,
            "error": "Duplicate material generation job already in queue",
        }

    return {
        "success": True,
        "job_id": job.id,
        "state": job.state.value,
        "prompt": prompt,
        "pipeline": pipeline,
        "model": job.model,
        "auto_apply": bool(target_names),
        "target_objects": target_names,
        "missing": missing,
    }


def get_procedural_material_generation_status(job_id: str = "") -> dict:
    """Return queued/recent AI procedural material generation jobs."""
    from mixar.modules.common.job_queue import get_queue
    from mixar.modules.common.job_queue.constants import FEATURE_MATGEN

    jobs = []
    for job in get_queue(FEATURE_MATGEN).snapshot():
        if job_id and job.id != job_id and getattr(job, "backend_job_id", "") != job_id:
            continue
        jobs.append({
            "job_id": job.id,
            "backend_job_id": getattr(job, "backend_job_id", ""),
            "state": job.state.value,
            "prompt": getattr(job, "prompt", ""),
            "pipeline": getattr(job, "pipeline", ""),
            "material_id": getattr(job, "material_id", ""),
            "material_name": getattr(job, "material_name", ""),
            "error": getattr(job, "error", ""),
            "user_message": getattr(job, "user_message", ""),
            "auto_apply": bool(getattr(job, "apply_to_object_names", [])),
            "target_objects": list(getattr(job, "apply_to_object_names", [])),
        })
    return {"success": True, "jobs": jobs, "total": len(jobs)}
