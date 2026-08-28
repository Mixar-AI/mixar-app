# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-part PBR material application (paper Sec. 3.5, Mixar-adapted).

Paint runs once the geometry is frozen and changes only colour/surface —
never shape (the triangle-count guard is reported so the backend can reject
a rewrite that moved geometry). One material per library entry, shared
across every part assigned to it. Honours the platform base-colour
contract: sets BOTH the Principled base color and ``diffuse_color`` (the
Workbench verification renders read only the latter), and assigns sub-part
colour blocks through ``polygon.material_index`` — the slot layout the
compiler pre-tagged at build time.
"""

from __future__ import annotations

import bpy

_TAG = "mixar_asm"


def _parse_color(value) -> tuple:
    if isinstance(value, str):
        s = value.lstrip("#")
        if len(s) == 6:
            return tuple(int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4)) + (1.0,)
        raise ValueError(f"bad hex color {value!r}")
    r, g, b = (float(c) for c in list(value)[:3])
    if max(r, g, b) > 1.0:
        r, g, b = r / 255.0, g / 255.0, b / 255.0
    return (r, g, b, 1.0)


def _library_material(entry: dict) -> object:
    """Create or update the shared material for one library entry."""
    name = f"asm_{entry['name']}"
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    color = _parse_color(entry.get("base_color") or "#B0B0B0")
    metallic = float(entry.get("metallic", 0.0))
    roughness = float(entry.get("roughness", 0.5))
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Metallic"].default_value = max(0.0, min(metallic, 1.0))
        bsdf.inputs["Roughness"].default_value = max(0.02, min(roughness, 1.0))
    # Workbench verification renders read only diffuse_color.
    mat.diffuse_color = color
    mat.metallic = max(0.0, min(metallic, 1.0))
    mat.roughness = max(0.02, min(roughness, 1.0))
    return mat


def apply_part_materials(params: dict) -> dict:
    """params:
        object_name (str)
        library (list[{name, base_color, metallic, roughness}])
        assignments (dict part -> entry name)
        block_assignments (dict part -> {block_name: entry name}) — optional;
            block slot order MUST match the compile report's ``blocks`` list
            (slot 0 is the part's base material).
        blocks (dict part -> [block names]) — the compile report's block
            order, passed back verbatim so slot indices line up.
    """
    object_name = str(params.get("object_name") or "")
    library = {e["name"]: e for e in (params.get("library") or []) if e.get("name")}
    assignments = params.get("assignments") or {}
    block_assignments = params.get("block_assignments") or {}
    blocks_order = params.get("blocks") or {}

    scene = bpy.context.scene
    parts = {
        o.get("mixar_asm_part"): o
        for o in scene.collection.all_objects
        if o.get(_TAG) == object_name and o.type == "MESH"
    }
    if not parts:
        return {"success": False,
                "error": f"no compiled parts found for '{object_name}'"}

    mats = {name: _library_material(entry) for name, entry in library.items()}
    applied = []
    missing = []
    tri_counts = {}
    for part_name, obj in parts.items():
        entry_name = assignments.get(part_name)
        base = mats.get(entry_name)
        if base is None:
            missing.append(part_name)
            continue
        # Slot 0 = base; slots 1.. = the part's colour blocks in compile order.
        slot_mats = [base]
        for block in blocks_order.get(part_name, []):
            block_entry = (block_assignments.get(part_name) or {}).get(block)
            slot_mats.append(mats.get(block_entry, base))
        mesh = obj.data
        mesh.materials.clear()
        for m in slot_mats:
            mesh.materials.append(m)
        # Faces tagged past the real slot count fall back to the base slot.
        nslots = len(slot_mats)
        for poly in mesh.polygons:
            if poly.material_index >= nslots:
                poly.material_index = 0
        tri_counts[part_name] = sum(
            max(p.loop_total - 2, 0) for p in mesh.polygons
        )
        applied.append(part_name)
    return {
        "success": True,
        "applied_objects": [parts[p].name for p in applied],
        "unassigned_parts": missing,
        "tri_counts": tri_counts,
        "materials": sorted(mats),
    }
