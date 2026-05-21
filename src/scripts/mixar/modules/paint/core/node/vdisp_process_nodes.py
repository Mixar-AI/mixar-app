# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Vector displacement process node operations for normal channel handling.

This module contains functions for checking and creating vector displacement
related nodes including vdisp process, flip Y/Z, and vdisp blend nodes.
"""

from ..lib.lib import *
from .node_tree_utils import get_node_tree_lib
from ..node.create_nodes import check_new_node, replace_new_node
from ..node.node_utils import remove_node
from ..node.update_nodes import replace_new_mix_node


def check_vdisp_intensity_node(tree, ch, need_reconnect=False):
    """
    Check and create vdisp intensity node for groups.

    Parameters:
        tree: Node tree to check and update nodes in.
        ch: Channel to check vdisp intensity node for.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    vdisp_intensity, dirty = check_new_node(
        tree, ch, "vdisp_intensity", "ShaderNodeMath", "VDisp Opacity", True
    )
    vdisp_intensity.operation = "MULTIPLY"
    if dirty:
        need_reconnect = True

    return need_reconnect


def check_vdisp_flip_yz_node(tree, ch, need_reconnect=False):
    """
    Check and create vdisp flip Y/Z node.

    Parameters:
        tree: Node tree to check and update nodes in.
        ch: Channel to check flip Y/Z node for.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    if ch.vdisp_enable_flip_yz:
        vdisp_flip_yz, dirty = check_new_node(
            tree, ch, "vdisp_flip_yz", "ShaderNodeGroup", "Flip Y/Z", True
        )
        vdisp_flip_yz.node_tree = get_node_tree_lib(FLIP_YZ)
        if dirty:
            need_reconnect = True
    else:
        if remove_node(tree, ch, "vdisp_flip_yz"):
            need_reconnect = True

    return need_reconnect


def check_vdisp_proc_node(tree, ch, need_reconnect=False):
    """
    Check and create vdisp process node.

    Parameters:
        tree: Node tree to check and update nodes in.
        ch: Channel to check vdisp process node for.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    vdisp_proc, need_reconnect = replace_new_mix_node(
        tree,
        ch,
        "vdisp_proc",
        "Vector Displacement Process",
        return_status=True,
        hard_replace=True,
        dirty=need_reconnect,
    )
    vdisp_proc.blend_type = "MULTIPLY"
    vdisp_proc.inputs[0].default_value = 1.0

    return need_reconnect


def check_vdisp_blend_node(tree, layer, ch, need_reconnect=False):
    """
    Check and create vdisp blend node.

    Parameters:
        tree: Node tree to check and update nodes in.
        layer: Layer object containing the channel.
        ch: Channel to check vdisp blend node for.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    if layer.parent_idx != -1 and ch.normal_blend_type == "MIX":
        vdisp_blend, need_reconnect = replace_new_node(
            tree,
            ch,
            "vdisp_blend",
            "ShaderNodeGroup",
            "VDisp Blend",
            STRAIGHT_OVER_HEIGHT_MIX,
            return_status=True,
            hard_replace=True,
            dirty=need_reconnect,
        )
    elif layer.parent_idx != -1 and ch.normal_blend_type == "OVERLAY":
        vdisp_blend, need_reconnect = replace_new_node(
            tree,
            ch,
            "vdisp_blend",
            "ShaderNodeGroup",
            "VDisp Blend",
            STRAIGHT_OVER_HEIGHT_ADD,
            return_status=True,
            hard_replace=True,
            dirty=need_reconnect,
        )
    else:
        vdisp_blend, need_reconnect = replace_new_mix_node(
            tree,
            ch,
            "vdisp_blend",
            "VDisp Blend",
            return_status=True,
            hard_replace=True,
            dirty=need_reconnect,
        )
        vdisp_blend.blend_type = (
            "ADD" if ch.normal_blend_type == "OVERLAY" else "MIX"
        )

    return need_reconnect


def check_vdisp_process_nodes(tree, layer, ch, need_reconnect=False):
    """
    Check and create all vector displacement process nodes.

    Parameters:
        tree: Node tree to check and update nodes in.
        layer: Layer object containing the channel.
        ch: Channel to check vdisp nodes for.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    # Dedicated vdisp intensity currently is needed for group
    if layer.type == "GROUP":
        need_reconnect = check_vdisp_intensity_node(tree, ch, need_reconnect)

        if remove_node(tree, ch, "vdisp_proc"):
            need_reconnect = True
        if remove_node(tree, ch, "vdisp_flip_yz"):
            need_reconnect = True

    else:
        need_reconnect = check_vdisp_flip_yz_node(tree, ch, need_reconnect)
        need_reconnect = check_vdisp_proc_node(tree, ch, need_reconnect)

        if remove_node(tree, ch, "vdisp_intensity"):
            need_reconnect = True

    need_reconnect = check_vdisp_blend_node(tree, layer, ch, need_reconnect)

    return need_reconnect


def remove_vdisp_process_nodes(tree, ch, need_reconnect=False):
    """
    Remove all vector displacement process related nodes.

    Parameters:
        tree: Node tree to remove nodes from.
        ch: Channel to remove nodes for.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    if remove_node(tree, ch, "vdisp_proc"):
        need_reconnect = True
    if remove_node(tree, ch, "vdisp_flip_yz"):
        need_reconnect = True
    if remove_node(tree, ch, "vdisp_blend"):
        need_reconnect = True
    if remove_node(tree, ch, "vdisp_intensity"):
        need_reconnect = True

    return need_reconnect
