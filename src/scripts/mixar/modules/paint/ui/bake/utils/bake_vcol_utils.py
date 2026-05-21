# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Vertex color baking utilities - helper functions for baking to vertex colors."""

from mixar.config.logging_config import get_logger

import bpy
import numpy

logger = get_logger(__name__)

from ....core.element.create_vcol import new_vertex_color
from ....core.element.update_vcol import set_active_vertex_color
from ....core.io.utils.io_utils import create_link
from ....core.lib.lib import BAKE_NORMAL_ACTIVE_UV_300
from ....core.node.create_nodes import simple_new_mix_node
from ....core.node.get_nodes import get_active_mat_output_node
from ....core.node.node_utils import get_node_tree_lib, get_vertex_colors
from ....utils.blender_commons import simple_remove_node
from ....utils.common import get_mix_color_indices
from ....utils.constants import io_suffix


def bake_object_op(bake_type="EMIT"):
    """Execute bake operation with fallback to CPU if GPU fails.

    Args:
        bake_type (str, optional): Type of bake operation. Defaults to "EMIT".
    """
    try:
        if bake_type != "EMIT":
            bpy.ops.object.bake(type=bake_type)
        else:
            bpy.ops.object.bake()
    except Exception as e:
        scene = bpy.context.scene
        if scene.cycles.device == "GPU":
            logger.warning("GPU baking failed! Trying to use CPU...")
            scene.cycles.device = "CPU"

            if bake_type != "EMIT":
                bpy.ops.object.bake(type=bake_type)
            else:
                bpy.ops.object.bake()
        else:
            logger.error("Baking exception: %s", e)


def bake_to_vcol(
    mat,
    node,
    root_ch,
    objs,
    extra_channel=None,
    extra_multiplier=1.0,
    bake_alpha=False,
    vcol_name="",
):
    """Bake channel data to vertex colors.

    Args:
        mat: Blender material object.
        node: Node to bake from.
        root_ch: Root channel property group.
        objs (list): List of objects to bake to.
        extra_channel: Extra channel to add to bake, defaults to None.
        extra_multiplier (float, optional): Multiplier for extra channel. Defaults to 1.0.
        bake_alpha (bool, optional): Bake alpha channel separately. Defaults to False.
        vcol_name (str, optional): Name of vertex color to bake to. Defaults to "".
    """

    # Create setup nodes
    emit = mat.node_tree.nodes.new("ShaderNodeEmission")

    if root_ch.type == "NORMAL":

        norm = mat.node_tree.nodes.new("ShaderNodeGroup")
        norm.node_tree = get_node_tree_lib(BAKE_NORMAL_ACTIVE_UV_300)

    # Get output node and remember original bsdf input
    output = get_active_mat_output_node(mat.node_tree)
    ori_bsdf = output.inputs[0].links[0].from_socket

    # Connect emit to output material
    mat.node_tree.links.new(emit.outputs[0], output.inputs[0])

    # Links to bake
    rgb = node.outputs[root_ch.name]
    if root_ch.type == "NORMAL":
        rgb = create_link(mat.node_tree, rgb, norm.inputs[0])[0]

    if extra_channel:
        mul = simple_new_mix_node(mat.node_tree)
        mmixcol0, mmixcol1, mmixout = get_mix_color_indices(mul)
        mul.inputs[0].default_value = 1.0
        mul.inputs[mmixcol1].default_value = (
            extra_multiplier,
            extra_multiplier,
            extra_multiplier,
            1.0,
        )
        mul.blend_type = "MULTIPLY"

        extra_rgb = node.outputs[extra_channel.name]
        extra_rgb = create_link(mat.node_tree, extra_rgb, mul.inputs[mmixcol0])[mmixout]

        add = simple_new_mix_node(mat.node_tree)
        amixcol0, amixcol1, amixout = get_mix_color_indices(add)
        add.inputs[0].default_value = 1.0
        add.blend_type = "ADD"

        rgb = create_link(mat.node_tree, rgb, add.inputs[amixcol0])[amixout]
        create_link(mat.node_tree, extra_rgb, add.inputs[amixcol1])

    mat.node_tree.links.new(rgb, emit.inputs[0])

    # To avoid duplicate code, define the function here
    def bake_alpha_to_vcol():
        temp_vcol_alpha_name = "__temp__Mixar Paint_vertex_color_for_alpha_bake"
        for obj in objs:
            # Creates temp vertex color for baking alpha
            temp_vcol = new_vertex_color(obj, temp_vcol_alpha_name)
            set_active_vertex_color(obj, temp_vcol)
        bake_object_op()
        for obj in objs:
            vcols = get_vertex_colors(obj)
            temp_vcol = vcols.get(temp_vcol_alpha_name)
            target_vcol = vcols.get(vcol_name)

            # Speed up the process with numpy
            dim_rgba = 4
            temp_nvcol = numpy.zeros(
                len(temp_vcol.data) * dim_rgba, dtype=numpy.float32
            )
            target_nvcol = numpy.zeros(
                len(target_vcol.data) * dim_rgba, dtype=numpy.float32
            )

            temp_vcol.data.foreach_get("color", temp_nvcol)
            target_vcol.data.foreach_get("color", target_nvcol)
            temp_nvcol2D = temp_nvcol.reshape(-1, dim_rgba)
            target_nvcol2D = target_nvcol.reshape(-1, dim_rgba)

            # Moves the alpha of the temp vertex color to the target vertex color
            target_nvcol2D[:, 3] = temp_nvcol2D[:, 0]
            target_vcol.data.foreach_set("color", target_nvcol)

            # Deletes the temp vertex color and resets the active vertex color
            vcols.remove(temp_vcol)
            set_active_vertex_color(obj, target_vcol)

    # Bake!
    # When bake_alpha is True and the channel type is 'VALUE', bake the alpha channel separately.
    if bake_alpha and root_ch.type == "VALUE":
        bake_alpha_to_vcol()
    else:
        # Bake without alpha channel
        bake_object_op()

    # If bake_alpha is True and the channel type is 'RGB', Bake twice to merge Alpha channel
    if bake_alpha and root_ch.type == "RGB" and root_ch.enable_alpha:
        # Connect channel alpha channel
        alpha_outp = node.outputs.get(root_ch.name + io_suffix["ALPHA"])
        mat.node_tree.links.new(alpha_outp, emit.inputs[0])
        bake_alpha_to_vcol()

    # Remove temp nodes
    simple_remove_node(mat.node_tree, emit)
    if root_ch.type == "NORMAL":
        simple_remove_node(mat.node_tree, norm)

    if extra_channel:
        simple_remove_node(mat.node_tree, mul)
        simple_remove_node(mat.node_tree, add)

    # Recover original bsdf
    mat.node_tree.links.new(ori_bsdf, output.inputs[0])
