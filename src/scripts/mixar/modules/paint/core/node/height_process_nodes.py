# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Height process node operations for normal channel handling.

This module contains functions for checking and creating height-related nodes
including bump distance, transition bump, height process, and max height nodes.
"""

from ...utils.common import (
    get_write_height,
    is_bump_distance_relevant,
)
from ..lib.lib import *
from .node_tree_utils import get_node_tree_lib
from ..node.create_nodes import check_new_node, replace_new_node
from ..node.node_graph import (
    get_layer_channel_bump_distance,
    get_transition_bump_max_distance,
)
from ..node.node_utils import remove_node
from ..node.update_nodes import set_default_value
from ..subtree.get_subtree import get_transition_disp_delta
from .height_blend_nodes import check_height_blend_node


def check_bump_distance_nodes(tree, layer, ch, need_reconnect=False):
    """
    Check and create bump distance ignorer and transition bump flipper nodes.

    Parameters:
        tree: Node tree to check and update nodes in.
        layer: Layer object containing the channel.
        ch: Channel to check bump distance nodes for.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    # Bump distance ignorer
    if ch.normal_map_type in {
        "BUMP_MAP",
        "BUMP_NORMAL_MAP",
    } and not is_bump_distance_relevant(layer, ch):
        bump_distance_ignorer, dirty = check_new_node(
            tree,
            ch,
            "bump_distance_ignorer",
            "ShaderNodeMath",
            "Bump Distance Ignorer",
            True,
        )
        if dirty:
            need_reconnect = True
        bump_distance_ignorer.operation = "MULTIPLY"
        bump_distance_ignorer.inputs[1].default_value = 0.0
    else:
        if remove_node(tree, ch, "bump_distance_ignorer"):
            need_reconnect = True

    # Transition bump flipper
    if ch.enable_transition_bump and ch.transition_bump_flip:
        tb_distance_flipper, dirty = check_new_node(
            tree,
            ch,
            "tb_distance_flipper",
            "ShaderNodeMath",
            "Transition Bump Distance Flipper",
            True,
        )
        if dirty:
            need_reconnect = True
        tb_distance_flipper.operation = "MULTIPLY"
        tb_distance_flipper.inputs[1].default_value = -1.0
    else:
        if remove_node(tree, ch, "tb_distance_flipper"):
            need_reconnect = True

    return need_reconnect


def check_transition_bump_delta_calc(tree, ch, need_reconnect=False):
    """
    Check and create transition bump delta calculation node.

    Parameters:
        tree: Node tree to check and update nodes in.
        ch: Channel to check delta calc node for.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    if (
        ch.normal_map_type in {"BUMP_MAP", "BUMP_NORMAL_MAP"}
        and ch.enable_transition_bump
    ):
        tb_delta_calc, dirty = check_new_node(
            tree,
            ch,
            "tb_delta_calc",
            "ShaderNodeGroup",
            "Transition Bump Delta Calculation",
            True,
        )
        if dirty:
            need_reconnect = True
        tb_delta_calc.node_tree = get_node_tree_lib(TB_DELTA_CALC)
    else:
        if remove_node(tree, ch, "tb_delta_calc"):
            need_reconnect = True

    return need_reconnect


def get_max_height_calc_lib_name(ch):
    """
    Determine the library name for max height calculation node.

    Parameters:
        ch: Channel to get lib name for.

    Returns:
        String with the library name for max height calculation.
    """
    if ch.enable_transition_bump:
        if ch.transition_bump_crease and not ch.transition_bump_flip:
            if ch.normal_blend_type == "OVERLAY":
                return CH_MAX_HEIGHT_TBC_ADD_CALC
            else:
                return CH_MAX_HEIGHT_TBC_CALC
        else:
            if ch.normal_blend_type == "OVERLAY":
                return CH_MAX_HEIGHT_TB_ADD_CALC
            else:
                return CH_MAX_HEIGHT_TB_CALC
    else:
        if ch.normal_blend_type == "OVERLAY":
            return CH_MAX_HEIGHT_ADD_CALC
        else:
            return CH_MAX_HEIGHT_CALC


def check_max_height_calc_node(tree, ch, need_reconnect=False):
    """
    Check and create max height calculation node.

    Parameters:
        tree: Node tree to check and update nodes in.
        ch: Channel to check max height calc node for.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    lib_name = get_max_height_calc_lib_name(ch)

    if ch.write_height:
        max_height_calc, need_reconnect = replace_new_node(
            tree,
            ch,
            "max_height_calc",
            "ShaderNodeGroup",
            "Max Height Calculation",
            lib_name,
            return_status=True,
            hard_replace=True,
            dirty=need_reconnect,
        )

        inp = max_height_calc.inputs.get("Is Flipped")
        if inp:
            inp.default_value = (
                1.0 if ch.enable_transition_bump and ch.transition_bump_flip else 0.0
            )
    else:
        if remove_node(tree, ch, "max_height_calc"):
            need_reconnect = True

    return need_reconnect


