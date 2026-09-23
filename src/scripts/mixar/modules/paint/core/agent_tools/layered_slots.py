# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Apply a layered manifest to EXACT material slots, at real-world scale.

The legacy object-level apply built the stack inside whatever material was
ACTIVE on the first target and then wrote the result into slot 0 of every
target. On a multi-slot mesh, or with a placeholder shared by other objects,
that converted an existing datablock in place and re-skinned unrelated slots
(trace 78670a35). This path never touches an existing material:

1. validate every ``{object_name, slot_indices}`` target up front (exact mesh
   names, no child walk, indices that exist; a bare mesh may take slot 0);
2. give each target the real-scale UV map for its planned slots when the
   manifest carries a physical ``tile_size_m`` (see ``real_scale_uv``);
3. build the stack in a FRESH datablock seeded into the first planned slot;
4. assign that one datablock by pointer to exactly the planned slots, keeping
   every other slot, the slot count (a bare mesh gains its first slot) and
   every polygon's material index;
5. stamp identity (name, source prompt, tile size) on the new datablock only,
   and verify each planned slot, restoring the snapshot on any failure.
"""

from __future__ import annotations

import math

import bpy
import numpy as np

from mixar.config.logging_config import get_logger

from ._common import (
    _activate_object,
    _bsdf_group_link_status,
    _clean_material_name,
    _enabled_layers_above_base,
    _ensure_basic_uv_map,
    _find_mpaint_node_for_material,
    _restore_selection,
    _selection_snapshot,
    _sync_layer_stack_ui,
    _unique_material_datablock_name,
    _unique_node_group_name,
)
from .real_scale_uv import REAL_SCALE_UV_NAME, ensure_real_scale_uv

logger = get_logger(__name__)

MIN_TILE_SIZE_M = 0.01
MAX_TILE_SIZE_M = 100.0


def manifest_tile_size(manifest: dict):
    """The physical size one base repeat covers, or ``None`` (legacy tiling)."""
    raw = (manifest.get("scale") or {}).get("tile_size_m")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return min(max(value, MIN_TILE_SIZE_M), MAX_TILE_SIZE_M)


def normalize_slot_targets(material_slot_targets) -> tuple[dict, list[dict]]:
    """``{object_name: sorted indices}`` plus shape errors (merges duplicates)."""
    merged: dict[str, list[int]] = {}
    errors: list[dict] = []
    for item in material_slot_targets or []:
        if not isinstance(item, dict):
            errors.append({"error": "each material slot target must be an object"})
            continue
        name = str(item.get("object_name") or "").strip()
        indices = item.get("slot_indices")
        if not name or not isinstance(indices, (list, tuple)) or not indices:
            errors.append({"object": name, "error": "slot target needs object_name and slot_indices"})
            continue
        bucket = merged.setdefault(name, [])
        for index in indices:
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                errors.append({"object": name, "error": f"invalid slot index {index!r}"})
                continue
            if index not in bucket:
                bucket.append(index)
    return {name: sorted(idx) for name, idx in merged.items() if idx}, errors


def _resolve_targets(slot_map: dict) -> tuple[list, list[str], list[dict]]:
    targets, missing, errors = [], [], []
    for name, indices in slot_map.items():
        obj = bpy.data.objects.get(name)
        if obj is None:
            missing.append(name)
            continue
        if getattr(obj, "type", "") != "MESH" or getattr(obj, "data", None) is None:
            errors.append({"object": name, "error": "slot target is not a mesh"})
            continue
        slot_count = len(obj.material_slots)
        bad = [i for i in indices if not (i < slot_count or (slot_count == 0 and i == 0))]
        if bad:
            errors.append({
                "object": name, "error": "material slot index does not exist",
                "slot_indices": bad, "slot_count": slot_count,
            })
            continue
        targets.append((obj, list(indices)))
    return targets, missing, errors


def _polygon_indices(mesh) -> np.ndarray:
    values = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("material_index", values)
    return values


def _set_polygon_indices(mesh, values: np.ndarray) -> None:
    mesh.polygons.foreach_set("material_index", np.ascontiguousarray(values, dtype=np.int32))


def _snapshot(obj) -> dict:
    slots = list(obj.material_slots)
    return {
        "materials": [slot.material for slot in slots],
        "links": [str(getattr(slot, "link", "DATA")) for slot in slots],
        "data_materials": list(obj.data.materials),
        "polygon_indices": _polygon_indices(obj.data),
        "active_material_index": int(getattr(obj, "active_material_index", 0)),
    }


def _put_material(obj, index: int, material) -> int:
    """Write ``material`` into slot ``index`` honouring its link; returns the slot."""
    if len(obj.material_slots) == 0:
        obj.data.materials.append(material)
        return 0
    slot = obj.material_slots[index]
    if str(getattr(slot, "link", "DATA")) == "OBJECT":
        slot.material = material
    else:
        obj.data.materials[index] = material
    return index


def _restore(obj, snap: dict) -> None:
    """Put back every slot pointer, the slot count and each polygon's index."""
    mesh = obj.data
    while len(mesh.materials) > len(snap["data_materials"]):
        mesh.materials.pop(index=len(mesh.materials) - 1)
    for index, material in enumerate(snap["data_materials"]):
        if index < len(mesh.materials):
            mesh.materials[index] = material
    for index, material in enumerate(snap["materials"]):
        if index < len(obj.material_slots) and snap["links"][index] == "OBJECT":
            obj.material_slots[index].material = material
    _set_polygon_indices(mesh, snap["polygon_indices"])
    if len(obj.material_slots):
        obj.active_material_index = min(snap["active_material_index"], len(obj.material_slots) - 1)


