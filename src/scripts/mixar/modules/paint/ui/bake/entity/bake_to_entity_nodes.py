# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Node creation and cleanup functions for entity baking."""

from mixar.config.logging_config import get_logger

import math

import bpy

from ....core.lib.lib import CAVITY, DUST, PAINT_BASE
from ....core.node.get_nodes import get_active_mat_output_node
from ....core.node.node_utils import get_node_tree_lib
from ....utils.blender_commons import simple_remove_node
from ....utils.constants import FLOW_VCOL

from ..utils.bake_common import TEMP_VCOL, recover_bake_settings

logger = get_logger(__name__)


class BakeNodes:
    """Container for bake-related nodes."""

    def __init__(self):
        self.tex = None
        self.bsdf = None
        self.src = None
        self.map_range = None
        self.geometry = None
        self.vector_math = None
        self.vector_math_1 = None
        # Position map nodes
        self.separate_xyz = None
        self.combine_xyz = None
        self.map_range_x = None
        self.map_range_y = None
        self.map_range_z = None
        # Original BSDF connection
        self.ori_bsdf = None
        self.output = None


def create_bake_nodes(mat, bprops, objs, bbox_min=None, bbox_max=None):
    """Create nodes needed for baking.

    Parameters:
        mat: Material to add nodes to
        bprops: Bake properties
        objs: List of objects being baked
        bbox_min: Bounding box minimum for position normalization
        bbox_max: Bounding box maximum for position normalization

    Returns:
        tuple: (BakeNodes instance, error message if any)
    """
    nodes = BakeNodes()

    # Create texture node
    nodes.tex = mat.node_tree.nodes.new("ShaderNodeTexImage")

    # Create BSDF node
    if bprops.type == "BEVEL_NORMAL":
        nodes.bsdf = mat.node_tree.nodes.new("ShaderNodeBsdfDiffuse")
    elif bprops.type == "BEVEL_MASK":
        nodes.geometry = mat.node_tree.nodes.new("ShaderNodeNewGeometry")
        nodes.vector_math = mat.node_tree.nodes.new("ShaderNodeVectorMath")
        nodes.vector_math.operation = "CROSS_PRODUCT"
        nodes.vector_math_1 = mat.node_tree.nodes.new("ShaderNodeVectorMath")
        nodes.vector_math_1.operation = "LENGTH"

    if not nodes.bsdf:
        nodes.bsdf = mat.node_tree.nodes.new("ShaderNodeEmission")

    # Get output node and remember original bsdf input
    nodes.output = get_active_mat_output_node(mat.node_tree)
    nodes.ori_bsdf = nodes.output.inputs[0].links[0].from_socket

    # Create source node based on bake type
    error = _create_source_node(mat, bprops, nodes, objs, bbox_min, bbox_max)
    if error:
        return nodes, error

    return nodes, ""


