# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Terrain Core Logic

Pure bpy functions (no operator/UI deps) so they're unit-testable with the root
conftest bpy stubs. The mixie.terrain_* operators are thin wrappers over these; the
heavy node-graph construction lives in nodegroups.py and the tunables in constants.py.
"""

import bpy

from mixar.modules.terrain.constants import (
    BIOMES,
    INPUT_NAMES,
    INPUT_PAIRS,
    MASTER_TERRAIN,
    PRESETS,
    TERRAIN_MATERIAL,
)
from mixar.modules.terrain.core.nodegroups import (
    build_master_terrain,
    build_terrain_material,
    socket_id,
)


def _make_grid(name, size, resolution):
    """Subdivided grid with a 0..1 UVMap (for heightmap sampling)."""
    area = next((a for w in bpy.context.window_manager.windows if w.screen
                 for a in w.screen.areas if a.type == "VIEW_3D"), None)
    kw = dict(x_subdivisions=resolution, y_subdivisions=resolution, size=size, location=(0, 0, 0))
    if area:
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        with bpy.context.temp_override(area=area, region=region):
            bpy.ops.mesh.primitive_grid_add(**kw)
    else:
        bpy.ops.mesh.primitive_grid_add(**kw)
    obj = bpy.context.active_object
    obj.name = name
    return obj


def _terrain_modifier(obj):
    return next((m for m in obj.modifiers
                 if m.type == "NODES" and m.node_group and m.node_group.name == MASTER_TERRAIN), None)


def create_terrain(size=200.0, resolution=256, preset="mountains", name="Terrain"):
    """Create-or-reuse a terrain grid driven by MasterTerrain. Returns a result dict."""
    size = float(size)
    resolution = max(2, min(int(resolution), 1024))
    preset_key = (preset or "mountains").lower()
    pv = PRESETS.get(preset_key, PRESETS["mountains"])

    ng = build_master_terrain()
    mat = build_terrain_material(pv["biome"])

    existing = bpy.data.objects.get(name)
    created = existing is None
    obj = existing if existing else _make_grid(name, size, resolution)

    mod = _terrain_modifier(obj)
    mod_created = mod is None
    if mod_created:
        mod = obj.modifiers.new(MASTER_TERRAIN, "NODES")
        mod.node_group = ng

    # Apply preset inputs ONLY on first creation (re-calling must not clobber tuning).
    inputs_reset = created or mod_created
    if inputs_reset:
        for disp, key in INPUT_PAIRS:
            sid = socket_id(ng, disp)
            if sid is not None:
                mod[sid] = pv[key]

    if TERRAIN_MATERIAL not in [ms.name for ms in obj.data.materials]:
        obj.data.materials.append(mat)
    obj.update_tag()
    bpy.context.view_layer.update()

    current = {}
    for disp, _k in INPUT_PAIRS:
        sid = socket_id(ng, disp)
        if sid is not None:
            try:
                v = mod[sid]
                current[disp] = int(v) if disp == "Seed" else round(float(v), 4)
            except Exception:
                current[disp] = mod[sid]

    res = {
        "success": True,
        "created_objects": [obj.name] if created else [],
        "modified_objects": [obj.name],
        "node_group": ng.name, "material": mat.name,
        "preset": preset_key, "biome": pv["biome"],
        "size": size, "resolution": resolution,
        "inputs_reset_to_preset": inputs_reset, "inputs": current,
    }
    if not inputs_reset:
        res["note"] = "Terrain already existed — inputs preserved. Use terrain_set_inputs to retune."
    return res


def set_inputs(object_name, inputs):
    """Tune MasterTerrain inputs non-destructively. Returns a result dict."""
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return {"success": False, "error": f"Object not found: {object_name}"}
    mod = _terrain_modifier(obj)
    if not mod:
        return {"success": False, "error": f"'{obj.name}' has no MasterTerrain modifier"}
    applied, skipped = {}, []
    for raw_key, value in (inputs or {}).items():
        disp = INPUT_NAMES.get(str(raw_key).lower().replace(" ", "_"), raw_key)
        sid = socket_id(mod.node_group, disp)
        if sid is None:
            skipped.append(raw_key); continue
        try:
            mod[sid] = value; applied[disp] = value
        except Exception as e:
            skipped.append(f"{raw_key}: {e}")
    obj.update_tag(); bpy.context.view_layer.update()
    out = {"success": True, "modified_objects": [obj.name], "applied": applied}
    if skipped:
        out["skipped"] = skipped
    return out


def set_material(object_name, biome):
    """Re-tint the TerrainMaterial zoning to a biome. Returns a result dict."""
    biome = (biome or "alpine").lower()
    if biome not in BIOMES:
        return {"success": False, "error": f"Unknown biome '{biome}'. Options: {list(BIOMES)}"}
    if not bpy.data.materials.get(TERRAIN_MATERIAL):
        return {"success": False, "error": "TerrainMaterial not found — run terrain_create first"}
    mat = build_terrain_material(biome)
    return {"success": True, "material": mat.name, "biome": biome}