def _topology_report(obj, snap: dict, planned: list[int]) -> dict:
    slots = list(obj.material_slots)
    before = len(snap["materials"])
    count_ok = len(slots) == before or (before == 0 and len(slots) == 1)
    changed = [
        i for i, material in enumerate(snap["materials"])
        if i not in planned and (i >= len(slots) or slots[i].material != material)
    ]
    polygons_ok = np.array_equal(_polygon_indices(obj.data), snap["polygon_indices"])
    return {
        "slot_topology_preserved": bool(count_ok and not changed),
        "polygon_assignments_preserved": bool(polygons_ok),
        "unplanned_slots_changed": changed,
    }


PRESEED_KEY = "mixar_agent_preseed"


def _new_material(name: str, obj=None, index: int = 0):
    """A datablock nothing else references, seeded by the caller into a slot.

    A backend apply script may already have seeded one (tagged
    ``mixar_agent_preseed``) into this very slot; adopt it rather than leave a
    second, suffixed datablock behind.
    """
    current = None
    if obj is not None and index < len(obj.material_slots):
        current = obj.material_slots[index].material
    if (current is not None and current.get(PRESEED_KEY) and int(current.users or 0) <= 1
            and _find_mpaint_node_for_material(current) is None):
        del current[PRESEED_KEY]
        return current
    material = bpy.data.materials.new(name or "Layered Material")
    try:
        material.use_nodes = True  # default on 5.x; kept for older builds
    except Exception:
        pass
    return material


def _discard(material) -> None:
    try:
        if material is not None and int(getattr(material, "users", 0) or 0) == 0:
            bpy.data.materials.remove(material)
    except Exception:
        logger.debug("Could not remove unused material", exc_info=True)


def _stamp(material, semantic_name: str, source_prompt: str, tile_size, uv_name: str) -> str:
    material.name = _unique_material_datablock_name(semantic_name, material)
    material["mixar_semantic_material_name"] = semantic_name
    material["mixar_shared_texture_set"] = True
    if source_prompt:
        material["mixar_source_prompt"] = source_prompt
    if tile_size:
        material["mixar_tile_size_m"] = float(tile_size)
        material["mixar_real_scale_uv"] = uv_name
    node = _find_mpaint_node_for_material(material)
    if node is not None and node.node_tree is not None:
        node.node_tree.name = _unique_node_group_name(material.name, node.node_tree)
    return material.name


