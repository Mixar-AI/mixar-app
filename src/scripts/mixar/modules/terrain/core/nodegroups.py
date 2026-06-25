# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Terrain Node-Group Builders

Geometry-node + shader builders for the terrain engine. Node groups are built once
via code and cached by name in ``bpy.data.node_groups`` (get-or-create). Native app
code, so no Blender script module-whitelist applies. Ported from the backend's
create_terrain script; these become the shared engine the ``mixie.terrain_*``
operators drive.
"""

import bpy

from mixar.modules.terrain.constants import BIOMES, MASTER_TERRAIN, TERRAIN_MATERIAL


def socket_id(node_group, name):
    """Resolve a GN group INPUT socket display name -> stable identifier."""
    for it in node_group.interface.items_tree:
        if getattr(it, "item_type", "") == "SOCKET" and it.in_out == "INPUT" and it.name == name:
            return it.identifier
    return None


def build_master_terrain():
    """Get-or-create the MasterTerrain GN group (heightmap-in + procedural detail).

    Displaces a subdivided grid along Z and stores a normalized ``ter_height`` point
    attribute (0..1) for material zoning. The ``Heightmap`` Image input is optional;
    with no image the group is fully procedural (detail noise only).
    """
    ng = bpy.data.node_groups.get(MASTER_TERRAIN)
    if ng and ng.bl_idname == "GeometryNodeTree":
        return ng

    ng = bpy.data.node_groups.new(MASTER_TERRAIN, "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    iface.new_socket("Heightmap", in_out="INPUT", socket_type="NodeSocketImage")
    s = iface.new_socket("Height Scale", in_out="INPUT", socket_type="NodeSocketFloat"); s.default_value = 100.0; s.min_value = 0.0
    s = iface.new_socket("Detail", in_out="INPUT", socket_type="NodeSocketFloat"); s.default_value = 8.0; s.min_value = 0.0
    s = iface.new_socket("Detail Scale", in_out="INPUT", socket_type="NodeSocketFloat"); s.default_value = 1.5; s.min_value = 0.0
    s = iface.new_socket("Warp", in_out="INPUT", socket_type="NodeSocketFloat"); s.default_value = 0.5; s.min_value = 0.0
    s = iface.new_socket("Water Level", in_out="INPUT", socket_type="NodeSocketFloat"); s.default_value = 0.0
    s = iface.new_socket("Seed", in_out="INPUT", socket_type="NodeSocketInt"); s.default_value = 0
    iface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

    nodes, links = ng.nodes, ng.links
    gin = nodes.new("NodeGroupInput"); gin.location = (-1200, 0)
    gout = nodes.new("NodeGroupOutput"); gout.location = (1400, 0)

    # heightmap branch: sample image by the grid's UV, take luminance
    uv = nodes.new("GeometryNodeInputNamedAttribute"); uv.location = (-1000, 320)
    uv.data_type = "FLOAT_VECTOR"; uv.inputs["Name"].default_value = "UVMap"
    img = nodes.new("GeometryNodeImageTexture"); img.location = (-800, 320)
    links.new(gin.outputs["Heightmap"], img.inputs["Image"])
    links.new(uv.outputs["Attribute"], img.inputs["Vector"])
    luma = nodes.new("ShaderNodeVectorMath"); luma.location = (-560, 320)
    luma.operation = "DOT_PRODUCT"; luma.inputs[1].default_value = (0.2126, 0.7152, 0.0722)
    links.new(img.outputs["Color"], luma.inputs[0])
    hmap = nodes.new("ShaderNodeMath"); hmap.location = (-340, 320); hmap.operation = "MULTIPLY"
    links.new(luma.outputs["Value"], hmap.inputs[0])
    links.new(gin.outputs["Height Scale"], hmap.inputs[1])

    # procedural detail branch: UV*detail_scale -> fBm noise (size-independent)
    dsvec = nodes.new("ShaderNodeCombineXYZ"); dsvec.location = (-1000, -160)
    links.new(gin.outputs["Detail Scale"], dsvec.inputs["X"])
    links.new(gin.outputs["Detail Scale"], dsvec.inputs["Y"])
    uvscaled = nodes.new("ShaderNodeVectorMath"); uvscaled.location = (-820, -160); uvscaled.operation = "MULTIPLY"
    links.new(uv.outputs["Attribute"], uvscaled.inputs[0])
    links.new(dsvec.outputs["Vector"], uvscaled.inputs[1])
    seedc = nodes.new("ShaderNodeCombineXYZ"); seedc.location = (-1000, -360)
    links.new(gin.outputs["Seed"], seedc.inputs["X"])
    links.new(gin.outputs["Seed"], seedc.inputs["Y"])
    addp = nodes.new("ShaderNodeVectorMath"); addp.location = (-640, -220); addp.operation = "ADD"
    links.new(uvscaled.outputs["Vector"], addp.inputs[0])
    links.new(seedc.outputs["Vector"], addp.inputs[1])
    noise = nodes.new("ShaderNodeTexNoise"); noise.location = (-440, -200)
    noise.noise_dimensions = "3D"
    noise.inputs["Scale"].default_value = 1.0
    noise.inputs["Detail"].default_value = 9.0
    noise.inputs["Roughness"].default_value = 0.55
    links.new(addp.outputs["Vector"], noise.inputs["Vector"])
    links.new(gin.outputs["Warp"], noise.inputs["Distortion"])
    sub = nodes.new("ShaderNodeMath"); sub.location = (-340, -200); sub.operation = "SUBTRACT"; sub.inputs[1].default_value = 0.5
    links.new(noise.outputs["Fac"], sub.inputs[0])
    twox = nodes.new("ShaderNodeMath"); twox.location = (-160, -200); twox.operation = "MULTIPLY"; twox.inputs[1].default_value = 2.0
    links.new(sub.outputs["Value"], twox.inputs[0])
    dheight = nodes.new("ShaderNodeMath"); dheight.location = (20, -200); dheight.operation = "MULTIPLY"
    links.new(twox.outputs["Value"], dheight.inputs[0])
    links.new(gin.outputs["Detail"], dheight.inputs[1])

    total = nodes.new("ShaderNodeMath"); total.location = (220, 60); total.operation = "ADD"
    links.new(hmap.outputs["Value"], total.inputs[0])
    links.new(dheight.outputs["Value"], total.inputs[1])
    offc = nodes.new("ShaderNodeCombineXYZ"); offc.location = (400, 60)
    links.new(total.outputs["Value"], offc.inputs["Z"])
    setpos = nodes.new("GeometryNodeSetPosition"); setpos.location = (600, 0)
    links.new(gin.outputs["Geometry"], setpos.inputs["Geometry"])
    links.new(offc.outputs["Vector"], setpos.inputs["Offset"])

    # ter_height (0..1) from the displaced surface bounds
    bbox = nodes.new("GeometryNodeBoundBox"); bbox.location = (800, -240)
    links.new(setpos.outputs["Geometry"], bbox.inputs["Geometry"])
    smin = nodes.new("ShaderNodeSeparateXYZ"); smin.location = (980, -180); links.new(bbox.outputs["Min"], smin.inputs[0])
    smax = nodes.new("ShaderNodeSeparateXYZ"); smax.location = (980, -320); links.new(bbox.outputs["Max"], smax.inputs[0])
    pos2 = nodes.new("GeometryNodeInputPosition"); pos2.location = (800, -420)
    pz = nodes.new("ShaderNodeSeparateXYZ"); pz.location = (980, -460); links.new(pos2.outputs["Position"], pz.inputs[0])
    mrange = nodes.new("ShaderNodeMapRange"); mrange.location = (1160, -300)
    links.new(pz.outputs["Z"], mrange.inputs["Value"])
    links.new(smin.outputs["Z"], mrange.inputs["From Min"])
    links.new(smax.outputs["Z"], mrange.inputs["From Max"])
    store = nodes.new("GeometryNodeStoreNamedAttribute"); store.location = (1180, 0)
    store.data_type = "FLOAT"; store.domain = "POINT"
    store.inputs["Name"].default_value = "ter_height"
    links.new(setpos.outputs["Geometry"], store.inputs["Geometry"])
    links.new(mrange.outputs["Result"], store.inputs["Value"])
    links.new(store.outputs["Geometry"], gout.inputs["Geometry"])
    return ng


def build_terrain_material(biome):
    """Get-or-create TerrainMaterial; (re)tint zoning to `biome` (from BIOMES)."""
    cols = BIOMES.get(biome, next(iter(BIOMES.values())))
    mat = bpy.data.materials.get(TERRAIN_MATERIAL) or bpy.data.materials.new(TERRAIN_MATERIAL)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (700, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (420, 0)
    bsdf.inputs["Roughness"].default_value = 0.9
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    attr = nt.nodes.new("ShaderNodeAttribute"); attr.location = (-800, 200)
    attr.attribute_type = "GEOMETRY"; attr.attribute_name = "ter_height"
    ramp = nt.nodes.new("ShaderNodeValToRGB"); ramp.location = (-560, 200)
    nt.links.new(attr.outputs["Fac"], ramp.inputs["Fac"])
    # (low, rock, snow) ramp positions. Alpine drops the snow line so a "snowy
    # mountain" actually reads snowy (snow over the upper ~third), not just a white
    # peak cap on grey rock. Warm biomes keep snow at the very top (effectively none).
    low_p, rock_p, snow_p = {"alpine": (0.26, 0.48, 0.66)}.get(biome, (0.45, 0.80, 1.0))
    e = ramp.color_ramp.elements
    e[0].position = 0.0; e[0].color = (*cols["grass"], 1.0)
    e[1].position = snow_p; e[1].color = (*cols["snow"], 1.0)
    e.new(low_p).color = (*cols["low"], 1.0)
    e.new(rock_p).color = (*cols["rock"], 1.0)
    geo = nt.nodes.new("ShaderNodeNewGeometry"); geo.location = (-800, -220)
    dot = nt.nodes.new("ShaderNodeVectorMath"); dot.location = (-560, -220)
    dot.operation = "DOT_PRODUCT"; dot.inputs[1].default_value = (0.0, 0.0, 1.0)
    nt.links.new(geo.outputs["Normal"], dot.inputs[0])
    slope = nt.nodes.new("ShaderNodeMath"); slope.location = (-360, -220)
    slope.operation = "SUBTRACT"; slope.inputs[0].default_value = 1.0
    nt.links.new(dot.outputs["Value"], slope.inputs[1])
    smask = nt.nodes.new("ShaderNodeMapRange"); smask.location = (-160, -220)
    smask.inputs["From Min"].default_value = 0.12; smask.inputs["From Max"].default_value = 0.40
    nt.links.new(slope.outputs["Value"], smask.inputs["Value"])
    rock = nt.nodes.new("ShaderNodeRGB"); rock.location = (-160, -420)
    rock.outputs[0].default_value = (*cols["rock"], 1.0)
    mix = nt.nodes.new("ShaderNodeMixRGB"); mix.location = (120, 0)
    nt.links.new(smask.outputs["Result"], mix.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], mix.inputs["Color1"])
    nt.links.new(rock.outputs["Color"], mix.inputs["Color2"])
    nt.links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])
    return mat
