# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent-facing scene-material preparation, queueing, and budgeted application."""

from __future__ import annotations

import time

import bpy

from mixar.config.logging_config import get_logger

from ._common import (
    _as_name_list,
    _assign_material_to_object,
    _clean_material_name,
    _material_application_snapshot,
    _resolve_mesh_objects,
)
from .layer_stack import add_procedural_material_layer

logger = get_logger(__name__)


_BASIC_PLACEHOLDER_COLORS = {
    "white": (0.82, 0.82, 0.78, 1.0),
    "black": (0.02, 0.02, 0.02, 1.0),
    "gray": (0.45, 0.45, 0.45, 1.0),
    "grey": (0.45, 0.45, 0.45, 1.0),
    "red": (0.75, 0.08, 0.05, 1.0),
    "green": (0.08, 0.45, 0.12, 1.0),
    "blue": (0.06, 0.18, 0.75, 1.0),
    "yellow": (0.95, 0.75, 0.08, 1.0),
    "brown": (0.36, 0.18, 0.08, 1.0),
    "tan": (0.62, 0.48, 0.32, 1.0),
}


def _color_from_spec(spec: dict) -> tuple[float, float, float, float]:
    value = spec.get("color") or spec.get("base_color")
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        vals = [max(0.0, min(1.0, float(v))) for v in value[:4]]
        if len(vals) == 3:
            vals.append(float(spec.get("alpha", 1.0) or 1.0))
        return tuple(vals[:4])

    haystack = " ".join(
        str(spec.get(k, "")) for k in ("name", "key", "prompt", "material_prompt")
    ).lower()
    for word, color in _BASIC_PLACEHOLDER_COLORS.items():
        if word in haystack:
            return color
    return (0.6, 0.6, 0.58, float(spec.get("alpha", 1.0) or 1.0))


def _set_input_default(node, names: tuple[str, ...], value) -> None:
    if node is None:
        return
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            socket.default_value = value
            return


def _create_placeholder_material(spec: dict) -> dict:
    key = str(spec.get("key") or spec.get("name") or "placeholder").strip()
    name = _clean_material_name(
        spec.get("name") or spec.get("layer_name"),
        f"Placeholder {key}",
    )
    if not name.startswith("Placeholder "):
        name = f"Placeholder {name}"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    color = _color_from_spec(spec)
    metallic = max(0.0, min(1.0, float(spec.get("metallic", 0.0) or 0.0)))
    roughness = max(0.0, min(1.0, float(spec.get("roughness", 0.65) or 0.65)))
    _set_input_default(bsdf, ("Base Color",), color)
    _set_input_default(bsdf, ("Metallic",), metallic)
    _set_input_default(bsdf, ("Roughness",), roughness)
    _set_input_default(bsdf, ("Alpha",), color[3])
    if color[3] < 1.0:
        try:
            mat.blend_method = "BLEND"
            mat.use_screen_refraction = True
        except Exception:
            pass
    mat["mixar_scene_material_placeholder"] = True
    mat["mixar_scene_material_key"] = key
    return {
        "key": key,
        "mode": "placeholder",
        "material_name": mat.name,
        "color": list(color),
        "metallic": metallic,
        "roughness": roughness,
        "state": "READY",
    }


def _scene_material_prompt(spec: dict) -> str:
    prompt = (
        spec.get("prompt")
        or spec.get("material_prompt")
        or spec.get("description")
        or spec.get("name")
        or spec.get("key")
        or "procedural material"
    )
    prompt = str(prompt).strip()
    context_parts = []
    object_desc = spec.get("object_description") or spec.get("object") or spec.get("target")
    if object_desc:
        context_parts.append(f"Object/surface: {object_desc}")
    size_m = spec.get("size_m") or spec.get("scale_m")
    if size_m:
        context_parts.append(f"Object scale: largest dimension about {size_m} meters")
    role = spec.get("role") or spec.get("use")
    if role:
        context_parts.append(f"Scene role/use: {role}")
    if context_parts:
        prompt = prompt + "\n" + "\n".join(context_parts)
    prompt += (
        "\nGenerate a Blender procedural material for the Mixar Paint layer system. "
        "Use object-appropriate procedural scale, physically plausible Base Color, "
        "Metallic, Roughness, Normal/Height, Alpha and any necessary secondary channels. "
        "Do not use external image textures."
    )
    return prompt


