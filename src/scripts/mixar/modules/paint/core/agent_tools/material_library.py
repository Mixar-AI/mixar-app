# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent-facing procedural material discovery and AI generation queueing."""

from __future__ import annotations

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.paint.procedural_materials import material_registry

from ._common import _resolve_mesh_objects

logger = get_logger(__name__)


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

    from mixar.modules.paint.procedural_materials.matgen_queue import enqueue_matgen_job

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
