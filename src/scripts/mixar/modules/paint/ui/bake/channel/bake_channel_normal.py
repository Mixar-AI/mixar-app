# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Normal channel baking functions - handles normal overlay, vector displacement, and displacement baking.

This module serves as the main entry point and re-exports all functions from helper modules
for backward compatibility.
"""

# Core imports
from ....core.layer.check_channels import check_all_channel_ios

# Re-export from helper modules for backward compatibility
from ..utils.bake_normal_overlay import bake_normal_overlay
from ..utils.bake_displacement_helpers import (
    bake_vector_displacement,
    bake_displacement,
    bake_displacement_image,
)

# Export all functions for backward compatibility
__all__ = [
    "bake_normal_overlay",
    "bake_vector_displacement",
    "bake_displacement",
    "bake_displacement_image",
    "handle_normal_channel_baking",
]


def handle_normal_channel_baking(
    tree,
    mp,
    root_ch,
    img,
    tex,
    node,
    mat,
    mat_out,
    bsdf,
    output,
    emit,
    scene,
    use_udim,
    filepath,
    use_float_for_displacement,
    target_layer=None,
    ch=None,
    ori_normal_space=None,
):
    """Handle all normal channel baking operations.

    Parameters:
        tree: Node tree
        mp: MPaint data
        root_ch: Root channel
        img: Base image
        tex: Texture node
        node: MPaint node
        mat: Material
        mat_out: Material output node
        bsdf: BSDF node
        output: Output node
        emit: Emission node
        scene: Blender scene
        use_udim (bool): Whether using UDIM
        filepath (str): Filepath
        use_float_for_displacement (bool): Use float for displacement
        target_layer: Optional target layer
        ch: Optional channel
        ori_normal_space: Original normal space

    Returns:
        tuple: (ori_disp_from_node, ori_disp_from_socket, disp_img)
    """
    ori_disp_from_node = ""
    ori_disp_from_socket = ""
    disp_img = None

    # Make sure height outputs available
    check_all_channel_ios(mp, reconnect=True, force_height_io=True)

    # Break displacement connection if displacement setup is enabled
    if root_ch.enable_subdiv_setup:
        for link in mat_out.inputs["Displacement"].links:
            ori_disp_from_node = link.from_node.name
            ori_disp_from_socket = link.from_socket.name
            mat.node_tree.links.remove(link)
            break

    if not target_layer:
        # Normal without bump
        bake_normal_overlay(
            tree,
            root_ch,
            img,
            tex,
            bsdf,
            output,
            emit,
            scene,
            use_udim,
            filepath,
            ori_normal_space,
        )

        # Vector Displacement
        bake_vector_displacement(
            tree, root_ch, img, tex, node, mat, emit, use_udim, filepath
        )

        # Displacement
        result = bake_displacement(
            tree,
            root_ch,
            img,
            tex,
            node,
            mat,
            emit,
            use_udim,
            filepath,
            use_float_for_displacement,
        )
        if result:
            disp_img, baked_disp = result
            bake_displacement_image(
                disp_img, baked_disp, tree, root_ch, tex, node, mat, emit
            )

    elif ch and ch.normal_map_type == "BUMP_MAP":
        disp_img = img
        bake_displacement_image(
            disp_img, None, tree, root_ch, tex, node, mat, emit, target_layer, ch
        )

    # Recover input outputs
    check_all_channel_ios(mp)

    return ori_disp_from_node, ori_disp_from_socket, disp_img
