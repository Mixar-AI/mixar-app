# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shader node tree creation functions for vector displacement maps."""

import bpy
from mathutils import Vector

from ...core.io.input_outputs.inputs import new_tree_input
from ...core.io.input_outputs.outputs import new_tree_output
from ...core.node.create_nodes import create_essential_nodes
from ...core.node.node_utils import create_info_nodes
from ...utils.constants import TREE_END, TREE_START
from .vdm_constants import SHA_BITANGENT_CALC, SHA_OBJECT2TANGENT, SHA_PACK_VECTOR
from .vdm_utils import create_link


def get_bitangent_calc_shader_tree():
    """Get or create a shader node tree for calculating bitangent vectors.

    Returns:
        bpy.types.ShaderNodeTree: Node tree that calculates bitangent from tangent and normal.
    """
    tree = bpy.data.node_groups.get(SHA_BITANGENT_CALC)
    if not tree:
        tree = bpy.data.node_groups.new(SHA_BITANGENT_CALC, "ShaderNodeTree")
        nodes = tree.nodes
        links = tree.links

        create_essential_nodes(tree)
        start = nodes.get(TREE_START)
        end = nodes.get(TREE_END)

        # Create IO
        new_tree_input(tree, "Tangent", "NodeSocketVector")
        new_tree_input(tree, "Bitangent Sign", "NodeSocketFloat")
        new_tree_output(tree, "Bitangent", "NodeSocketVector")

        # Create nodes
        geom = nodes.new("ShaderNodeNewGeometry")
        cross = nodes.new("ShaderNodeVectorMath")
        cross.operation = "CROSS_PRODUCT"
        normalize = nodes.new("ShaderNodeVectorMath")
        normalize.operation = "NORMALIZE"
        transform = nodes.new("ShaderNodeVectorTransform")
        transform.vector_type = "VECTOR"
        transform.convert_from = "WORLD"
        transform.convert_to = "OBJECT"

        # Bitangent sign nodes
        bit_mul = nodes.new("ShaderNodeMath")
        bit_mul.operation = "MULTIPLY"
        bit_mul.inputs[1].default_value = -1.0

        bit_mix = nodes.new("ShaderNodeMixRGB")

        final_mul = nodes.new("ShaderNodeVectorMath")
        final_mul.operation = "MULTIPLY"

        # Node Arrangements
        loc = Vector((0, 0))

        start.location = loc
        loc.y -= 200
        transform.location = loc
        loc.y -= 200
        geom.location = loc

        loc.y = 0
        loc.x += 200

        cross.location = loc
        loc.y -= 200
        bit_mul.location = loc
        loc.y -= 200

        loc.y = 0
        loc.x += 200

        normalize.location = loc
        loc.y -= 200
        bit_mix.location = loc
        loc.y -= 200

        loc.y = 0
        loc.x += 200

        final_mul.location = loc

        loc.x += 200

        end.location = loc

        # Node connection
        links.new(geom.outputs["Normal"], transform.inputs[0])
        links.new(transform.outputs[0], cross.inputs[0])
        links.new(start.outputs["Tangent"], cross.inputs[1])

        links.new(cross.outputs[0], normalize.inputs[0])

        links.new(start.outputs["Bitangent Sign"], bit_mul.inputs[0])
        links.new(geom.outputs["Backfacing"], bit_mix.inputs[0])
        links.new(start.outputs["Bitangent Sign"], bit_mix.inputs[1])
        links.new(bit_mul.outputs[0], bit_mix.inputs[2])

        links.new(normalize.outputs[0], final_mul.inputs[0])
        links.new(bit_mix.outputs[0], final_mul.inputs[1])

        links.new(final_mul.outputs[0], end.inputs[0])

        # Info nodes
        create_info_nodes(tree)

    return tree


def get_pack_vector_shader_tree():
    """Get or create a shader node tree for packing vectors into 0-1 range.

    Returns:
        bpy.types.ShaderNodeTree: Node tree that normalizes and packs vector values.
    """
    tree = bpy.data.node_groups.get(SHA_PACK_VECTOR)
    if not tree:
        tree = bpy.data.node_groups.new(SHA_PACK_VECTOR, "ShaderNodeTree")
        nodes = tree.nodes
        links = tree.links

        create_essential_nodes(tree)
        start = nodes.get(TREE_START)
        end = nodes.get(TREE_END)

        # Create IO
        new_tree_input(tree, "Vector", "NodeSocketVector")
        new_tree_output(tree, "Vector", "NodeSocketVector")
        inp = new_tree_input(tree, "Max Value", "NodeSocketFloat")
        inp.default_value = 1.0

        # Create nodes
        divide = nodes.new("ShaderNodeVectorMath")
        divide.operation = "DIVIDE"
        multiply = nodes.new("ShaderNodeVectorMath")
        multiply.operation = "MULTIPLY"
        multiply.inputs[1].default_value = Vector((0.5, 0.5, 0.5))
        add = nodes.new("ShaderNodeVectorMath")
        add.operation = "ADD"
        add.inputs[1].default_value = Vector((0.5, 0.5, 0.5))

        # Node Arrangements
        loc = Vector((0, 0))

        start.location = loc
        loc.x += 200

        divide.location = loc
        loc.x += 200

        multiply.location = loc
        loc.x += 200

        add.location = loc
        loc.x += 200

        end.location = loc

        # Node connection
        vec = start.outputs[0]
        links.new(start.outputs[1], divide.inputs[1])

        vec = create_link(tree, vec, divide.inputs[0])[0]
        vec = create_link(tree, vec, multiply.inputs[0])[0]
        vec = create_link(tree, vec, add.inputs[0])[0]
        create_link(tree, vec, end.inputs[0])

        # Info nodes
        create_info_nodes(tree)

    return tree


def get_object2tangent_shader_tree():
    """Get or create a shader node tree for converting object space to tangent space.

    Returns:
        bpy.types.ShaderNodeTree: Node tree that transforms vectors from object to tangent space.
    """
    tree = bpy.data.node_groups.get(SHA_OBJECT2TANGENT)
    if not tree:
        tree = bpy.data.node_groups.new(SHA_OBJECT2TANGENT, "ShaderNodeTree")

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

        normal = nodes.new("ShaderNodeNewGeometry")
        transform = nodes.new("ShaderNodeVectorTransform")
        transform.vector_type = "VECTOR"
        transform.convert_from = "WORLD"
        transform.convert_to = "OBJECT"

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
        transform.location = loc
        loc.y -= 200
        normal.location = loc

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

        links.new(start.outputs["Vector"], dottangent.inputs[0])
        links.new(start.outputs["Vector"], dotbitangent.inputs[0])
        links.new(start.outputs["Vector"], dotnormal.inputs[0])

        links.new(start.outputs["Tangent"], dottangent.inputs[1])
        links.new(start.outputs["Bitangent"], dotbitangent.inputs[1])
        links.new(normal.outputs["Normal"], transform.inputs[0])
        links.new(transform.outputs[0], dotnormal.inputs[1])

        links.new(dottangent.outputs["Value"], finalvec.inputs[0])
        links.new(dotbitangent.outputs["Value"], finalvec.inputs[1])
        links.new(dotnormal.outputs["Value"], finalvec.inputs[2])

        links.new(finalvec.outputs[0], end.inputs[0])

        # Info nodes
        create_info_nodes(tree)

    return tree
