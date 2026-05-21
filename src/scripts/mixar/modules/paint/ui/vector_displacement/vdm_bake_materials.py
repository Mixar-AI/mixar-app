# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Material creation functions for baking tangent, bitangent, and offset maps."""

import bpy
from mathutils import Vector

from ...core.node.node_utils import create_info_nodes
from .vdm_constants import (
    BSIGN_ATTR,
    MAT_BITANGENT_BAKE,
    MAT_OFFSET_TANGENT_SPACE,
    MAT_TANGENT_BAKE,
    OFFSET_ATTR,
)
from .vdm_shader_trees import (
    get_bitangent_calc_shader_tree,
    get_object2tangent_shader_tree,
    get_pack_vector_shader_tree,
)


def get_tangent_bake_mat(uv_name="", target_image=None):
    """Get or create a material for baking tangent vectors.

    Args:
        uv_name (str, optional): Name of the UV map to use. Defaults to "".
        target_image (bpy.types.Image, optional): Image to bake to. Defaults to None.

    Returns:
        bpy.types.Material: Material configured for tangent baking.
    """
    mat = bpy.data.materials.get(MAT_TANGENT_BAKE)
    if not mat:
        mat = bpy.data.materials.new(MAT_TANGENT_BAKE)
        mat.use_nodes = True

        tree = mat.node_tree
        nodes = tree.nodes
        links = tree.links

        # Remove principled
        prin = [n for n in nodes if n.type == "BSDF_PRINCIPLED"]
        if prin:
            nodes.remove(prin[0])

        # Create nodes
        emission = nodes.new("ShaderNodeEmission")
        emission.name = emission.label = "Emission"

        tangent = nodes.new("ShaderNodeTangent")
        tangent.name = tangent.label = "Tangent"
        tangent.direction_type = "UV_MAP"

        transform = nodes.new("ShaderNodeVectorTransform")
        transform.name = transform.label = "World to Object"
        transform.vector_type = "VECTOR"
        transform.convert_from = "WORLD"
        transform.convert_to = "OBJECT"

        bake_target = nodes.new("ShaderNodeTexImage")
        bake_target.name = bake_target.label = "Bake Target"
        nodes.active = bake_target

        end = nodes.get("Material Output")

        # Node Arrangements
        loc = Vector((0, 0))

        tangent.location = loc
        loc.y -= 200

        bake_target.location = loc

        loc.y = 0
        loc.x += 200

        transform.location = loc
        loc.x += 200

        emission.location = loc
        loc.x += 200

        end.location = loc

        # Node Connections
        links.new(tangent.outputs[0], transform.inputs[0])
        links.new(transform.outputs[0], emission.inputs[0])
        links.new(emission.outputs[0], end.inputs[0])

        # Info nodes
        create_info_nodes(tree)

    bake_target = mat.node_tree.nodes.get("Bake Target")
    bake_target.image = target_image

    tangent = mat.node_tree.nodes.get("Tangent")
    tangent.uv_map = uv_name

    return mat


def get_bitangent_bake_mat(uv_name="", target_image=None):
    """Get or create a material for baking bitangent vectors.

    Args:
        uv_name (str, optional): Name of the UV map to use. Defaults to "".
        target_image (bpy.types.Image, optional): Image to bake to. Defaults to None.

    Returns:
        bpy.types.Material: Material configured for bitangent baking.
    """
    mat = bpy.data.materials.get(MAT_BITANGENT_BAKE)
    if not mat:
        mat = bpy.data.materials.new(MAT_BITANGENT_BAKE)
        mat.use_nodes = True

        tree = mat.node_tree
        nodes = tree.nodes
        links = tree.links

        # Remove principled
        prin = [n for n in nodes if n.type == "BSDF_PRINCIPLED"]
        if prin:
            nodes.remove(prin[0])

        # Create nodes
        emission = nodes.new("ShaderNodeEmission")
        emission.name = emission.label = "Emission"

        tangent = nodes.new("ShaderNodeTangent")
        tangent.name = tangent.label = "Tangent"
        tangent.direction_type = "UV_MAP"

        tangent_transform = nodes.new("ShaderNodeVectorTransform")
        tangent_transform.name = tangent_transform.label = "Tangent World to Object"
        tangent_transform.vector_type = "VECTOR"
        tangent_transform.convert_from = "WORLD"
        tangent_transform.convert_to = "OBJECT"

        bsign = nodes.new("ShaderNodeAttribute")
        bsign.attribute_name = BSIGN_ATTR
        bsign.name = bsign.label = "Bitangent Sign"

        bcalc = nodes.new("ShaderNodeGroup")
        bcalc.node_tree = get_bitangent_calc_shader_tree()
        bcalc.name = bcalc.label = "Bitangent Calculation"

        bake_target = nodes.new("ShaderNodeTexImage")
        bake_target.name = bake_target.label = "Bake Target"
        nodes.active = bake_target

        end = nodes.get("Material Output")

        # Node Arrangements
        loc = Vector((0, 0))

        bcalc.location = loc
        loc.y -= 200

        bsign.location = loc
        loc.y -= 200

        tangent_transform.location = loc
        loc.y -= 200

        tangent.location = loc
        loc.y -= 200

        loc.y = 0
        loc.x += 200

        emission.location = loc
        loc.y -= 200

        bake_target.location = loc

        loc.y = 0
        loc.x += 200

        end.location = loc

        # Node Connections
        links.new(tangent.outputs[0], tangent_transform.inputs[0])
        links.new(tangent_transform.outputs[0], bcalc.inputs["Tangent"])
        links.new(bsign.outputs["Fac"], bcalc.inputs["Bitangent Sign"])
        links.new(bcalc.outputs[0], emission.inputs[0])
        links.new(emission.outputs[0], end.inputs[0])

        # Info nodes
        create_info_nodes(tree)

    bake_target = mat.node_tree.nodes.get("Bake Target")
    bake_target.image = target_image

    tangent = mat.node_tree.nodes.get("Tangent")
    tangent.uv_map = uv_name

    return mat