def get_height_process_lib_name(layer, root_ch, ch):
    """
    Determine the library name for height process node.

    Parameters:
        layer: Layer object containing the channel.
        root_ch: Root channel object.
        ch: Channel to get lib name for.

    Returns:
        String with the library name for height process.
    """
    if layer.type != "GROUP" and ch.normal_map_type == "NORMAL_MAP":
        if root_ch.enable_smooth_bump:
            if ch.enable_transition_bump:
                if ch.transition_bump_crease and not ch.transition_bump_flip:
                    lib_name = HEIGHT_PROCESS_TRANSITION_SMOOTH_NORMAL_MAP_CREASE
                else:
                    lib_name = HEIGHT_PROCESS_TRANSITION_SMOOTH_NORMAL_MAP
            else:
                lib_name = HEIGHT_PROCESS_SMOOTH_NORMAL_MAP
        else:
            if ch.enable_transition_bump:
                if ch.transition_bump_crease and not ch.transition_bump_flip:
                    lib_name = HEIGHT_PROCESS_TRANSITION_NORMAL_MAP_CREASE
                else:
                    lib_name = HEIGHT_PROCESS_TRANSITION_NORMAL_MAP
            else:
                lib_name = HEIGHT_PROCESS_NORMAL_MAP
    else:
        if root_ch.enable_smooth_bump:
            if ch.enable_transition_bump:
                if ch.transition_bump_crease and not ch.transition_bump_flip:
                    lib_name = HEIGHT_PROCESS_TRANSITION_SMOOTH_CREASE
                elif ch.transition_bump_chain == 0:
                    lib_name = HEIGHT_PROCESS_TRANSITION_SMOOTH_ZERO_CHAIN
                else:
                    lib_name = HEIGHT_PROCESS_TRANSITION_SMOOTH
            else:
                lib_name = HEIGHT_PROCESS_SMOOTH
        else:
            if ch.enable_transition_bump:
                if ch.transition_bump_crease and not ch.transition_bump_flip:
                    lib_name = HEIGHT_PROCESS_TRANSITION_CREASE
                else:
                    lib_name = HEIGHT_PROCESS_TRANSITION
            else:
                lib_name = HEIGHT_PROCESS

        # Group lib
        if layer.type == "GROUP":
            lib_name += " Group"

    return lib_name


