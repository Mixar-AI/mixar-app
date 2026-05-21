# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Parallax preparation node management for paint layers.

This module handles creation and updating of parallax preparation nodes
for UVs and texture coordinates.
"""

from ...utils.common import is_parallax_enabled
from ...utils.constants import PARALLAX_PREP_SUFFIX, texcoord_lists
from ..lib.lib import (
    PARALLAX_OCCLUSION_PREP,
    PARALLAX_OCCLUSION_PREP_CAMERA,
    PARALLAX_OCCLUSION_PREP_OBJECT,
)
from ..node.node_utils import get_node_tree_lib, remove_node
from ..subtree.get_subtree import get_displacement_max_height
from ..layer.layer_utils import get_root_height_channel
from .create_nodes import new_node


def check_parallax_prep_nodes(mp, unused_uvs=[], unused_texcoords=[], baked=False):
    """
    Check and update parallax preparation nodes for UVs and texture coordinates.

    Parameters:
        mp: MPaint object containing layer data.
        unused_uvs (optional): List of UV objects that are not in use. Default: [].
        unused_texcoords (optional): List of texture coordinate types that are not in use. Default: [].
        baked (optional): If True, use baked parallax settings. Default: False.

    Returns:
        None. Nodes are created or updated directly in the tree.
    """

    tree = mp.id_data

    # Standard height channel is same as parallax channel (for now?)
    height_ch = get_root_height_channel(mp)
    if not height_ch:
        return

    if baked:
        num_of_layers = int(height_ch.baked_parallax_num_of_layers)
    else:
        num_of_layers = int(height_ch.parallax_num_of_layers)

    max_height = get_displacement_max_height(height_ch)

    # Create parallax preparations for uvs
    for uv in mp.uvs:
        if uv in unused_uvs:
            continue
        if not is_parallax_enabled(height_ch):
            remove_node(tree, uv, "parallax_prep")
        else:
            parallax_prep = tree.nodes.get(uv.parallax_prep)
            if not parallax_prep:
                parallax_prep = new_node(
                    tree,
                    uv,
                    "parallax_prep",
                    "ShaderNodeGroup",
                    uv.name + " Parallax Preparation",
                )
                parallax_prep.node_tree = get_node_tree_lib(PARALLAX_OCCLUSION_PREP)

            # parallax_prep.inputs['depth_scale'].default_value = height_ch.displacement_height_ratio
            parallax_prep.inputs["depth_scale"].default_value = (
                max_height * height_ch.parallax_height_tweak
            )
            parallax_prep.inputs["ref_plane"].default_value = (
                height_ch.parallax_ref_plane
            )
            parallax_prep.inputs["Rim Hack"].default_value = (
                1.0 if height_ch.parallax_rim_hack else 0.0
            )
            parallax_prep.inputs["Rim Hack Hardness"].default_value = (
                height_ch.parallax_rim_hack_hardness
            )
            parallax_prep.inputs["layer_depth"].default_value = 1.0 / num_of_layers

    # Create parallax preparations for texcoords other than UV
    _check_texcoord_parallax_prep(tree, height_ch, unused_texcoords, max_height, num_of_layers)


def _check_texcoord_parallax_prep(tree, height_ch, unused_texcoords, max_height, num_of_layers):
    """
    Check and update parallax preparation nodes for texture coordinates other than UV.

    Parameters:
        tree: Node tree to update.
        height_ch: Height channel containing parallax settings.
        unused_texcoords: List of texture coordinate types not in use.
        max_height: Maximum displacement height.
        num_of_layers: Number of parallax layers.

    Returns:
        None. Nodes are created or updated directly in the tree.
    """
    for tc in texcoord_lists:

        parallax_prep = tree.nodes.get(tc + PARALLAX_PREP_SUFFIX)

        if tc not in unused_texcoords and is_parallax_enabled(height_ch):

            if not parallax_prep:
                parallax_prep = tree.nodes.new("ShaderNodeGroup")
                if tc in {"Generated", "Normal", "Object"}:
                    parallax_prep.node_tree = get_node_tree_lib(
                        PARALLAX_OCCLUSION_PREP_OBJECT
                    )
                elif tc in {"Camera", "Window", "Reflection"}:
                    parallax_prep.node_tree = get_node_tree_lib(
                        PARALLAX_OCCLUSION_PREP_CAMERA
                    )
                else:
                    parallax_prep.node_tree = get_node_tree_lib(PARALLAX_OCCLUSION_PREP)
                parallax_prep.name = parallax_prep.label = tc + PARALLAX_PREP_SUFFIX

            parallax_prep.inputs["depth_scale"].default_value = (
                max_height * height_ch.parallax_height_tweak
            )
            parallax_prep.inputs["ref_plane"].default_value = (
                height_ch.parallax_ref_plane
            )
            parallax_prep.inputs["Rim Hack"].default_value = (
                1.0 if height_ch.parallax_rim_hack else 0.0
            )
            parallax_prep.inputs["Rim Hack Hardness"].default_value = (
                height_ch.parallax_rim_hack_hardness
            )
            parallax_prep.inputs["layer_depth"].default_value = 1.0 / num_of_layers

        elif parallax_prep:
            tree.nodes.remove(parallax_prep)
