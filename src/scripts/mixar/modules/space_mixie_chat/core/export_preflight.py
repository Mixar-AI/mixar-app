# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Inspection and permanent repair primitives for deterministic exports."""

from __future__ import annotations

import threading
import json

import bpy

TRANSFORM_TOLERANCE = 1.0e-5
CHECK_ORDER = ("transforms", "modifiers", "packed_images", "mixar_bakes")
CHECK_LABELS = {
    "transforms": "Rotation and scale applied",
    "modifiers": "Modifiers applied",
    "packed_images": "Material images packed",
    "mixar_bakes": "Mixar Paint materials baked",
}

_cache_lock = threading.Lock()
_repair_cache: dict[tuple[str, str, str], dict] = {}


def resolve_targets(scope: str, object_names: list[str] | None = None):
    """Resolve meshes exactly once for preflight, repair, and export."""
    names = list(object_names or [])
    if scope == "named":
        missing = [name for name in names if bpy.data.objects.get(name) is None]
        if missing:
            raise ValueError("Named object(s) not found: " + ", ".join(missing))
        meshes = [bpy.data.objects[name] for name in names
                  if bpy.data.objects[name].type == 'MESH']
    elif scope == "selected":
        meshes = [obj for obj in bpy.context.selected_objects if obj.type == 'MESH']
    else:
        meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not meshes:
        raise ValueError("No mesh objects match the export target")
    return meshes


def _is_identity(values, identity) -> bool:
    return all(abs(float(value) - expected) <= TRANSFORM_TOLERANCE
               for value, expected in zip(values, identity))


def _walk_nodes(tree, visited=None):
    if tree is None:
        return
    visited = visited if visited is not None else set()
    marker = id(tree)
    if marker in visited:
        return
    visited.add(marker)
    for node in getattr(tree, "nodes", ()):
        yield node
        child = getattr(node, "node_tree", None)
        if child is not None:
            yield from _walk_nodes(child, visited)


def material_images(material):
    """Return unique images reachable through a material and nested groups."""
    images, seen = [], set()
    if not material or not getattr(material, "use_nodes", False):
        return images
    for node in _walk_nodes(getattr(material, "node_tree", None)):
        image = getattr(node, "image", None)
        if image is not None and id(image) not in seen:
            seen.add(id(image))
            images.append(image)
    return images


def active_mixar_nodes(material):
    """Find Mixar groups upstream of the active material output surface."""
    tree = getattr(material, "node_tree", None) if material else None
    if not tree:
        return []
    outputs = [node for node in tree.nodes
               if getattr(node, "type", "") == 'OUTPUT_MATERIAL'
               and getattr(node, "is_active_output", True)]
    pending, visited, found = [], set(), []
    for output in outputs:
        surface = getattr(output, "inputs", {}).get("Surface")
        pending.extend(link.from_node for link in getattr(surface, "links", ()))
    while pending:
        node = pending.pop()
        if id(node) in visited:
            continue
        visited.add(id(node))
        node_tree = getattr(node, "node_tree", None)
        if node_tree is not None and hasattr(node_tree, "mp"):
            found.append(node)
            continue
        for socket in getattr(node, "inputs", ()):
            pending.extend(link.from_node for link in getattr(socket, "links", ()))
    return found


def _mixar_reasons(obj, material) -> list[str]:
    reasons = []
    for node in active_mixar_nodes(material):
        tree, mp = node.node_tree, node.node_tree.mp
        if not len(getattr(obj.data, "uv_layers", ())):
            reasons.append(f"{material.name}: no UV map")
        try:
            from mixar.modules.paint.core.layer.check_layers import (
                is_any_layer_using_channel,
            )
            used = [ch for ch in mp.channels if is_any_layer_using_channel(ch, node)]
        except (ImportError, AttributeError):
            used = [ch for ch in mp.channels if not getattr(ch, "no_layer_using", False)]
        missing = [ch.name for ch in used
                   if not (tree.nodes.get(ch.baked) and tree.nodes.get(ch.baked).image)]
        if missing:
            reasons.append(f"{material.name}: unbaked channels: {', '.join(missing)}")
        if not mp.use_baked:
            reasons.append(f"{material.name}: baked output is disabled")
    return reasons


def inspect_mesh(obj) -> dict[str, list[str]]:
    failures = {key: [] for key in CHECK_ORDER}
    if not (_is_identity(obj.rotation_euler, (0.0, 0.0, 0.0)) and
            _is_identity(obj.scale, (1.0, 1.0, 1.0))):
        failures["transforms"].append("rotation or scale is not applied")
    ordinary = [mod.name for mod in obj.modifiers if mod.type != 'ARMATURE']
    if ordinary:
        failures["modifiers"].append("unapplied modifiers: " + ", ".join(ordinary))
    for material in obj.data.materials:
        unpacked = [image.name for image in material_images(material)
                    if getattr(image, "packed_file", None) is None]
        if unpacked:
            failures["packed_images"].append(
                f"{material.name}: unpacked images: {', '.join(unpacked)}")
        failures["mixar_bakes"].extend(_mixar_reasons(obj, material))
    return failures


def run_preflight(spec: dict) -> dict:
    meshes = resolve_targets(str(spec.get("target_scope") or "scene"),
                             list(spec.get("object_names") or []))
    checks = {key: {"label": CHECK_LABELS[key], "passed": 0, "failed": 0,
                    "failed_meshes": [], "failures": []}
              for key in CHECK_ORDER}
    armatures = 0
    for obj in meshes:
        armatures += sum(mod.type == 'ARMATURE' for mod in obj.modifiers)
        failures = inspect_mesh(obj)
        for key, reasons in failures.items():
            check = checks[key]
            if reasons:
                check["failed"] += 1
                check["failed_meshes"].append(obj.name)
                check["failures"].append({"mesh": obj.name, "reasons": reasons})
            else:
                check["passed"] += 1
    return {"success": True, "ready": all(not item["failed"] for item in checks.values()),
            "mesh_count": len(meshes), "preserved_armature_modifiers": armatures,
            "checks": checks}