def prepare_real_scale_uvs(targets, tile_size) -> tuple[str, dict]:
    """Metric UV for every planned region; ``("", reports)`` when any target
    cannot carry it (one shared material cannot sample a map some meshes lack).
    """
    reports: dict[str, dict] = {}
    if not tile_size:
        return "", reports
    by_mesh: dict[str, tuple] = {}
    for obj, indices in targets:
        entry = by_mesh.setdefault(obj.data.name, (obj, set()))
        entry[1].update(indices)
    for obj, indices in targets:
        _ensure_basic_uv_map(obj)
    for mesh_name, (obj, indices) in by_mesh.items():
        slot_count = len(obj.material_slots)
        report = ensure_real_scale_uv(obj, None if slot_count == 0 else sorted(indices))
        users = int(getattr(obj.data, "users", 1) or 1)
        if users > 1:
            report["shared_mesh_users"] = users
        reports[obj.name] = report
    for obj, _ in targets:
        if obj.name not in reports:
            reports[obj.name] = {"mode": "shared_mesh", "mesh": obj.data.name}
    if any(r.get("mode") == "unavailable" for r in reports.values()):
        return "", reports
    return REAL_SCALE_UV_NAME, reports


def _verify_slots(targets, built: dict, expected_base_name: str, manifest_names: set) -> dict:
    objects = []
    verified = bool(targets)
    for obj, indices in targets:
        for slot_index in indices:
            material = obj.material_slots[slot_index].material if slot_index < len(obj.material_slots) else None
            expected = built.get(obj.name)
            node = _find_mpaint_node_for_material(material)
            layers = [layer.name for layer in node.node_tree.mp.layers] if node else []
            linked, reason = _bsdf_group_link_status(material, node) if node else (None, "no paint node")
            above = [
                name for name in (
                    _enabled_layers_above_base(node.node_tree.mp, "", expected_base_name) if node else []
                )
                if name not in manifest_names
            ]
            ok = material is not None and material == expected and node is not None \
                and expected_base_name in layers and linked is not False
            verified = verified and ok
            objects.append({
                "object": obj.name,
                "slot_index": slot_index,
                "active_material": getattr(material, "name", ""),
                "material_slots": [getattr(s.material, "name", "") for s in obj.material_slots],
                "mpaint_node": getattr(node, "name", "") if node else "",
                "layers": [{"name": name} for name in layers],
                "bsdf_linked_to_group": linked,
                "bsdf_link_reason": reason,
                "layers_above_base": above,
            })
    return {"verified": verified, "expected_layer_name": expected_base_name,
            "objects": objects, "missing": []}