def _create_source_node(mat, bprops, nodes, objs, bbox_min, bbox_max):
    """Create source node based on bake type.

    Parameters:
        mat: Material
        bprops: Bake properties
        nodes: BakeNodes instance
        objs: List of objects
        bbox_min: Bounding box minimum
        bbox_max: Bounding box maximum

    Returns:
        str: Error message if any
    """
    if bprops.type == "AO":
        nodes.src = mat.node_tree.nodes.new("ShaderNodeAmbientOcclusion")
        if "Distance" in nodes.src.inputs:
            nodes.src.inputs["Distance"].default_value = bprops.ao_distance
        mat.node_tree.links.new(nodes.src.outputs["AO"], nodes.bsdf.inputs[0])
        mat.node_tree.links.new(nodes.bsdf.outputs[0], nodes.output.inputs[0])

    elif bprops.type == "POINTINESS":
        nodes.src = mat.node_tree.nodes.new("ShaderNodeNewGeometry")
        pointy = nodes.src.outputs["Pointiness"]

        if bprops.normalize:
            nodes.map_range = mat.node_tree.nodes.new("ShaderNodeMapRange")
            mat.node_tree.links.new(pointy, nodes.map_range.inputs[0])
            pointy = nodes.map_range.outputs[0]

        mat.node_tree.links.new(pointy, nodes.bsdf.inputs[0])
        mat.node_tree.links.new(nodes.bsdf.outputs[0], nodes.output.inputs[0])

    elif bprops.type == "CAVITY":
        nodes.src = mat.node_tree.nodes.new("ShaderNodeGroup")
        nodes.src.node_tree = get_node_tree_lib(CAVITY)

        if not nodes.src.node_tree:
            logger.error("Failed to load CAVITY node library!")
            return "Failed to load CAVITY node library!"

        vcol_node = nodes.src.node_tree.nodes.get("vcol")
        if vcol_node:
            vcol_node.attribute_name = TEMP_VCOL

        mat.node_tree.links.new(nodes.src.outputs[0], nodes.bsdf.inputs[0])
        mat.node_tree.links.new(nodes.bsdf.outputs[0], nodes.output.inputs[0])

    elif bprops.type == "DUST":
        nodes.src = mat.node_tree.nodes.new("ShaderNodeGroup")
        nodes.src.node_tree = get_node_tree_lib(DUST)

        if not nodes.src.node_tree:
            logger.error("Failed to load DUST node library!")
            return "Failed to load DUST node library!"

        mat.node_tree.links.new(nodes.src.outputs[0], nodes.bsdf.inputs[0])
        mat.node_tree.links.new(nodes.bsdf.outputs[0], nodes.output.inputs[0])

    elif bprops.type == "PAINT_BASE":
        nodes.src = mat.node_tree.nodes.new("ShaderNodeGroup")
        nodes.src.node_tree = get_node_tree_lib(PAINT_BASE)

        if not nodes.src.node_tree:
            logger.error("Failed to load PAINT_BASE node library!")
            return "Failed to load PAINT_BASE node library!"

        mat.node_tree.links.new(nodes.src.outputs[0], nodes.bsdf.inputs[0])
        mat.node_tree.links.new(nodes.bsdf.outputs[0], nodes.output.inputs[0])

    elif bprops.type == "BEVEL_NORMAL":
        nodes.src = mat.node_tree.nodes.new("ShaderNodeBevel")
        nodes.src.samples = bprops.bevel_samples
        nodes.src.inputs[0].default_value = bprops.bevel_radius
        mat.node_tree.links.new(nodes.src.outputs[0], nodes.bsdf.inputs["Normal"])
        mat.node_tree.links.new(nodes.bsdf.outputs[0], nodes.output.inputs[0])

    elif bprops.type == "BEVEL_MASK":
        nodes.src = mat.node_tree.nodes.new("ShaderNodeBevel")
        nodes.src.samples = bprops.bevel_samples
        nodes.src.inputs[0].default_value = bprops.bevel_radius
        mat.node_tree.links.new(nodes.geometry.outputs["Normal"], nodes.vector_math.inputs[0])
        mat.node_tree.links.new(nodes.src.outputs[0], nodes.vector_math.inputs[1])
        mat.node_tree.links.new(nodes.vector_math.outputs[0], nodes.vector_math_1.inputs[0])
        mat.node_tree.links.new(nodes.vector_math_1.outputs[1], nodes.bsdf.inputs[0])
        mat.node_tree.links.new(nodes.bsdf.outputs[0], nodes.output.inputs[0])

    elif bprops.type == "SELECTED_VERTICES":
        nodes.src = mat.node_tree.nodes.new("ShaderNodeVertexColor")
        nodes.src.layer_name = TEMP_VCOL
        mat.node_tree.links.new(nodes.src.outputs[0], nodes.bsdf.inputs[0])
        mat.node_tree.links.new(nodes.bsdf.outputs[0], nodes.output.inputs[0])

    elif bprops.type == "FLOW":
        nodes.src = mat.node_tree.nodes.new("ShaderNodeAttribute")
        nodes.src.attribute_name = FLOW_VCOL
        mat.node_tree.links.new(nodes.src.outputs[0], nodes.bsdf.inputs[0])
        mat.node_tree.links.new(nodes.bsdf.outputs[0], nodes.output.inputs[0])

    elif bprops.type == "POSITION":
        nodes.src = mat.node_tree.nodes.new("ShaderNodeNewGeometry")
        position = nodes.src.outputs["Position"]

        if bprops.position_normalize and bbox_min and bbox_max:
            nodes.separate_xyz = mat.node_tree.nodes.new("ShaderNodeSeparateXYZ")
            nodes.combine_xyz = mat.node_tree.nodes.new("ShaderNodeCombineXYZ")

            mat.node_tree.links.new(position, nodes.separate_xyz.inputs[0])

            nodes.map_range_x = mat.node_tree.nodes.new("ShaderNodeMapRange")
            nodes.map_range_y = mat.node_tree.nodes.new("ShaderNodeMapRange")
            nodes.map_range_z = mat.node_tree.nodes.new("ShaderNodeMapRange")

            # Set range from bounding box min/max to 0-1
            nodes.map_range_x.inputs[1].default_value = bbox_min[0]
            nodes.map_range_x.inputs[2].default_value = bbox_max[0]
            nodes.map_range_x.inputs[3].default_value = 0.0
            nodes.map_range_x.inputs[4].default_value = 1.0

            nodes.map_range_y.inputs[1].default_value = bbox_min[1]
            nodes.map_range_y.inputs[2].default_value = bbox_max[1]
            nodes.map_range_y.inputs[3].default_value = 0.0
            nodes.map_range_y.inputs[4].default_value = 1.0

            nodes.map_range_z.inputs[1].default_value = bbox_min[2]
            nodes.map_range_z.inputs[2].default_value = bbox_max[2]
            nodes.map_range_z.inputs[3].default_value = 0.0
            nodes.map_range_z.inputs[4].default_value = 1.0

            mat.node_tree.links.new(nodes.separate_xyz.outputs[0], nodes.map_range_x.inputs[0])
            mat.node_tree.links.new(nodes.separate_xyz.outputs[1], nodes.map_range_y.inputs[0])
            mat.node_tree.links.new(nodes.separate_xyz.outputs[2], nodes.map_range_z.inputs[0])

            mat.node_tree.links.new(nodes.map_range_x.outputs[0], nodes.combine_xyz.inputs[0])
            mat.node_tree.links.new(nodes.map_range_y.outputs[0], nodes.combine_xyz.inputs[1])
            mat.node_tree.links.new(nodes.map_range_z.outputs[0], nodes.combine_xyz.inputs[2])

            position = nodes.combine_xyz.outputs[0]

        mat.node_tree.links.new(position, nodes.bsdf.inputs[0])
        mat.node_tree.links.new(nodes.bsdf.outputs[0], nodes.output.inputs[0])

    else:
        nodes.src = None
        mat.node_tree.links.new(nodes.bsdf.outputs[0], nodes.output.inputs[0])

    return ""


