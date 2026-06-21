# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent-facing helpers for Mixar Paint layer-stack workflows."""

from __future__ import annotations

import time
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


def _clean_material_name(name: str, fallback: str) -> str:
    raw = (name or fallback or "Scene Material").strip()
    safe = "".join(ch if ch.isalnum() or ch in " _-." else "_" for ch in raw)
    safe = " ".join(safe.split()) or "Scene Material"
    return safe[:80]


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
        "model": getattr(job, "model", ""),
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
            if obj.data.materials:
                obj.data.materials[0] = mat
            else:
                obj.data.materials.append(mat)
            applied.append({"object": obj.name, "material_name": mat.name})
        except Exception as exc:
            applied.append({"object": obj.name, "error": str(exc)})
    errors = [item for item in applied if item.get("error")]
    return {"success": not errors, "applied": applied, "missing": missing, "errors": errors}


def _find_mpaint_node_for_material(mat):
    if mat is None or not getattr(mat, "node_tree", None):
        return None
    for node in getattr(mat.node_tree, "nodes", []):
        tree = getattr(node, "node_tree", None)
        mp = getattr(tree, "mp", None) if tree is not None else None
        if getattr(mp, "is_mpaint_node", False):
            return node
    return None


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


def prepare_scene_materials(materials: list[dict]) -> dict:
    """Prepare placeholders and queue detailed MatGen jobs for a planned scene."""
    if not isinstance(materials, list):
        return {"success": False, "error": "materials must be a list"}

    from ..procedural_materials.matgen_queue import enqueue_matgen_job, model_for_pipeline

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
            model=model_for_pipeline("detailed"),
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
            for remaining in assignments[index:]:
                if isinstance(remaining, dict):
                    names = remaining.get("object_names") or remaining.get("objects") or []
                    pending.append(_deferred_material_assignment(remaining, _as_name_list(names), "time_budget_exhausted"))
                else:
                    errors.append({"index": index, "error": "assignment must be a dict"})
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

            target_entries = []
            target_errors = []
            deferred_names: list[str] = []
            for target_index, target in enumerate(targets):
                # Always allow at least one target to run so repeated calls make progress.
                if target_index > 0 and time.monotonic() >= deadline:
                    deferred_names = [obj.name for obj in targets[target_index:]]
                    pending_spec = {
                        **spec,
                        "material_id": material_id,
                        "material_name": material_name,
                        "layer_name": layer_name,
                    }
                    pending.append(_deferred_material_assignment(pending_spec, deferred_names, "time_budget_exhausted"))
                    break

                result = add_procedural_material_layer(
                    material_id=material_id,
                    material_name=material_name,
                    object_names=[target.name],
                    layer_name=layer_name,
                    apply_to_existing=bool(spec.get("apply_to_existing", False)),
                    initialize_if_needed=True,
                )
                verification = _material_application_snapshot(
                    [target.name],
                    expected_material_id=material_id,
                    expected_layer_name=layer_name,
                )
                target_entry = {
                    "object_names": [target.name],
                    "result": result,
                    "verification": verification,
                }
                if result.get("success") and verification.get("verified"):
                    target_entries.append(target_entry)
                else:
                    target_errors.append(target_entry)

            result = {
                "success": bool(target_entries) and not target_errors,
                "applied": [
                    item
                    for entry in target_entries
                    for item in entry.get("result", {}).get("applied", [])
                ],
                "missing": missing,
                "errors": target_errors,
                "deferred": deferred_names,
            }
            verification_objects = [
                item
                for entry in target_entries
                for item in entry.get("verification", {}).get("objects", [])
            ]
            verification = {
                "verified": bool(target_entries) and not target_errors,
                "expected_material_id": material_id,
                "expected_layer_name": layer_name,
                "objects": verification_objects,
                "missing": missing,
                "deferred": deferred_names,
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
