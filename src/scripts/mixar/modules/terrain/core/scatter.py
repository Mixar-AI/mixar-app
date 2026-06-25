# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Biome Scatter Engine

Scatters Botaniq vegetation across the terrain, one geometry-nodes scatter object per
biome layer, with each layer's instance density driven by its ecological mask rule
(biomes.py) — so plants land where they belong. Reads the masks computed by masks.py,
writes a per-layer density attribute, and builds a DistributePointsOnFaces ->
InstanceOnPoints graph (ported from the validated /tmp/bq_riparian.py prototype).
"""

import bpy
import numpy as np

from mixar.modules.terrain.core import vegetation
from mixar.modules.terrain.core.biomes import BIOMES, DEFAULT_BUDGET, LAYER_BUDGET
from mixar.modules.terrain.core.masks import (
    ATTR_DISTW, ATTR_HAW, ATTR_MOISTURE, ATTR_SLOPE, ATTR_UNDER,
)

_MASK_KEYS = {"distw": ATTR_DISTW, "moisture": ATTR_MOISTURE, "haw": ATTR_HAW,
              "slope": ATTR_SLOPE, "under": ATTR_UNDER}


def _read_masks(me):
    n = len(me.vertices)
    out = {}
    for key, attr in _MASK_KEYS.items():
        a = me.attributes.get(attr)
        if a is None:
            return None
        arr = np.empty(n, dtype="f4")
        a.data.foreach_get("value", arr)
        out[key] = arr
    return out


def _build_scatter_object(name, terrain, asset, density_attr, max_density, scale, align, seed):
    """One scatter object: distribute points on the terrain weighted by `density_attr`,
    instance `asset`, with surface-aligned (align) or upright random rotation + scale."""
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nd, lk = ng.nodes, ng.links
    out = nd.new("NodeGroupOutput")

    oit = nd.new("GeometryNodeObjectInfo")
    oit.inputs["Object"].default_value = terrain
    try:
        oit.transform_space = "RELATIVE"
    except Exception:
        pass
    na = nd.new("GeometryNodeInputNamedAttribute")
    na.data_type = "FLOAT"
    na.inputs["Name"].default_value = density_attr
    mul = nd.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = float(max_density)
    lk.new(na.outputs["Attribute"], mul.inputs[0])

    dist = nd.new("GeometryNodeDistributePointsOnFaces")
    lk.new(oit.outputs["Geometry"], dist.inputs["Mesh"])
    lk.new(mul.outputs["Value"], dist.inputs["Density"])
    try:
        dist.inputs["Seed"].default_value = seed
    except Exception:
        pass

    oia = nd.new("GeometryNodeObjectInfo")
    oia.inputs["Object"].default_value = asset
    try:
        oia.inputs["As Instance"].default_value = True
    except Exception:
        pass
    iop = nd.new("GeometryNodeInstanceOnPoints")
    lk.new(dist.outputs["Points"], iop.inputs["Points"])
    lk.new(oia.outputs["Geometry"], iop.inputs["Instance"])

    if align:
        lk.new(dist.outputs["Rotation"], iop.inputs["Rotation"])
    else:
        rv = nd.new("FunctionNodeRandomValue")
        rv.data_type = "FLOAT_VECTOR"
        rv.inputs[0].default_value = (0.0, 0.0, 0.0)
        rv.inputs[1].default_value = (0.0, 0.0, 6.2832)
        try:
            rv.inputs["Seed"].default_value = seed + 11
        except Exception:
            pass
        lk.new(rv.outputs[0], iop.inputs["Rotation"])

    rs = nd.new("FunctionNodeRandomValue")
    rs.data_type = "FLOAT"
    rs.inputs[2].default_value = float(scale[0])
    rs.inputs[3].default_value = float(scale[1])
    try:
        rs.inputs["Seed"].default_value = seed + 7
    except Exception:
        pass
    lk.new(rs.outputs[1], iop.inputs["Scale"])

    lk.new(iop.outputs["Instances"], out.inputs["Geometry"])

    ob = bpy.data.objects.new(name, bpy.data.meshes.new(name + "_m"))
    ob.modifiers.new(name, "NODES").node_group = ng
    bpy.context.scene.collection.objects.link(ob)
    return ob


def scatter_biome(object_name, biome="riparian", maturity=1.0, botaniq_path=None):
    """Scatter `biome` vegetation on the terrain, density scaled by `maturity` (0..1+)."""
    terr = bpy.data.objects.get(object_name)
    if not terr or terr.type != "MESH":
        return {"success": False, "error": f"Terrain not found: {object_name}"}
    layers = BIOMES.get(biome)
    if not layers:
        return {"success": False, "error": f"Unknown biome '{biome}'. Options: {list(BIOMES)}"}
    masks = _read_masks(terr.data)
    if masks is None:
        # Auto-compute masks from the carved channel route + water level so the agent
        # can just carve -> set_water -> scatter_biome without a separate masks step.
        from mixar.modules.terrain.core.masks import compute_masks
        compute_masks(object_name, terr.get("ter_channel_route"),
                      float(terr.get("ter_water_level", 0.0)))
        masks = _read_masks(terr.data)
        if masks is None:
            return {"success": False, "error": "could not compute ecological masks"}
    if vegetation.botaniq_models_dir() is None and not botaniq_path:
        return {"success": False,
                "error": "Botaniq assets not found — set MIXAR_BOTANIQ_PATH to the Botaniq models dir"}

    me = terr.data
    area = sum(p.area for p in me.polygons) or 1.0  # terrain surface area (m²)
    created, skipped, caps = [], [], {}
    for i, layer in enumerate(layers):
        asset = vegetation.load_asset(layer["asset"], botaniq_path)
        if asset is None:
            skipped.append(layer["asset"])
            continue
        dens = layer["density"](masks) * float(maturity)
        attr_name = f"scd_{layer['id']}"
        a = me.attributes.get(attr_name) or me.attributes.new(attr_name, "FLOAT", "POINT")
        a.data.foreach_set("value", dens.astype("f4"))

        # Cap total instances so a large terrain can't explode the count and freeze the
        # viewport: expected ~ max_density * mean(density) * area; scale density to budget.
        mean_d = float(dens.mean())
        expected = layer["max_density"] * mean_d * area
        budget = LAYER_BUDGET.get(layer["id"], DEFAULT_BUDGET)
        eff_max = layer["max_density"]
        if expected > budget and expected > 1e-6:
            eff_max = layer["max_density"] * (budget / expected)
            caps[layer["id"]] = {"expected": int(expected), "capped_to": budget}

        name = f"Scatter_{biome}_{layer['id']}"
        old = bpy.data.objects.get(name)
        if old:
            bpy.data.objects.remove(old, do_unlink=True)
        ob = _build_scatter_object(name, terr, asset, attr_name, eff_max,
                                   layer["scale"], layer["align"], seed=i * 17 + 1)
        created.append(ob.name)

    terr.update_tag()
    bpy.context.view_layer.update()
    res = {"success": True, "object": terr.name, "biome": biome, "maturity": float(maturity),
           "area_m2": round(area, 1), "scatter_objects": created}
    if caps:
        res["density_capped"] = caps
    if skipped:
        res["skipped_assets"] = skipped
    return res
