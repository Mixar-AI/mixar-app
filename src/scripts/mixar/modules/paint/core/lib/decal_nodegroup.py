# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Decal Process node group creation.

Creates the ~yPL Decal Process node group programmatically when it doesn't exist
in the library blend file.
"""

import bpy
from mathutils import Vector

from ..io.input_outputs.inputs import new_tree_input
from ..io.input_outputs.outputs import new_tree_output
from ..node.create_nodes import create_essential_nodes
from ..node.node_utils import create_info_nodes
from ...utils.constants import TREE_END, TREE_START
from .lib import DECAL_PROCESS


def get_decal_process_node_tree():
    """Get or create the Decal Process shader node tree.

    The Decal Process node group projects textures from a decal empty object
    onto the surface. It handles coordinate transformation and creates a
    distance-based falloff mask.

    Node Group Structure:
    - Input 0 (Vector): Object-space coordinates from TexCoord node
    - Input 1 (Distance): Maximum projection distance (decal_distance_value)
    - Input "Scale": Aspect ratio correction (set from image dimensions)
    - Output 0 (Vector): Processed UV coordinates for texture sampling
    - Output 1 (Value): Alpha/falloff mask based on distance

    Returns:
        bpy.types.ShaderNodeTree: The Decal Process node group.
    """
    tree = bpy.data.node_groups.get(DECAL_PROCESS)
    if tree:
        return tree

    # Create new node group
    tree = bpy.data.node_groups.new(DECAL_PROCESS, "ShaderNodeTree")
    nodes = tree.nodes
    links = tree.links

    # Create essential start/end nodes
    create_essential_nodes(tree)
    start = nodes.get(TREE_START)
    end = nodes.get(TREE_END)

    # ========== CREATE INPUTS ==========
    # Input 0: Vector (object-space coordinates from TexCoord node)
    new_tree_input(tree, "Vector", "NodeSocketVector")

    # Input 1: Distance (max projection distance)
    dist_input = new_tree_input(tree, "Distance", "NodeSocketFloat")
    dist_input.default_value = 0.5
    dist_input.min_value = 0.0
    dist_input.max_value = 100.0

    # Input 2: Scale (aspect ratio correction)
    scale_input = new_tree_input(tree, "Scale", "NodeSocketVector")
    scale_input.default_value = (1.0, 1.0, 1.0)

    # ========== CREATE OUTPUTS ==========
    # Output 0: Vector (processed UV coordinates)
    new_tree_output(tree, "Vector", "NodeSocketVector")

    # Output 1: Value (alpha/falloff mask)
    new_tree_output(tree, "Value", "NodeSocketFloat")

    # ========== CREATE INTERNAL NODES ==========

    # Node positions
    loc = Vector((0, 0))

    # Position start node
    start.location = loc
    loc.x += 200

    # --- Scale the input vector by aspect ratio ---
    scale_multiply = nodes.new("ShaderNodeVectorMath")
    scale_multiply.operation = "MULTIPLY"
    scale_multiply.name = "Scale Multiply"
    scale_multiply.location = loc
    loc.x += 200

    # --- Separate XYZ to get individual components ---
    separate_xyz = nodes.new("ShaderNodeSeparateXYZ")
    separate_xyz.name = "Separate XYZ"
    separate_xyz.location = loc
    loc.x += 200

    # --- Combine X and Y for UV output, offset by 0.5 to center ---
    # Add 0.5 to X
    add_x = nodes.new("ShaderNodeMath")
    add_x.operation = "ADD"
    add_x.name = "Add X 0.5"
    add_x.inputs[1].default_value = 0.5
    add_x.location = loc
    loc.y -= 150

    # Add 0.5 to Y
    add_y = nodes.new("ShaderNodeMath")
    add_y.operation = "ADD"
    add_y.name = "Add Y 0.5"
    add_y.inputs[1].default_value = 0.5
    add_y.location = loc
    loc.y += 150
    loc.x += 200

    # Combine back to vector
    combine_xyz = nodes.new("ShaderNodeCombineXYZ")
    combine_xyz.name = "Combine XYZ"
    combine_xyz.location = loc
    loc.x += 200

    # --- Calculate distance-based falloff ---
    # Use Z coordinate for distance calculation
    # Falloff = 1 - clamp(abs(Z) / Distance, 0, 1)

    # Absolute value of Z
    loc_falloff = Vector((separate_xyz.location.x + 200, -300))

    abs_z = nodes.new("ShaderNodeMath")
    abs_z.operation = "ABSOLUTE"
    abs_z.name = "Abs Z"
    abs_z.location = loc_falloff
    loc_falloff.x += 150

    # Divide by distance
    divide_dist = nodes.new("ShaderNodeMath")
    divide_dist.operation = "DIVIDE"
    divide_dist.name = "Divide Distance"
    divide_dist.location = loc_falloff
    loc_falloff.x += 150

    # Clamp to 0-1
    clamp_dist = nodes.new("ShaderNodeClamp")
    clamp_dist.name = "Clamp Distance"
    clamp_dist.clamp_type = "MINMAX"
    clamp_dist.inputs["Min"].default_value = 0.0
    clamp_dist.inputs["Max"].default_value = 1.0
    clamp_dist.location = loc_falloff
    loc_falloff.x += 150

    # Invert: 1 - clamped value
    invert = nodes.new("ShaderNodeMath")
    invert.operation = "SUBTRACT"
    invert.name = "Invert"
    invert.inputs[0].default_value = 1.0
    invert.location = loc_falloff
    loc_falloff.x += 150

    # --- Edge falloff for X and Y (clip beyond -0.5 to 0.5) ---
    # This creates the decal boundary mask

    # X edge: clamp abs(X - 0.5) to create edge falloff
    loc_edge = Vector((add_x.location.x, -500))

    # For X: check if in range [-0.5, 0.5] before offset
    # After offset of 0.5, check if in range [0, 1]
    x_less = nodes.new("ShaderNodeMath")
    x_less.operation = "LESS_THAN"
    x_less.name = "X Less Than 1"
    x_less.inputs[1].default_value = 1.0
    x_less.location = loc_edge
    loc_edge.x += 150

    x_greater = nodes.new("ShaderNodeMath")
    x_greater.operation = "GREATER_THAN"
    x_greater.name = "X Greater Than 0"
    x_greater.inputs[1].default_value = 0.0
    x_greater.location = loc_edge
    loc_edge.y -= 100
    loc_edge.x -= 150

    loc_edge.x += 300
    loc_edge.y += 50

    x_and = nodes.new("ShaderNodeMath")
    x_and.operation = "MULTIPLY"
    x_and.name = "X In Range"
    x_and.location = loc_edge
    loc_edge.x += 150

    # Same for Y
    loc_edge.y -= 200

    y_less = nodes.new("ShaderNodeMath")
    y_less.operation = "LESS_THAN"
    y_less.name = "Y Less Than 1"
    y_less.inputs[1].default_value = 1.0
    y_less.location = loc_edge
    loc_edge.x -= 150
    loc_edge.y -= 100

    y_greater = nodes.new("ShaderNodeMath")
    y_greater.operation = "GREATER_THAN"
    y_greater.name = "Y Greater Than 0"
    y_greater.inputs[1].default_value = 0.0
    y_greater.location = loc_edge
    loc_edge.x += 300
    loc_edge.y += 50

    y_and = nodes.new("ShaderNodeMath")
    y_and.operation = "MULTIPLY"
    y_and.name = "Y In Range"
    y_and.location = loc_edge
    loc_edge.x += 150

    # Combine X and Y edge masks with Z distance mask
    loc_edge.y += 100

    xy_and = nodes.new("ShaderNodeMath")
    xy_and.operation = "MULTIPLY"
    xy_and.name = "XY In Range"
    xy_and.location = loc_edge
    loc_edge.x += 150

    # Final alpha: XY mask * Z falloff
    final_alpha = nodes.new("ShaderNodeMath")
    final_alpha.operation = "MULTIPLY"
    final_alpha.name = "Final Alpha"
    final_alpha.location = loc_edge
    loc_edge.x += 150

    # Position end node
    end.location = Vector((loc.x + 200, 0))

    # ========== CREATE LINKS ==========

    # Scale input vector
    links.new(start.outputs["Vector"], scale_multiply.inputs[0])
    links.new(start.outputs["Scale"], scale_multiply.inputs[1])

    # Separate XYZ
    links.new(scale_multiply.outputs[0], separate_xyz.inputs[0])

    # Add 0.5 offset to center UVs
    links.new(separate_xyz.outputs["X"], add_x.inputs[0])
    links.new(separate_xyz.outputs["Y"], add_y.inputs[0])

    # Combine for output vector
    links.new(add_x.outputs[0], combine_xyz.inputs["X"])
    links.new(add_y.outputs[0], combine_xyz.inputs["Y"])
    links.new(separate_xyz.outputs["Z"], combine_xyz.inputs["Z"])

    # Output vector
    links.new(combine_xyz.outputs[0], end.inputs["Vector"])

    # Z distance falloff
    links.new(separate_xyz.outputs["Z"], abs_z.inputs[0])
    links.new(abs_z.outputs[0], divide_dist.inputs[0])
    links.new(start.outputs["Distance"], divide_dist.inputs[1])
    links.new(divide_dist.outputs[0], clamp_dist.inputs["Value"])
    links.new(clamp_dist.outputs[0], invert.inputs[1])

    # X edge detection
    links.new(add_x.outputs[0], x_less.inputs[0])
    links.new(add_x.outputs[0], x_greater.inputs[0])
    links.new(x_less.outputs[0], x_and.inputs[0])
    links.new(x_greater.outputs[0], x_and.inputs[1])

    # Y edge detection
    links.new(add_y.outputs[0], y_less.inputs[0])
    links.new(add_y.outputs[0], y_greater.inputs[0])
    links.new(y_less.outputs[0], y_and.inputs[0])
    links.new(y_greater.outputs[0], y_and.inputs[1])

    # Combine XY mask
    links.new(x_and.outputs[0], xy_and.inputs[0])
    links.new(y_and.outputs[0], xy_and.inputs[1])

    # Final alpha = XY mask * Z falloff
    links.new(xy_and.outputs[0], final_alpha.inputs[0])
    links.new(invert.outputs[0], final_alpha.inputs[1])

    # Output alpha
    links.new(final_alpha.outputs[0], end.inputs["Value"])

    # Create info frame
    create_info_nodes(tree)

    return tree


def ensure_decal_process_exists():
    """Ensure the Decal Process node group exists.

    Call this during addon registration or before using Decal functionality
    to guarantee the node group is available.

    Returns:
        bpy.types.ShaderNodeTree: The Decal Process node group.
    """
    return get_decal_process_node_tree()
