# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Read-only material-slot inventory for agent texturing passes.

One call answers what a texturing pass must know before it applies or edits a
finish: every mesh's slots in order (material, faces, link, whether a Mixar
Paint stack is already there and at which real-world tile size), the flat
colour of a plain material, shared-mesh and library-asset flags, and whether
the authoring UV map can carry real-scale tiling as-is. Nothing is created or
modified.
"""

from __future__ import annotations

import math

import bpy
import numpy as np

from ._common import _find_mpaint_node_for_material
from .real_scale_uv import REAL_SCALE_UV_NAME, measure_uv_health, source_uv_layer, uv_is_reusable

MAX_MATERIALS = 30
MAX_BARE = 20
DETAIL_LIMIT = 8


def _library_asset(obj) -> bool:
    current = obj
    while current is not None:
        try:
            if current.get("library_asset"):
                return True
        except Exception:
            pass
        current = current.parent
    return False


def _flat_colour(material):
    if material is None or not getattr(material, "node_tree", None):
        colour = getattr(material, "diffuse_color", None)
        return [round(float(c), 3) for c in colour[:3]] if colour is not None else None
    for node in material.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            socket = node.inputs.get("Base Color")
            if socket is not None and not socket.is_linked:
                return [round(float(c), 3) for c in socket.default_value[:3]]
    return None


def _face_counts(obj) -> np.ndarray:
    mesh = obj.data
    n_poly = len(mesh.polygons)
    slots = max(len(obj.material_slots), 1)
    if n_poly == 0:
        return np.zeros(slots, dtype=np.int64)
    values = np.empty(n_poly, dtype=np.int32)
    mesh.polygons.foreach_get("material_index", values)
    return np.bincount(np.clip(values, 0, slots - 1), minlength=slots)


def _slot_entry(index: int, slot, faces: int) -> dict:
    material = slot.material
    entry = {"index": index, "material": getattr(material, "name", None),
             "faces": int(faces), "link": str(getattr(slot, "link", "DATA"))}
    node = _find_mpaint_node_for_material(material)
    entry["has_paint_stack"] = node is not None
    if node is not None:
        entry["layers"] = len(node.node_tree.mp.layers)
        tile = material.get("mixar_tile_size_m")
        if tile:
            entry["tile_size_m"] = round(float(tile), 4)
        prompt = str(material.get("mixar_source_prompt") or "")
        if prompt:
            entry["source_prompt"] = prompt[:120]
    elif material is not None:
        colour = _flat_colour(material)
        if colour is not None:
            entry["colour"] = colour
    return entry


def _uv_entry(obj, indices) -> dict:
    mesh = obj.data
    source = source_uv_layer(mesh)
    entry = {"authoring_uv": getattr(source, "name", None),
             "real_scale_uv": REAL_SCALE_UV_NAME in mesh.uv_layers}
    if source is None:
        entry["uv_note"] = "no UV map: one is created on apply"
        return entry
    health = measure_uv_health(obj, indices)
    per_uv = health.get("meters_per_uv")
    entry["meters_per_uv"] = None if per_uv is None else round(float(per_uv), 4)
    aniso = health.get("anisotropy")
    entry["uv_stretch"] = None if aniso is None or not math.isfinite(aniso) else round(float(aniso), 3)
    entry["uv_mode_on_apply"] = "rescaled" if uv_is_reusable(health) else "box_projected"
    return entry


def _material_rows(meshes) -> tuple[list[dict], list[str]]:
    """Group every slot by material: the scene's finish map."""
    rows: dict[str, dict] = {}
    bare: list[str] = []
    for obj in meshes:
        faces = _face_counts(obj)
        if not len(obj.material_slots) or all(s.material is None for s in obj.material_slots):
            bare.append(obj.name)
        for index, slot in enumerate(obj.material_slots):
            if slot.material is None:
                continue
            entry = rows.get(slot.material.name)
            if entry is None:
                entry = _slot_entry(index, slot, 0)
                entry = {k: v for k, v in entry.items() if k not in ("index", "faces", "link")}
                entry.update({"meshes": 0, "slots": 0, "faces": 0, "examples": []})
                rows[slot.material.name] = entry
            entry["meshes"] += 1 if index == next(
                i for i, s in enumerate(obj.material_slots) if s.material == slot.material) else 0
            entry["slots"] += 1
            entry["faces"] += int(faces[index]) if index < len(faces) else 0
            if len(entry["examples"]) < 3:
                entry["examples"].append(f"{obj.name}[{index}]")
    ordered = sorted(rows.values(), key=lambda r: -r["faces"])
    return ordered, bare


def inspect_material_slots(object_names=None, material_names=None, detail_limit: int = DETAIL_LIMIT) -> dict:
    """Finish map of the scope: materials grouped with their slot counts.

    Scope: the named roots (with descendants), else every non-library mesh in
    the scene; ``material_names`` narrows it to meshes using those materials.
    Per-object slot rows (slot order, faces, link, UV readiness) are added
    when the scope has at most ``detail_limit`` meshes.
    """
    wanted_materials = {str(n) for n in (material_names or []) if str(n).strip()}
    missing: list[str] = []
    if object_names:
        meshes, seen = [], set()
        for name in object_names:
            root = bpy.data.objects.get(name)
            if root is None:
                missing.append(name)
                continue
            for obj in [root, *getattr(root, "children_recursive", [])]:
                if obj.name not in seen and getattr(obj, "type", "") == "MESH":
                    seen.add(obj.name)
                    meshes.append(obj)
    else:
        meshes = [o for o in bpy.context.scene.objects
                  if getattr(o, "type", "") == "MESH" and not _library_asset(o)]
    if wanted_materials:
        meshes = [o for o in meshes if any(getattr(s.material, "name", None) in wanted_materials
                                           for s in o.material_slots)]
    meshes.sort(key=lambda o: o.name)
    materials, bare = _material_rows(meshes)
    result = {"success": True, "mesh_count": len(meshes),
              "materials": materials[:MAX_MATERIALS], "missing_objects": missing}
    if len(materials) > MAX_MATERIALS:
        result["materials_truncated"] = len(materials) - MAX_MATERIALS
    if bare:
        result["meshes_without_material"] = bare[:MAX_BARE]
        result["meshes_without_material_count"] = len(bare)
    if len(meshes) <= detail_limit:
        rows = []
        for obj in meshes:
            faces = _face_counts(obj)
            slots = [_slot_entry(i, s, faces[i] if i < len(faces) else 0)
                     for i, s in enumerate(obj.material_slots)]
            row = {"object": obj.name, "slots": slots,
                   "dimensions_m": [round(float(d), 3) for d in obj.dimensions]}
            users = int(getattr(obj.data, "users", 1) or 1)
            if users > 1:
                row["shared_mesh_users"] = users
            if _library_asset(obj):
                row["library_asset"] = True
            indices = [s["index"] for s in slots if not wanted_materials or s["material"] in wanted_materials]
            row.update(_uv_entry(obj, indices or None))
            rows.append(row)
        result["objects"] = rows
    else:
        result["objects_note"] = "scope object_names to at most %d meshes for per-slot detail" % detail_limit
    found = {m["material"] for m in materials}
    unknown = sorted(wanted_materials - found)
    if unknown:
        result["unknown_materials"] = unknown
    return result
