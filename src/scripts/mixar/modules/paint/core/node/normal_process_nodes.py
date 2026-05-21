# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Normal process node operations for normal channel handling.

This module contains functions for checking and creating normal-related nodes
including normal map process, bump to normal conversion, and normal flip nodes.
"""

from ...utils.common import get_write_height, is_parallax_enabled
from ...utils.math_utils import get_fine_bump_distance
from ..lib.lib import *
from ..node.create_nodes import check_new_node, replace_new_node
from ..node.node_utils import remove_node
from ..subtree.get_subtree import get_displacement_max_height


def get_normal_process_lib_name(layer, root_ch, ch):
    """
    Determine the library name for normal process node.

    Parameters:
        layer: Layer object containing the channel.
        root_ch: Root channel object.
        ch: Channel to get lib name for.

    Returns:
        String with the library name, or empty string if no normal process needed.
    """
    lib_name = ""

    if layer.type == "GROUP":
        if root_ch.enable_smooth_bump:
            lib_name = GROUP_BUMP_2_NORMAL_SMOOTH
        else:
            lib_name = GROUP_BUMP_2_NORMAL

    elif ch.normal_map_type == "NORMAL_MAP":
        if ch.enable_transition_bump:
            if root_ch.enable_smooth_bump:
                lib_name = BUMP_2_NORMAL_SMOOTH
            else:
                lib_name = BUMP_2_NORMAL
        elif is_parallax_enabled(root_ch):
            lib_name = NORMAL_MAP

    elif ch.normal_map_type == "BUMP_MAP":
        # When write_height is true, the bump to normal conversion is handled at
        # the material level using the combined height, so no per-layer node is needed
        write_height = get_write_height(ch)
        if not write_height:
            if root_ch.enable_smooth_bump:
                lib_name = BUMP_2_NORMAL_SMOOTH
            else:
                lib_name = BUMP_2_NORMAL

    elif ch.normal_map_type == "BUMP_NORMAL_MAP":
        if not ch.write_height:
            if root_ch.enable_smooth_bump:
                lib_name = BUMP_2_NORMAL_SMOOTH
            else:
                lib_name = BUMP_2_NORMAL
        elif is_parallax_enabled(root_ch):
            lib_name = NORMAL_MAP

    return lib_name


def check_normal_map_proc_node(tree, layer, ch, need_reconnect=False):
    """
    Check and create normal map process node.

    Parameters:
        tree: Node tree to check and update nodes in.
        layer: Layer object containing the channel.
        ch: Channel to check normal map process node for.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    if layer.type != "GROUP" and ch.normal_map_type in {
        "NORMAL_MAP",
        "BUMP_NORMAL_MAP",
    }:
        normal_map_proc, need_reconnect = check_new_node(
            tree,
            ch,
            "normal_map_proc",
            "ShaderNodeNormalMap",
            "Normal Map Process",
            True,
        )
        normal_map_proc.uv_map = layer.uv_name
        normal_map_proc.space = ch.normal_space
    else:
        if remove_node(tree, ch, "normal_map_proc"):
            need_reconnect = True

    return need_reconnect


def check_normal_proc_node(tree, layer, root_ch, ch, max_height, need_reconnect=False):
    """
    Check and create bump to normal conversion node.

    Parameters:
        tree: Node tree to check and update nodes in.
        layer: Layer object containing the channel.
        root_ch: Root channel object.
        ch: Channel to check normal process node for.
        max_height: Maximum height value for the displacement.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    lib_name = get_normal_process_lib_name(layer, root_ch, ch)

    if lib_name != "":
        normal_proc, need_reconnect = replace_new_node(
            tree,
            ch,
            "normal_proc",
            "ShaderNodeGroup",
            "Bump to Normal",
            lib_name,
            return_status=True,
            hard_replace=True,
            dirty=need_reconnect,
        )

        if "Max Height" in normal_proc.inputs:
            normal_proc.inputs["Max Height"].default_value = max_height
        if root_ch.enable_smooth_bump:
            if "Bump Height Scale" in normal_proc.inputs:
                normal_proc.inputs["Bump Height Scale"].default_value = (
                    get_fine_bump_distance(max_height)
                )

        if "Intensity" in normal_proc.inputs:
            normal_proc.inputs["Intensity"].default_value = ch.intensity_value

        if "Strength" in normal_proc.inputs:
            normal_proc.inputs["Strength"].default_value = ch.normal_strength

    else:
        if remove_node(tree, ch, "normal_proc"):
            need_reconnect = True

    return need_reconnect


def check_normal_flip_node(tree, layer, root_ch, ch, mp, need_reconnect=False):
    """
    Check and create normal flip node for backface handling.

    Note: This function currently always removes the node as normal flip
    is not supported for non-smooth bump.

    Parameters:
        tree: Node tree to check and update nodes in.
        layer: Layer object containing the channel.
        root_ch: Root channel object.
        ch: Channel to check normal flip node for.
        mp: Material properties object.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    write_height = get_write_height(ch)

    # NOTE: Normal flip node is kinda unnecessary since non smooth bump
    # don't support backface up for now
    if False and not root_ch.enable_smooth_bump and not write_height:
        if is_bl_newer_than(2, 80):
            lib_name = FLIP_BACKFACE_BUMP
        else:
            lib_name = FLIP_BACKFACE_BUMP_LEGACY

        normal_flip = replace_new_node(
            tree,
            ch,
            "normal_flip",
            "ShaderNodeGroup",
            "Normal Backface Flip",
            lib_name,
        )

        set_bump_backface_flip(normal_flip, mp.enable_backface_always_up)
    else:
        if remove_node(tree, ch, "normal_flip"):
            need_reconnect = True

    return need_reconnect


def remove_normal_process_nodes(tree, ch, need_reconnect=False):
    """
    Remove all normal process related nodes.

    Parameters:
        tree: Node tree to remove nodes from.
        ch: Channel to remove nodes for.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    if remove_node(tree, ch, "normal_map_proc"):
        need_reconnect = True
    if remove_node(tree, ch, "normal_proc"):
        need_reconnect = True
    if remove_node(tree, ch, "normal_flip"):
        need_reconnect = True

    return need_reconnect
