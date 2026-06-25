# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Terrain Hydrology

Carves a graded channel/streambed along a route (the "correct depth" the noisy
heightmap path couldn't give) and places a still water surface. carve_channel bakes
the procedural MasterTerrain to real geometry first (you carve real verts), so tune
the base shape with create_terrain/set_inputs BEFORE carving. Ported from the
validated /tmp/bq_riparian.py prototype, generalized to an arbitrary route.
"""

import bpy
import numpy as np
from mathutils import Vector

from mixar.modules.terrain.core.masks import dist_to_polyline
from mixar.modules.terrain.core.nodegroups import MASTER_TERRAIN, build_terrain_material
from mixar.modules.terrain.constants import BIOMES


def _bake_terrain(obj):
    """Apply MasterTerrain (displaced shape -> real geometry) so we can carve verts.

    Uses new_from_object on the evaluated object (robust headless + in-app); preserves
    GN-baked attributes (ter_height) and re-attaches the material. No-op if no GN mod.
    """
    mod = next((m for m in obj.modifiers
                if m.type == "NODES" and m.node_group and m.node_group.name == MASTER_TERRAIN), None)
    if mod is None:
        return False
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    new_me = bpy.data.meshes.new_from_object(ev)
    old_me = obj.data
    mats = list(old_me.materials)
    obj.data = new_me
    obj.modifiers.clear()
    if mats and not new_me.materials:
        for m in mats:
            new_me.materials.append(m)
    return True


def carve_channel(object_name, route, width=6.0, depth=1.4, bank=4.0):
    """Carve a graded channel along `route` (flat [x0,y0,x1,y1,...]). Returns a dict
    incl. a suggested water level. Bakes the terrain first."""
    obj = bpy.data.objects.get(object_name)
    if not obj or obj.type != "MESH":
        return {"success": False, "error": f"Mesh not found: {object_name}"}
    if not route or len(route) < 4:
        return {"success": False, "error": "route needs >= 2 points: [x0,y0,x1,y1,...]"}

    baked = _bake_terrain(obj)
    me = obj.data
    n = len(me.vertices)
    co = np.empty(n * 3, dtype="f8")
    me.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)  # terrain is axis-aligned at origin: local == world

    d = dist_to_polyline(co[:, 0], co[:, 1], route)
    half = float(width) * 0.5
    # full depth within the half-width, easing to 0 over `bank` metres beyond it.
    t = np.clip((d - half) / max(float(bank), 1e-3), 0.0, 1.0)
    profile = (1.0 - t) ** 1.5
    co[:, 2] = co[:, 2] - float(depth) * profile
    me.vertices.foreach_set("co", co.reshape(-1))
    me.update()

    channel_bottom = float(co[:, 2].min())
    suggested_water = round(channel_bottom + float(depth) * 0.3, 3)
    obj["ter_channel_route"] = [float(v) for v in route]
    obj["ter_water_level"] = suggested_water
    obj.update_tag()
    bpy.context.view_layer.update()
    return {
        "success": True, "object": obj.name, "baked": baked,
        "channel_bottom": round(channel_bottom, 2),
        "suggested_water_level": suggested_water,
        "width": float(width), "depth": float(depth), "points": len(route) // 2,
    }


def set_water(object_name, level, name="Water", margin=2.0):
    """Place/resize a still water plane at world Z `level`, sized to the terrain."""
    terr = bpy.data.objects.get(object_name)
    if not terr or terr.type != "MESH":
        return {"success": False, "error": f"Terrain not found: {object_name}"}
    bb = [terr.matrix_world @ Vector(c) for c in terr.bound_box]
    xmin = min(p.x for p in bb) - margin
    xmax = max(p.x for p in bb) + margin
    ymin = min(p.y for p in bb) - margin
    ymax = max(p.y for p in bb) + margin

    water = bpy.data.objects.get(name)
    if water and water.type == "MESH":
        me = water.data
        me.clear_geometry()
    else:
        me = bpy.data.meshes.new(name)
        water = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(water)
    me.from_pydata(
        [(xmin, ymin, level), (xmax, ymin, level), (xmax, ymax, level), (xmin, ymax, level)],
        [], [(0, 1, 2, 3)],
    )
    me.update()

    mat = bpy.data.materials.get("TerrainWater") or bpy.data.materials.new("TerrainWater")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.02, 0.07, 0.10, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.05
        for k in ("Transmission Weight", "Transmission"):
            if k in bsdf.inputs:
                bsdf.inputs[k].default_value = 0.9
                break
    if not me.materials:
        me.materials.append(mat)

    terr["ter_water_level"] = float(level)
    water.update_tag()
    bpy.context.view_layer.update()
    return {"success": True, "object": water.name, "level": float(level),
            "size": [round(xmax - xmin, 1), round(ymax - ymin, 1)]}
