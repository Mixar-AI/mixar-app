# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Geometry node tree creation functions for vector displacement maps."""

import bpy
from mathutils import Vector

from ...core.io.input_outputs.inputs import new_tree_input
from ...core.io.input_outputs.outputs import new_tree_output
from ...core.node.create_nodes import create_essential_nodes
from ...utils.constants import TREE_END, TREE_START
from .vdm_constants import GEO_TANGENT2OBJECT, GEO_VDM_LOADER


def get_tangent2object_geo_tree():
    """Get or create a geometry node tree for converting tangent space to object space.

    Returns:
        bpy.types.GeometryNodeTree: Node tree that transforms vectors from tangent to object space.
    """
    tree = bpy.data.node_groups.get(GEO_TANGENT2OBJECT)
    if not tree:
        tree = bpy.data.node_groups.new(GEO_TANGENT2OBJECT, "GeometryNodeTree")
        nodes = tree.nodes
        links = tree.links

        create_essential_nodes(tree)
        start = nodes.get(TREE_START)
        end = nodes.get(TREE_END)

        # Create IO
        new_tree_input(tree, "Vector", "NodeSocketVector")
        new_tree_input(tree, "Tangent", "NodeSocketVector")
        new_tree_input(tree, "Bitangent", "NodeSocketVector")
        new_tree_output(tree, "Vector", "NodeSocketVector")

        normal = nodes.new("GeometryNodeInputNormal")

        # Matrix nodes
        septangent = nodes.new("ShaderNodeSeparateXYZ")
        sepbitangent = nodes.new("ShaderNodeSeparateXYZ")
        sepnormal = nodes.new("ShaderNodeSeparateXYZ")

        comtangent = nodes.new("ShaderNodeCombineXYZ")
        combitangent = nodes.new("ShaderNodeCombineXYZ")
        comnormal = nodes.new("ShaderNodeCombineXYZ")

        # Dot product nodes
        dottangent = nodes.new("ShaderNodeVectorMath")
        dottangent.operation = "DOT_PRODUCT"
        dotbitangent = nodes.new("ShaderNodeVectorMath")
        dotbitangent.operation = "DOT_PRODUCT"
        dotnormal = nodes.new("ShaderNodeVectorMath")
        dotnormal.operation = "DOT_PRODUCT"

        finalvec = nodes.new("ShaderNodeCombineXYZ")

        # Node Arrangements
        loc = Vector((0, 0))

        start.location = loc
        loc.y -= 200
        normal.location = loc

        loc.y = 0
        loc.x += 200

        septangent.location = loc
        loc.y -= 200
        sepbitangent.location = loc
        loc.y -= 200
        sepnormal.location = loc

        loc.y = 0
        loc.x += 200

        comtangent.location = loc
        loc.y -= 200
        combitangent.location = loc
        loc.y -= 200
        comnormal.location = loc

        loc.y = 0
        loc.x += 200

        dottangent.location = loc
        loc.y -= 200
        dotbitangent.location = loc
        loc.y -= 200
        dotnormal.location = loc

        loc.y = 0
        loc.x += 200

        finalvec.location = loc

        loc.x += 200

        end.location = loc

        # Node Connection

        links.new(start.outputs["Tangent"], septangent.inputs[0])
        links.new(start.outputs["Bitangent"], sepbitangent.inputs[0])
        links.new(normal.outputs["Normal"], sepnormal.inputs[0])

        links.new(septangent.outputs[0], comtangent.inputs[0])
        links.new(septangent.outputs[1], combitangent.inputs[0])
        links.new(septangent.outputs[2], comnormal.inputs[0])

        links.new(sepbitangent.outputs[0], comtangent.inputs[1])
        links.new(sepbitangent.outputs[1], combitangent.inputs[1])
        links.new(sepbitangent.outputs[2], comnormal.inputs[1])

        links.new(sepnormal.outputs[0], comtangent.inputs[2])
        links.new(sepnormal.outputs[1], combitangent.inputs[2])
        links.new(sepnormal.outputs[2], comnormal.inputs[2])

        links.new(comtangent.outputs[0], dottangent.inputs[0])
        links.new(combitangent.outputs[0], dotbitangent.inputs[0])
        links.new(comnormal.outputs[0], dotnormal.inputs[0])

        links.new(start.outputs["Vector"], dottangent.inputs[1])
        links.new(start.outputs["Vector"], dotbitangent.inputs[1])
        links.new(start.outputs["Vector"], dotnormal.inputs[1])

        links.new(dottangent.outputs["Value"], finalvec.inputs[0])
        links.new(dotbitangent.outputs["Value"], finalvec.inputs[1])
        links.new(dotnormal.outputs["Value"], finalvec.inputs[2])

        links.new(finalvec.outputs[0], end.inputs[0])

    return tree


