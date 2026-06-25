# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Ecological Mask Engine

The "semantic brain" of the terrain agent. Computes per-vertex ecological fields on
the terrain surface — distance-to-water (moisture), height-above-water, slope — and
stores them as FLOAT point attributes. The biome scatter reads these so vegetation
lands where it ecologically belongs (riprap at the bank toe, grass by moisture, trees
set back, etc.) instead of uniform noise. Pure numpy on the evaluated surface; ported
from the validated /tmp/bq_riparian.py prototype, generalized to an arbitrary route.
"""

import bpy
import numpy as np

# Attribute names (FLOAT, POINT domain) the BiomeScatter reads.
ATTR_DISTW = "ter_distw"        # metres to the channel/water route (lateral)
ATTR_MOISTURE = "ter_moisture"  # 0..1, high near water
ATTR_HAW = "ter_haw"            # height above water (m); negative = submerged
ATTR_SLOPE = "ter_slope"        # 0..1, 0 = flat, 1 = vertical
ATTR_UNDER = "ter_underwater"   # 1.0 if below the water level, else 0.0
MASK_ATTRS = (ATTR_DISTW, ATTR_MOISTURE, ATTR_HAW, ATTR_SLOPE, ATTR_UNDER)


def dist_to_polyline(px, py, route):
    """Min distance from each (px, py) to the polyline ``route`` = [x0,y0,x1,y1,...]."""
    pts = np.asarray(route, dtype="f8").reshape(-1, 2)
    if len(pts) == 1:
        return np.hypot(px - pts[0, 0], py - pts[0, 1])
    best = np.full(px.shape, np.inf)
    for i in range(len(pts) - 1):
        ax, ay = pts[i]
        bx, by = pts[i + 1]
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        if seg2 < 1e-9:
            d = np.hypot(px - ax, py - ay)
        else:
            t = np.clip(((px - ax) * dx + (py - ay) * dy) / seg2, 0.0, 1.0)
            d = np.hypot(px - (ax + t * dx), py - (ay + t * dy))
        best = np.minimum(best, d)
    return best


def _eval_xyz_nz(obj):
    """Evaluated (GN-displaced) vertex positions + normal.z in base-mesh vertex order.

    Terrain objects are axis-aligned at the origin, so local == world here.
    """
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    n = len(me.vertices)
    co = np.empty(n * 3, dtype="f8")
    me.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    nz = np.empty(n * 3, dtype="f8")
    me.vertices.foreach_get("normal", nz)
    nz = nz.reshape(n, 3)[:, 2]
    ev.to_mesh_clear()
    return co[:, 0], co[:, 1], co[:, 2], nz


def compute_masks(object_name, route=None, water_level=0.0, moisture_radius=14.0):
    """Compute + store the ecological masks on the terrain. Returns a result dict.

    ``route`` (flat [x0,y0,...]) is the water/channel centerline moisture radiates from;
    if omitted, falls back to a stored channel route or treats the whole surface as dry.
    """
    obj = bpy.data.objects.get(object_name)
    if not obj or obj.type != "MESH":
        return {"success": False, "error": f"Mesh not found: {object_name}"}

    if route is None:
        route = obj.get("ter_channel_route")
    xs, ys, zs, nz = _eval_xyz_nz(obj)

    if route and len(route) >= 4:
        distw = dist_to_polyline(xs, ys, route)
    else:
        distw = np.full(xs.shape, float(moisture_radius))

    moisture = np.clip(1.0 - distw / max(float(moisture_radius), 1e-3), 0.0, 1.0)
    haw = zs - float(water_level)
    slope = np.clip(1.0 - np.abs(nz), 0.0, 1.0)
    under = (zs < float(water_level)).astype("f4")

    me = obj.data
    if len(me.vertices) != len(xs):
        return {"success": False,
                "error": "evaluated vertex count != base mesh; bake the terrain (carve_channel) first"}
    for name, arr in ((ATTR_DISTW, distw), (ATTR_MOISTURE, moisture), (ATTR_HAW, haw),
                      (ATTR_SLOPE, slope), (ATTR_UNDER, under)):
        a = me.attributes.get(name) or me.attributes.new(name, "FLOAT", "POINT")
        a.data.foreach_set("value", arr.astype("f4"))
    obj["ter_water_level"] = float(water_level)
    obj.update_tag()
    bpy.context.view_layer.update()
    return {
        "success": True,
        "object": obj.name,
        "attributes": list(MASK_ATTRS),
        "moisture_radius": float(moisture_radius),
        "water_level": float(water_level),
        "stats": {
            "distw_max": round(float(distw.max()), 2),
            "haw_range": [round(float(haw.min()), 2), round(float(haw.max()), 2)],
            "moist_mean": round(float(moisture.mean()), 3),
        },
    }