def apply_manifest_to_slots(
    manifest: dict,
    material_slot_targets,
    shared_material: bool = True,
    material_name: str = "",
) -> dict:
    """Build ``manifest`` into fresh material(s) assigned to exact slots."""
    from mixar.modules.paint.layered_build.builder import build_layered_material

    slot_map, shape_errors = normalize_slot_targets(material_slot_targets)
    targets, missing, errors = _resolve_targets(slot_map)
    errors = shape_errors + errors
    semantic_name = _clean_material_name(
        material_name or manifest.get("material_name") or manifest.get("source_prompt"),
        "Layered Material",
    )
    if missing or errors or not targets:
        return {"success": False, "error": "Material slot targets did not resolve.",
                "missing": missing, "errors": errors, "applied": []}

    base_layers = sorted(manifest.get("layers") or [], key=lambda l: l.get("index", 0))
    expected_base = (base_layers[0].get("name") if base_layers else "") or "PBR Base"
    source_prompt = str(manifest.get("source_prompt") or "")
    snapshots = {obj.name: _snapshot(obj) for obj, _ in targets}
    selection = _selection_snapshot()
    tile_size = manifest_tile_size(manifest)
    created: list = []
    built: dict = {}
    try:
        uv_name, uv_reports = prepare_real_scale_uvs(targets, tile_size)
        if uv_name:
            tiling, mask_tiling = 1.0 / tile_size, 1.0 / max(tile_size, 1.0)
        else:
            tiling = mask_tiling = None
        groups = [targets] if shared_material else [[t] for t in targets]
        layers_built = 0
        for group in groups:
            source_obj, source_indices = group[0]
            fresh = _new_material(semantic_name, source_obj, source_indices[0])
            created.append(fresh)
            slot = _put_material(source_obj, source_indices[0], fresh)
            source_obj.active_material_index = slot
            _activate_object(source_obj)
            result = build_layered_material(
                manifest, source_obj, uv_name=uv_name, tiling=tiling, mask_tiling=mask_tiling,
            ) or {}
            layers_built = max(layers_built, int(result.get("layers_built") or 0))
            material = source_obj.material_slots[slot].material
            if material is None or _find_mpaint_node_for_material(material) is None:
                raise RuntimeError("the build did not leave a paint stack in the planned slot")
            if material is not fresh:
                created.append(material)
            _stamp(material, semantic_name, source_prompt, tile_size if uv_name else None, uv_name)
            for obj, indices in group:
                for index in indices:
                    _put_material(obj, index, material)
                built[obj.name] = material
        applied = []
        for obj, indices in targets:
            snap = snapshots[obj.name]
            if not np.array_equal(_polygon_indices(obj.data), snap["polygon_indices"]):
                _set_polygon_indices(obj.data, snap["polygon_indices"])
            obj.active_material_index = 0 if len(snap["materials"]) == 0 else indices[0]
            entry = {
                "object": obj.name,
                "material_name": built[obj.name].name,
                "shared_material": bool(shared_material),
                "uv_created": bool(uv_reports.get(obj.name, {}).get("created")),
                "slot_indices": list(indices),
                "slot_count": len(obj.material_slots),
                "original_materials": [getattr(m, "name", None) for m in snap["materials"]],
            }
            entry.update(_topology_report(obj, snap, indices))
            if uv_name:
                entry["real_scale"] = uv_reports.get(obj.name, {})
            applied.append(entry)
        manifest_names = {str(l.get("name") or "") for l in base_layers}
        verification = _verify_slots(targets, built, expected_base, manifest_names)
        if not verification["verified"] or not all(
            a["slot_topology_preserved"] and a["polygon_assignments_preserved"] for a in applied
        ):
            raise RuntimeError("slot verification failed after the build")
    except Exception as exc:
        logger.exception("apply_manifest_to_slots failed")
        for obj, _ in targets:
            try:
                _restore(obj, snapshots[obj.name])
            except Exception:
                logger.debug("Could not restore %s", obj.name, exc_info=True)
        for material in created:
            _discard(material)
        _restore_selection(selection)
        return {"success": False, "error": str(exc), "missing": missing,
                "errors": errors, "applied": [], "semantic_material_name": semantic_name}
    _restore_selection(selection)
    for material in set(built.values()):
        node = _find_mpaint_node_for_material(material)
        if node is not None:
            _sync_layer_stack_ui(node, node.node_tree.mp)
    names = sorted({m.name for m in built.values()})
    return {
        "success": True,
        "shared_material": names[0] if shared_material and names else "",
        "semantic_material_name": semantic_name,
        "texture_set_count": len(names),
        "layers_built": layers_built,
        "manifest_material_name": manifest.get("material_name", ""),
        "applied": applied,
        "missing": missing,
        "errors": errors,
        "verification": verification,
        "real_scale": {
            "tile_size_m": tile_size if uv_name else None,
            "uv_map": uv_name or None,
            "fallback_reason": "" if uv_name or not tile_size else "a target cannot carry the real-scale UV map",
        },
    }