def get_vdm_loader_geotree(
    uv_name="", vdm_image=None, tangent_image=None, bitangent_image=None, intensity=1.0
):
    """Get or create a geometry node tree for loading vector displacement maps.

    Args:
        uv_name (str, optional): Name of the UV map to use. Defaults to "".
        vdm_image (bpy.types.Image, optional): Vector displacement map image. Defaults to None.
        tangent_image (bpy.types.Image, optional): Baked tangent image. Defaults to None.
        bitangent_image (bpy.types.Image, optional): Baked bitangent image. Defaults to None.
        intensity (float, optional): Displacement intensity multiplier. Defaults to 1.0.

    Returns:
        bpy.types.GeometryNodeTree: Node tree configured to load and apply VDM.
    """
    tree = bpy.data.node_groups.get(GEO_VDM_LOADER)

    if not tree:
        tree = bpy.data.node_groups.new(GEO_VDM_LOADER, "GeometryNodeTree")
        nodes = tree.nodes
        links = tree.links

        create_essential_nodes(tree)
        start = nodes.get(TREE_START)
        end = nodes.get(TREE_END)

        # Create IO
        new_tree_input(tree, "Geometry", "NodeSocketGeometry")
        new_tree_output(tree, "Geometry", "NodeSocketGeometry")

        # Create nodes
        vdm = tree.nodes.new("GeometryNodeImageTexture")
        vdm.label = "VDM"
        vdm.inputs[0].default_value = vdm_image

        tangent = tree.nodes.new("GeometryNodeImageTexture")
        tangent.label = "Tangent"
        tangent.inputs[0].default_value = tangent_image

        bitangent = tree.nodes.new("GeometryNodeImageTexture")
        bitangent.label = "Bitangent"
        bitangent.inputs[0].default_value = bitangent_image

        uv_map = tree.nodes.new("GeometryNodeInputNamedAttribute")
        uv_map.label = "UV Map"
        uv_map.data_type = "FLOAT_VECTOR"
        uv_map.inputs[0].default_value = uv_name

        tangent2object = tree.nodes.new("GeometryNodeGroup")
        tangent2object.node_tree = get_tangent2object_geo_tree()

        intensity_multiplier = tree.nodes.new("ShaderNodeVectorMath")
        intensity_multiplier.operation = "MULTIPLY"
        intensity_multiplier.inputs[1].default_value = (intensity, intensity, intensity)

        offset_capture = tree.nodes.new("GeometryNodeCaptureAttribute")
        offset_capture.label = "Offset Capture"
        offset_capture.domain = "CORNER"

        offset_capture.capture_items.new("VECTOR", "Vector")

        offset = tree.nodes.new("GeometryNodeSetPosition")
        offset.label = "Offset"

        # Node Arrangements
        loc = Vector((0, 0))

        start.location = loc
        loc.y -= 100

        vdm.location = loc
        loc.y -= 200

        tangent.location = loc
        loc.y -= 200

        bitangent.location = loc
        loc.y -= 200

        uv_map.location = loc
        loc.y = 0
        loc.x += 300

        tangent2object.location = loc
        loc.x += 200

        intensity_multiplier.location = loc
        loc.x += 200

        offset_capture.location = loc
        loc.x += 200

        offset.location = loc
        loc.x += 200

        end.location = loc

        # Node Connection

        links.new(uv_map.outputs[0], vdm.inputs[1])
        links.new(uv_map.outputs[0], tangent.inputs[1])
        links.new(uv_map.outputs[0], bitangent.inputs[1])

        links.new(vdm.outputs[0], tangent2object.inputs[0])
        links.new(tangent.outputs[0], tangent2object.inputs[1])
        links.new(bitangent.outputs[0], tangent2object.inputs[2])

        links.new(tangent2object.outputs[0], intensity_multiplier.inputs[0])

        links.new(start.outputs[0], offset_capture.inputs[0])
        links.new(intensity_multiplier.outputs[0], offset_capture.inputs[1])

        links.new(offset_capture.outputs[0], offset.inputs[0])
        links.new(offset_capture.outputs[1], offset.inputs[3])

        links.new(offset.outputs[0], end.inputs[0])

    return tree