def _find_matgen_job(job_id: str = "", key: str = ""):
    from mixar.modules.common.job_queue.constants import FEATURE_MATGEN
    from mixar.modules.common.job_queue import get_queue

    for job in get_queue(FEATURE_MATGEN).snapshot():
        if job_id and job.id == job_id:
            return job
        if job_id and getattr(job, "backend_job_id", "") == job_id:
            return job
        if key and getattr(job, "scene_material_key", "") == key:
            return job
    return None


def _matgen_job_summary(job) -> dict:
    state = getattr(job, "state", "")
    state_value = getattr(state, "value", str(state))
    material_id = getattr(job, "material_id", "")
    return {
        "key": getattr(job, "scene_material_key", ""),
        "mode": "detailed",
        "job_id": getattr(job, "id", ""),
        "backend_job_id": getattr(job, "backend_job_id", ""),
        "state": state_value,
        "ready": state_value == "SUCCESS" and bool(material_id),
        "prompt": getattr(job, "prompt", ""),
        "pipeline": getattr(job, "pipeline", ""),
        "material_id": material_id,
        "material_name": getattr(job, "material_name", ""),
        "planned_object_names": list(getattr(job, "planned_object_names", [])),
        "error": getattr(job, "error", ""),
        "user_message": getattr(job, "user_message", ""),
    }


def _assign_placeholder_material(material_name: str, object_names=None) -> dict:
    mat = bpy.data.materials.get(material_name)
    if mat is None:
        return {"success": False, "error": "Placeholder material not found", "material_name": material_name}

    targets, missing = _resolve_mesh_objects(object_names)
    if not targets:
        return {"success": False, "error": "No mesh objects found", "missing": missing}

    applied = []
    for obj in targets:
        try:
            _assign_material_to_object(obj, mat)
            applied.append({"object": obj.name, "material_name": mat.name})
        except Exception as exc:
            applied.append({"object": obj.name, "error": str(exc)})
    errors = [item for item in applied if item.get("error")]
    return {"success": not errors, "applied": applied, "missing": missing, "errors": errors}


def prepare_scene_materials(materials: list[dict]) -> dict:
    """Prepare placeholders and queue detailed MatGen jobs for a planned scene."""
    if not isinstance(materials, list):
        return {"success": False, "error": "materials must be a list"}

    from mixar.modules.paint.procedural_materials.matgen_queue import enqueue_matgen_job

    prepared = []
    errors = []
    for index, spec in enumerate(materials):
        if not isinstance(spec, dict):
            errors.append({"index": index, "error": "material spec must be a dict"})
            continue
        key = str(spec.get("key") or spec.get("name") or f"material_{index + 1}").strip()
        mode = str(spec.get("mode") or ("placeholder" if spec.get("placeholder") else "detailed")).lower()
        if mode in {"basic", "simple", "flat", "bpy"}:
            mode = "placeholder"

        if mode == "placeholder":
            try:
                prepared.append(_create_placeholder_material({**spec, "key": key}))
            except Exception as exc:
                errors.append({"key": key, "error": str(exc)})
            continue

        prompt = _scene_material_prompt({**spec, "key": key})
        planned_names = spec.get("object_names") or spec.get("planned_object_names") or []
        if isinstance(planned_names, str):
            planned_names = [planned_names]
        job = enqueue_matgen_job(
            prompt=prompt,
            pipeline="detailed",
            planned_object_names=planned_names,
            scene_material_key=key,
            layer_name=spec.get("layer_name") or spec.get("name") or key,
        )
        if job is None:
            errors.append({"key": key, "error": "Duplicate material generation job already in queue"})
            continue
        prepared.append(_matgen_job_summary(job))

    return {
        "success": not errors,
        "prepared": prepared,
        "queued": sum(1 for item in prepared if item.get("pipeline") == "detailed"),
        "placeholders": sum(1 for item in prepared if item.get("mode") == "placeholder"),
        "errors": errors,
    }


def get_prepared_scene_material_status(job_ids=None, keys=None) -> dict:
    """Return status for scene material jobs created by prepare_scene_materials."""
    from mixar.modules.common.job_queue.constants import FEATURE_MATGEN
    from mixar.modules.common.job_queue import get_queue

    job_filter = set(_as_name_list(job_ids))
    key_filter = set(_as_name_list(keys))
    jobs = []
    for job in get_queue(FEATURE_MATGEN).snapshot():
        if job_filter and job.id not in job_filter and getattr(job, "backend_job_id", "") not in job_filter:
            continue
        if key_filter and getattr(job, "scene_material_key", "") not in key_filter:
            continue
        jobs.append(_matgen_job_summary(job))
    return {"success": True, "jobs": jobs, "total": len(jobs)}


