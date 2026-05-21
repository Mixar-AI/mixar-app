# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Functions for cleaning up baked outside nodes."""

from ....core.layer.layer_utils import get_root_height_channel
from ....core.node.node_utils import remove_node
from ....utils.constants import io_suffix
from ..utils.bake_operators_helper import (
    check_displacement_node,
    connect_to_original_node,
)


def cleanup_baked_outside_nodes(mtree, mp, node, mat, output_mat, context):
    """Clean up baked outside nodes when disabling the feature.

    Args:
        mtree: Material node tree.
        mp: MPaint property group.
        node: MPaint node.
        mat: Material.
        output_mat: Material output node.
        context: Blender context.
    """
    scene = context.scene
    baked_outside_frame = mtree.nodes.get(mp.baked_outside_frame)
    bake_target_outside_frame = mtree.nodes.get(mp.bake_target_outside_frame)

    # Channels
    for ch in mp.channels:
        outp = node.outputs.get(ch.name)
        connect_to_original_node(mtree, outp, ch.ori_to)
        ch.ori_to.clear()

        outp_alpha = node.outputs.get(ch.name + io_suffix["ALPHA"])
        if outp_alpha:
            connect_to_original_node(mtree, outp_alpha, ch.ori_alpha_to)
            ch.ori_alpha_to.clear()

        outp_height = node.outputs.get(ch.name + io_suffix["HEIGHT"])
        if outp_height:
            connect_to_original_node(mtree, outp_height, ch.ori_height_to)
            ch.ori_height_to.clear()

        outp_mheight = node.outputs.get(ch.name + io_suffix["MAX_HEIGHT"])
        if outp_mheight:
            connect_to_original_node(mtree, outp_mheight, ch.ori_max_height_to)
            ch.ori_max_height_to.clear()

        # Delete nodes inside frames
        if baked_outside_frame:
            remove_node(mtree, ch, "baked_outside", parent=baked_outside_frame)
            remove_node(mtree, ch, "baked_outside_vcol", parent=baked_outside_frame)
            remove_node(mtree, ch, "baked_outside_disp", parent=baked_outside_frame)
            remove_node(mtree, ch, "baked_outside_vdisp", parent=baked_outside_frame)
            remove_node(mtree, ch, "baked_outside_normal_overlay", parent=baked_outside_frame)
            remove_node(mtree, ch, "baked_outside_normal_process", parent=baked_outside_frame)
            remove_node(mtree, ch, "baked_outside_disp_process", parent=baked_outside_frame)
            remove_node(mtree, ch, "baked_outside_vdisp_process", parent=baked_outside_frame)
            remove_node(mtree, ch, "baked_outside_disp_addition", parent=baked_outside_frame)

    # Bake targets
    for bt in mp.bake_targets:
        remove_node(mtree, bt, "image_node_outside", parent=bake_target_outside_frame)

    if baked_outside_frame:
        remove_node(mtree, mp, "baked_outside_uv", parent=baked_outside_frame)
        remove_node(mtree, mp, "baked_outside_frame")

    if bake_target_outside_frame:
        remove_node(mtree, mp, "bake_target_outside_frame")

    # Shift back nodes location
    for n in mtree.nodes:
        if n.location.x > node.location.x:
            n.location.x -= mp.baked_outside_x_shift
    mp.baked_outside_x_shift = 0

    # Set back adaptive displacement node
    height_ch = get_root_height_channel(mp)
    if height_ch:
        # Recover displacement connection
        if height_ch.baked_outside_ori_disp_from_node != "":
            nod = mat.node_tree.nodes.get(height_ch.baked_outside_ori_disp_from_node)
            if nod:
                soc = nod.outputs.get(height_ch.baked_outside_ori_disp_from_socket)
                if soc and output_mat:
                    mat.node_tree.links.new(soc, output_mat.inputs["Displacement"])
            height_ch.baked_outside_ori_disp_from_node = ""
            height_ch.baked_outside_ori_disp_from_socket = ""

        if height_ch.enable_subdiv_setup:
            if height_ch.subdiv_adaptive:
                # Adaptive subdivision only works for experimental feature set
                scene.cycles.feature_set = "EXPERIMENTAL"
                scene.cycles.dicing_rate = height_ch.subdiv_global_dicing
                scene.cycles.preview_dicing_rate = height_ch.subdiv_global_dicing

            check_displacement_node(mat, node, set_one=True)