def get_offset_bake_mat(uv_name="", target_image=None, bitangent_image=None):
    """Get or create a material for baking offset in tangent space.

    Args:
        uv_name (str, optional): Name of the UV map to use. Defaults to "".
        target_image (bpy.types.Image, optional): Image to bake to. Defaults to None.
        bitangent_image (bpy.types.Image, optional): Baked bitangent image. Defaults to None.

    Returns:
        bpy.types.Material: Material configured for offset baking in tangent space.
    """
    mat = bpy.data.materials.get(MAT_OFFSET_TANGENT_SPACE)
    if not mat:
        mat = bpy.data.materials.new(MAT_OFFSET_TANGENT_SPACE)
        mat.use_nodes = True

        tree = mat.node_tree
        nodes = tree.nodes
        links = tree.links

        # Remove principled
        prin = [n for n in nodes if n.type == "BSDF_PRINCIPLED"]
        if prin:
            nodes.remove(prin[0])

        # Create nodes
        emission = nodes.new("ShaderNodeEmission")
        emission.name = emission.label = "Emission"

        tangent = nodes.new("ShaderNodeTangent")
        tangent.direction_type = "UV_MAP"
        tangent.name = tangent.label = "Tangent"

        tangent_transform = nodes.new("ShaderNodeVectorTransform")
        tangent_transform.vector_type = "VECTOR"
        tangent_transform.convert_from = "WORLD"
        tangent_transform.convert_to = "OBJECT"
        tangent_transform.name = tangent_transform.label = "Tangent Transform"

        offset = nodes.new("ShaderNodeAttribute")
        offset.attribute_name = OFFSET_ATTR
        offset.name = offset.label = "Offset"

        # For baked bitangent
        bitangent = nodes.new("ShaderNodeTexImage")
        bitangent.name = bitangent.label = "Bitangent"
        bitangent.image = bitangent_image
        bitangent_uv = nodes.new("ShaderNodeUVMap")
        bitangent_uv.name = bitangent_uv.label = "Bitangent UV"

        object2tangent = nodes.new("ShaderNodeGroup")
        object2tangent.node_tree = get_object2tangent_shader_tree()
        object2tangent.name = object2tangent.label = "Object to Tangent"

        pack_vector = nodes.new("ShaderNodeGroup")
        pack_vector.node_tree = get_pack_vector_shader_tree()
        pack_vector.name = pack_vector.label = "Pack Vector"
        pack_vector.mute = True

        bake_target = nodes.new("ShaderNodeTexImage")
        bake_target.name = bake_target.label = "Bake Target"
        nodes.active = bake_target

        end = nodes.get("Material Output")

        # Node Arrangements
        loc = Vector((0, 0))

        offset.location = loc
        loc.y -= 200

        tangent_transform.location = loc
        loc.y -= 200

        tangent.location = loc
        loc.y -= 200

        bitangent.location = loc
        loc.y -= 200

        bitangent_uv.location = loc
        loc.y -= 200

        loc.y = 0
        loc.x += 200

        object2tangent.location = loc

        loc.y = 0
        loc.x += 200

        pack_vector.location = loc

        loc.y = 0
        loc.x += 200

        emission.location = loc
        loc.y -= 200

        bake_target.location = loc

        loc.y = 0
        loc.x += 200

        end.location = loc

        # Node Connections
        links.new(offset.outputs["Vector"], object2tangent.inputs["Vector"])
        links.new(tangent.outputs["Tangent"], tangent_transform.inputs[0])
        links.new(tangent_transform.outputs[0], object2tangent.inputs["Tangent"])
        links.new(bitangent_uv.outputs[0], bitangent.inputs["Vector"])
        links.new(bitangent.outputs[0], object2tangent.inputs["Bitangent"])

        links.new(object2tangent.outputs["Vector"], pack_vector.inputs["Vector"])
        links.new(pack_vector.outputs["Vector"], emission.inputs[0])
        links.new(emission.outputs[0], end.inputs[0])

    tangent = mat.node_tree.nodes.get("Tangent")
    tangent.uv_map = uv_name

    bitangent_uv = mat.node_tree.nodes.get("Bitangent UV")
    bitangent_uv.uv_map = uv_name

    bake_target = mat.node_tree.nodes.get("Bake Target")
    bake_target.image = target_image

    bitangent = mat.node_tree.nodes.get("Bitangent")
    bitangent.image = bitangent_image

    return mat