def format_report_markdown(report: dict, detail_limit: int = 4) -> str:
    """Render a bounded table suitable for the backend decision interrupt."""
    lines = ["| Check | Passed | Failed | Details |",
             "|---|---:|---:|---|"]
    total = int(report.get("mesh_count", 0))
    for key in CHECK_ORDER:
        check = report.get("checks", {}).get(key, {})
        details = []
        for failure in check.get("failures", []):
            reasons = "; ".join(failure.get("reasons", []))
            details.append(f"{failure.get('mesh', '?')}: {reasons}")
        omitted = max(0, len(details) - detail_limit)
        details = details[:detail_limit]
        if omitted:
            details.append(f"+{omitted} more")
        safe_details = "<br>".join(details).replace("|", "\\|") or "—"
        lines.append(
            f"| {check.get('label', CHECK_LABELS[key])} | "
            f"{check.get('passed', 0)} / {total} | {check.get('failed', 0)} | "
            f"{safe_details} |"
        )
    return "\n".join(lines)


def _cache_key(session_id: str, request_id: str, task_id: str):
    if not session_id or not request_id or not task_id:
        raise ValueError("session_id, request_id, and task_id are required")
    return session_id, request_id, task_id


def clear_repair_cache(session_id: str | None = None) -> None:
    with _cache_lock:
        if session_id is None:
            _repair_cache.clear()
        else:
            for key in [key for key in _repair_cache if key[0] == session_id]:
                _repair_cache.pop(key, None)


def repair_export(session_id: str, request_id: str, task_id: str, spec: dict) -> dict:
    """Permanently repair targets once, then return a fresh preflight report."""
    key = _cache_key(session_id, request_id, task_id)
    with _cache_lock:
        cached = _repair_cache.get(key)
    if cached is not None:
        return cached
    meshes = resolve_targets(str(spec.get("target_scope") or "scene"),
                             list(spec.get("object_names") or []))
    target_ids = {id(obj) for obj in meshes}
    active, selected = bpy.context.view_layer.objects.active, list(bpy.context.selected_objects)
    mode = active.mode if active else 'OBJECT'
    active_slot = getattr(active, "active_material_index", 0) if active else 0
    errors = []
    bake_jobs = []
    isolated_materials = {}
    try:
        if active and mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if bpy.ops.object.select_all.poll():
            bpy.ops.object.select_all(action='DESELECT')
        for obj in meshes:
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            shared_outside = any(id(user) not in target_ids and user.data == obj.data
                                 for user in bpy.data.objects if user.type == 'MESH')
            if shared_outside:
                obj.data = obj.data.copy()
            # A material is copied only when a non-target object uses it. This
            # keeps packing/baking from changing assets outside export scope.
            for slot_index, material in enumerate(list(obj.data.materials)):
                if material is None:
                    continue
                used_outside = any(
                    id(user) not in target_ids and
                    any(slot.material == material for slot in user.material_slots)
                    for user in bpy.data.objects if user.type == 'MESH'
                )
                if used_outside:
                    original_id = id(material)
                    material = isolated_materials.get(original_id)
                    if material is None:
                        material = obj.data.materials[slot_index].copy()
                        isolated_materials[original_id] = material
                    obj.data.materials[slot_index] = material
                nodes = active_mixar_nodes(material)
                if nodes:
                    bake_jobs.append((obj, slot_index, material))
            if not (_is_identity(obj.rotation_euler, (0, 0, 0)) and
                    _is_identity(obj.scale, (1, 1, 1))):
                bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
            for modifier in list(obj.modifiers):
                if modifier.type == 'ARMATURE':
                    continue
                try:
                    bpy.ops.object.modifier_apply(modifier=modifier.name)
                except Exception as exc:
                    errors.append(f"{obj.name}/{modifier.name}: {exc}")
            for material in obj.data.materials:
                for image in material_images(material):
                    if getattr(image, "packed_file", None) is None:
                        try:
                            image.pack()
                        except Exception as exc:
                            errors.append(f"{obj.name}/{image.name}: {exc}")
            obj.select_set(False)
        baked_materials = set()
        target_names = json.dumps([obj.name for obj in meshes])
        for obj, slot_index, material in bake_jobs:
            if id(material) in baked_materials:
                continue
            baked_materials.add(id(material))
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            obj.active_material_index = slot_index
            try:
                result = bpy.ops.wm.m_bake_channels(
                    'EXEC_DEFAULT', only_active_channel=False,
                    export_target_names=target_names,
                )
                if 'FINISHED' not in result:
                    errors.append(f"{obj.name}/{material.name}: bake did not finish")
                    continue
                for image in material_images(material):
                    if getattr(image, "packed_file", None) is None:
                        image.pack()
            except Exception as exc:
                errors.append(f"{obj.name}/{material.name}: bake failed: {exc}")
            finally:
                obj.select_set(False)
        report = run_preflight(spec)
        report["repair_errors"] = errors
        report["cached"] = False
        with _cache_lock:
            _repair_cache[key] = report
        return report
    finally:
        try:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in selected:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = active
            if active:
                active.active_material_index = active_slot
                if mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode=mode)
        except Exception:
            pass