def cleanup_bake_nodes(mat, nodes):
    """Remove temporary bake nodes.

    Parameters:
        mat: Material containing the nodes
        nodes: BakeNodes instance
    """
    simple_remove_node(mat.node_tree, nodes.tex)
    simple_remove_node(mat.node_tree, nodes.bsdf)
    if nodes.src:
        simple_remove_node(mat.node_tree, nodes.src)
    if nodes.geometry:
        simple_remove_node(mat.node_tree, nodes.geometry)
    if nodes.map_range:
        simple_remove_node(mat.node_tree, nodes.map_range)
    if nodes.vector_math:
        simple_remove_node(mat.node_tree, nodes.vector_math)
    if nodes.vector_math_1:
        simple_remove_node(mat.node_tree, nodes.vector_math_1)
    # Position map nodes cleanup
    if nodes.separate_xyz:
        simple_remove_node(mat.node_tree, nodes.separate_xyz)
    if nodes.combine_xyz:
        simple_remove_node(mat.node_tree, nodes.combine_xyz)
    if nodes.map_range_x:
        simple_remove_node(mat.node_tree, nodes.map_range_x)
    if nodes.map_range_y:
        simple_remove_node(mat.node_tree, nodes.map_range_y)
    if nodes.map_range_z:
        simple_remove_node(mat.node_tree, nodes.map_range_z)

    # Recover original bsdf
    if nodes.ori_bsdf and nodes.output:
        mat.node_tree.links.new(nodes.ori_bsdf, nodes.output.inputs[0])


def handle_node_creation_error(mat, nodes, book, mp):
    """Handle error during node creation by cleaning up.

    Parameters:
        mat: Material
        nodes: BakeNodes instance
        book: Bake settings book
        mp: Material properties

    Returns:
        dict: Error result dictionary
    """
    simple_remove_node(mat.node_tree, nodes.tex)
    simple_remove_node(mat.node_tree, nodes.bsdf)
    if nodes.ori_bsdf and nodes.output:
        mat.node_tree.links.new(nodes.ori_bsdf, nodes.output.inputs[0])
    recover_bake_settings(book, mp, mat=mat)
    return {}
