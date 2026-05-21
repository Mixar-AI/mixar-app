# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Height blend node operations for normal channel handling.

This module contains functions for checking and creating height blend nodes
with different blend types (MIX, OVERLAY, COMPARE).
"""

from ...utils.common import get_write_height
from ..lib.lib import *
from ..node.create_nodes import replace_new_node
from ..node.node_utils import is_normal_height_input_connected
from ..node.update_nodes import replace_new_mix_node


def get_height_blend_lib_name_mix(layer, root_ch):
    """
    Determine the library name for height blend node with MIX blend type.

    Parameters:
        layer: Layer object containing the channel.
        root_ch: Root channel object.

    Returns:
        String with the library name, or None if standard mix node should be used.
    """
    if layer.parent_idx != -1 or (
        is_normal_height_input_connected(root_ch)
        and root_ch.enable_smooth_bump
    ):
        if root_ch.enable_smooth_bump:
            return STRAIGHT_OVER_HEIGHT_MIX_SMOOTH
        else:
            return STRAIGHT_OVER_HEIGHT_MIX
    else:
        if root_ch.enable_smooth_bump:
            return HEIGHT_MIX_SMOOTH
        else:
            return None  # Use standard mix node


def get_height_blend_lib_name_overlay(layer, root_ch):
    """
    Determine the library name for height blend node with OVERLAY blend type.

    Parameters:
        layer: Layer object containing the channel.
        root_ch: Root channel object.

    Returns:
        String with the library name, or None if standard mix node should be used.
    """
    if layer.parent_idx != -1 or (
        is_normal_height_input_connected(root_ch)
        and root_ch.enable_smooth_bump
    ):
        if root_ch.enable_smooth_bump:
            return STRAIGHT_OVER_HEIGHT_ADD_SMOOTH
        else:
            return STRAIGHT_OVER_HEIGHT_ADD
    else:
        if root_ch.enable_smooth_bump:
            return HEIGHT_ADD_SMOOTH
        else:
            return None  # Use standard mix node


def get_height_blend_lib_name_compare(layer, root_ch):
    """
    Determine the library name for height blend node with COMPARE blend type.

    Parameters:
        layer: Layer object containing the channel.
        root_ch: Root channel object.

    Returns:
        String with the library name.
    """
    if layer.parent_idx != -1 or (
        is_normal_height_input_connected(root_ch) and root_ch.enable_smooth_bump
    ):
        if root_ch.enable_smooth_bump:
            return STRAIGHT_OVER_HEIGHT_COMPARE_SMOOTH
        else:
            return STRAIGHT_OVER_HEIGHT_COMPARE
    else:
        if root_ch.enable_smooth_bump:
            return HEIGHT_COMPARE_SMOOTH
        else:
            return HEIGHT_COMPARE


def _check_height_blend_mix(tree, layer, root_ch, ch, write_height, need_reconnect):
    """
    Check and create height blend node with MIX blend type.

    Parameters:
        tree: Node tree to check and update nodes in.
        layer: Layer object containing the channel.
        root_ch: Root channel object.
        ch: Channel to check height blend node for.
        write_height: Whether height writing is enabled.
        need_reconnect: Initial reconnection flag state.

    Returns:
        Updated need_reconnect flag.
    """
    lib_name = get_height_blend_lib_name_mix(layer, root_ch)

    if lib_name is not None:
        height_blend, need_reconnect = replace_new_node(
            tree,
            ch,
            "height_blend",
            "ShaderNodeGroup",
            "Height Blend",
            lib_name,
            return_status=True,
            hard_replace=True,
            dirty=need_reconnect,
        )

        divide = height_blend.inputs.get("Divide")
        if divide is not None:
            divide.default_value = 1.0 if write_height else 0.0
    else:
        height_blend, need_reconnect = replace_new_mix_node(
            tree,
            ch,
            "height_blend",
            "Height Blend",
            return_status=True,
            dirty=need_reconnect,
        )
        height_blend.blend_type = "MIX"

    return need_reconnect


def _check_height_blend_overlay(tree, layer, root_ch, ch, write_height, need_reconnect):
    """
    Check and create height blend node with OVERLAY blend type.

    Parameters:
        tree: Node tree to check and update nodes in.
        layer: Layer object containing the channel.
        root_ch: Root channel object.
        ch: Channel to check height blend node for.
        write_height: Whether height writing is enabled.
        need_reconnect: Initial reconnection flag state.

    Returns:
        Updated need_reconnect flag.
    """
    lib_name = get_height_blend_lib_name_overlay(layer, root_ch)

    if lib_name is not None:
        height_blend, need_reconnect = replace_new_node(
            tree,
            ch,
            "height_blend",
            "ShaderNodeGroup",
            "Height Blend",
            lib_name,
            return_status=True,
            hard_replace=True,
            dirty=need_reconnect,
        )

        divide = height_blend.inputs.get("Divide")
        if divide is not None:
            divide.default_value = 1.0 if write_height else 0.0
    else:
        height_blend, need_reconnect = replace_new_mix_node(
            tree,
            ch,
            "height_blend",
            "Height Blend",
            return_status=True,
            dirty=need_reconnect,
        )
        height_blend.blend_type = "ADD"

    return need_reconnect


def _check_height_blend_compare(tree, layer, root_ch, ch, need_reconnect):
    """
    Check and create height blend node with COMPARE blend type.

    Parameters:
        tree: Node tree to check and update nodes in.
        layer: Layer object containing the channel.
        root_ch: Root channel object.
        ch: Channel to check height blend node for.
        need_reconnect: Initial reconnection flag state.

    Returns:
        Updated need_reconnect flag.
    """
    lib_name = get_height_blend_lib_name_compare(layer, root_ch)

    height_blend, need_reconnect = replace_new_node(
        tree,
        ch,
        "height_blend",
        "ShaderNodeGroup",
        "Height Blend",
        lib_name,
        return_status=True,
        hard_replace=True,
        dirty=need_reconnect,
    )

    return need_reconnect


def check_height_blend_node(tree, layer, root_ch, ch, need_reconnect=False):
    """
    Check and create height blend node.

    Parameters:
        tree: Node tree to check and update nodes in.
        layer: Layer object containing the channel.
        root_ch: Root channel object.
        ch: Channel to check height blend node for.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    write_height = get_write_height(ch)

    if ch.normal_blend_type == "MIX":
        need_reconnect = _check_height_blend_mix(
            tree, layer, root_ch, ch, write_height, need_reconnect
        )
    elif ch.normal_blend_type == "OVERLAY":
        need_reconnect = _check_height_blend_overlay(
            tree, layer, root_ch, ch, write_height, need_reconnect
        )
    else:
        # COMPARE blend type
        need_reconnect = _check_height_blend_compare(
            tree, layer, root_ch, ch, need_reconnect
        )

    return need_reconnect