def check_height_process_node(tree, layer, root_ch, ch, channel_enabled, need_reconnect=False):
    """
    Check and create height process node.

    Parameters:
        tree: Node tree to check and update nodes in.
        layer: Layer object containing the channel.
        root_ch: Root channel object.
        ch: Channel to check height process node for.
        channel_enabled: Whether the channel is enabled.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    write_height = get_write_height(ch)
    lib_name = get_height_process_lib_name(layer, root_ch, ch)

    height_proc, need_reconnect = replace_new_node(
        tree,
        ch,
        "height_proc",
        "ShaderNodeGroup",
        "Height Process",
        lib_name,
        return_status=True,
        hard_replace=True,
        dirty=need_reconnect,
    )

    if ch.normal_map_type == "NORMAL_MAP":
        if ch.enable_transition_bump:
            set_default_value(
                height_proc, "Bump Height", get_transition_bump_max_distance(ch)
            )
        else:
            set_default_value(height_proc, "Bump Height", ch.normal_bump_distance)
    else:
        if layer.type != "GROUP":
            set_default_value(
                height_proc,
                "Value Max Height",
                get_layer_channel_bump_distance(layer, ch),
            )
        if ch.enable_transition_bump:
            set_default_value(
                height_proc, "Delta", get_transition_disp_delta(layer, ch)
            )
            set_default_value(
                height_proc,
                "Transition Max Height",
                get_transition_bump_max_distance(ch),
            )

    set_default_value(height_proc, "Intensity", ch.intensity_value)

    if (
        ch.enable_transition_bump
        and channel_enabled
        and ch.transition_bump_crease
        and not ch.transition_bump_flip
    ):
        set_default_value(
            height_proc, "Crease Factor", ch.transition_bump_crease_factor
        )
        set_default_value(
            height_proc, "Crease Power", ch.transition_bump_crease_power
        )

        if not write_height and not root_ch.enable_smooth_bump:
            set_default_value(height_proc, "Remaining Filter", 1.0)
        else:
            set_default_value(height_proc, "Remaining Filter", 0.0)

    return need_reconnect


def check_height_rgb_to_bw_node(tree, layer, ch, need_reconnect=False):
    """Check and create RGB to BW node for height luminance extraction.

    This node is needed for IMAGE layers with bump-based height to properly
    extract luminance from painted RGB colors for height calculation.
    Without this, only the red channel would be used (Blender's default
    color-to-float conversion), causing incorrect height values when
    painting with colored brushes.

    Parameters:
        tree: Node tree to check and update nodes in.
        layer: Layer object containing the channel.
        ch: Channel to check RGB to BW node for.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    # Check if property exists (may not exist on older saved files)
    if not hasattr(ch, 'height_rgb_to_bw'):
        return need_reconnect

    # Needed for ALL IMAGE layers with bump-based height types
    # The image texture outputs RGB, but height calculation needs grayscale
    # Without RGB to BW, only the red channel would be used for height
    needs_rgb_to_bw = (
        layer.type == 'IMAGE' and
        ch.normal_map_type in {'BUMP_MAP', 'BUMP_NORMAL_MAP'}
    )

    if needs_rgb_to_bw:
        # Create or get the RGB to BW node
        rgb_to_bw, dirty = check_new_node(
            tree, ch, 'height_rgb_to_bw',
            'ShaderNodeRGBToBW',
            'Height Luminance',
            return_dirty=True
        )
        if dirty:
            need_reconnect = True
    else:
        # Remove the node if it exists but is not needed
        if remove_node(tree, ch, 'height_rgb_to_bw'):
            need_reconnect = True

    return need_reconnect


def remove_height_process_nodes(tree, ch, need_reconnect=False):
    """
    Remove all height process related nodes.

    Parameters:
        tree: Node tree to remove nodes from.
        ch: Channel to remove nodes for.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        Updated need_reconnect flag.
    """
    if remove_node(tree, ch, "height_proc"):
        need_reconnect = True
    if remove_node(tree, ch, "height_blend"):
        need_reconnect = True
    if remove_node(tree, ch, "height_rgb_to_bw"):
        need_reconnect = True
    if remove_node(tree, ch, "bump_distance_ignorer"):
        need_reconnect = True
    if remove_node(tree, ch, "tb_distance_flipper"):
        need_reconnect = True
    if remove_node(tree, ch, "tb_delta_calc"):
        need_reconnect = True
    if remove_node(tree, ch, "max_height_calc"):
        need_reconnect = True

    return need_reconnect


# Re-export check_height_blend_node for backward compatibility
__all__ = [
    "check_bump_distance_nodes",
    "check_transition_bump_delta_calc",
    "get_max_height_calc_lib_name",
    "check_max_height_calc_node",
    "get_height_process_lib_name",
    "check_height_process_node",
    "check_height_rgb_to_bw_node",
    "remove_height_process_nodes",
    "check_height_blend_node",
]