def _material_apply_budget(time_budget_s) -> float:
    try:
        value = float(time_budget_s)
    except Exception:
        value = 20.0
    return max(5.0, min(value, 30.0))


def _deferred_material_assignment(spec: dict, object_names: list[str], reason: str) -> dict:
    assignment = dict(spec)
    assignment["object_names"] = list(object_names)
    return {
        "key": str(spec.get("key") or "").strip(),
        "reason": reason,
        "object_names": list(object_names),
        "assignment": assignment,
    }


def apply_prepared_scene_materials(assignments: list[dict], time_budget_s: float = 20.0) -> dict:
    """Apply prepared placeholder/direct materials or generated procedural layers."""
    if not isinstance(assignments, list):
        return {"success": False, "error": "assignments must be a list"}

    budget_s = _material_apply_budget(time_budget_s)
    started_at = time.monotonic()
    deadline = started_at + budget_s
    applied = []
    pending = []
    errors = []
    for index, spec in enumerate(assignments):
        if not isinstance(spec, dict):
            errors.append({"index": index, "error": "assignment must be a dict"})
            continue
        if time.monotonic() >= deadline:
            for remaining_offset, remaining in enumerate(assignments[index:]):
                if isinstance(remaining, dict):
                    names = remaining.get("object_names") or remaining.get("objects") or []
                    pending.append(_deferred_material_assignment(remaining, _as_name_list(names), "time_budget_exhausted"))
                else:
                    errors.append({"index": index + remaining_offset, "error": "assignment must be a dict"})
            break

        key = str(spec.get("key") or "").strip()
        object_names = spec.get("object_names") or spec.get("objects") or []
        material_id = spec.get("material_id") or ""
        material_name = spec.get("material_name") or spec.get("placeholder_material_name") or ""
        job_id = spec.get("job_id") or spec.get("backend_job_id") or ""

        if job_id and not material_id:
            job = _find_matgen_job(job_id=job_id, key=key)
            if job is None:
                errors.append({"key": key, "job_id": job_id, "error": "MatGen job not found"})
                continue
            summary = _matgen_job_summary(job)
            if not summary.get("ready"):
                pending.append(summary)
                continue
            material_id = summary.get("material_id", "")
            material_name = summary.get("material_name", "")

        is_placeholder = bool(spec.get("placeholder")) or str(spec.get("mode", "")).lower() == "placeholder"
        mat = bpy.data.materials.get(material_name) if material_name else None
        if mat is not None and mat.get("mixar_scene_material_placeholder"):
            is_placeholder = True

        layer_name = spec.get("layer_name") or material_name or key
        if is_placeholder:
            result = _assign_placeholder_material(material_name, object_names)
            verification = _material_application_snapshot(
                object_names,
                placeholder_material_name=material_name,
            )
        elif material_id or material_name:
            targets, missing = _resolve_mesh_objects(object_names)
            if not targets:
                errors.append({"key": key, "error": "No mesh objects found for procedural material layer", "missing": missing})
                continue

            target_names = [target.name for target in targets]
            result = add_procedural_material_layer(
                material_id=material_id,
                material_name=material_name,
                object_names=target_names,
                layer_name=layer_name,
                apply_to_existing=bool(spec.get("apply_to_existing", False)),
                initialize_if_needed=True,
                shared_material=not bool(spec.get("separate_materials", False)),
            )
            verification = _material_application_snapshot(
                target_names,
                expected_material_id=material_id,
                expected_layer_name=layer_name,
            )
            verification = {
                **verification,
                "verified": bool(result.get("success")) and verification.get("verified", False),
                "expected_material_id": material_id,
                "expected_layer_name": layer_name,
                "missing": missing,
            }
        else:
            errors.append({"key": key, "error": "assignment needs job_id, material_id, or material_name"})
            continue

        entry = {
            "key": key,
            "object_names": _as_name_list(object_names),
            "result": result,
            "verification": verification,
        }
        if result.get("success") and verification.get("verified"):
            applied.append(entry)
        else:
            errors.append(entry)

    return {
        "success": not errors,
        "applied": applied,
        "pending": pending,
        "errors": errors,
        "partial": bool(pending),
        "time_budget_s": budget_s,
        "elapsed_s": round(time.monotonic() - started_at, 3),
    }
