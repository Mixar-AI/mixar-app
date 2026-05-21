# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Check and update normal map related nodes for channels.

This module provides the main function for checking channel normal map nodes
and managing extra alpha nodes for layers.
"""

from ...utils.common import get_write_height
from ..layer.check_layers import (
    is_height_process_needed,
    is_normal_process_needed,
    is_vdisp_process_needed,
)
from ..layer.get_channels import get_channel_enabled
from ..layer.layer_utils import get_height_channel
from ..modifier.modifier import check_modifiers_trees, disable_modifiers_tree
from ..node.create_nodes import new_node
from ..node.node_utils import remove_node
from ..subtree.check_subtree import (
    check_mask_source_tree,
    disable_channel_source_tree,
    disable_layer_source_tree,
    enable_channel_source_tree,
    enable_layer_source_tree,
)
from ..subtree.get_subtree import get_displacement_max_height, get_tree
from .height_operations import update_displacement_height_ratio
from .height_process_nodes import (
    check_bump_distance_nodes,
    check_height_blend_node,
    check_height_process_node,
    check_height_rgb_to_bw_node,
    check_max_height_calc_node,
    check_transition_bump_delta_calc,
    remove_height_process_nodes,
)
from .normal_process_nodes import (
    check_normal_flip_node,
    check_normal_map_proc_node,
    check_normal_proc_node,
    remove_normal_process_nodes,
)
from .vdisp_process_nodes import (
    check_vdisp_process_nodes,
    remove_vdisp_process_nodes,
)


def check_channel_normal_map_nodes(tree, layer, root_ch, ch, need_reconnect=False):
    """
    Check and update all normal map related nodes for a channel.

    Parameters:
        tree: Node tree to check and update nodes in.
        layer: Layer object containing the channel.
        root_ch: Root channel object.
        ch: Channel to check normal map nodes for.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        True if any nodes were modified and reconnection is needed, False otherwise.
    """

    mp = layer.id_data.mp

    # Check mask mix nodes
    # Lazy import to avoid circular dependency
    from .check_mask_nodes import check_mask_mix_nodes
    if check_mask_mix_nodes(layer, tree):
        need_reconnect = True

    # Only normal channel will continue proceed with this function
    if root_ch.type != "NORMAL":
        return need_reconnect

    channel_enabled = get_channel_enabled(ch, layer, root_ch)
    height_process_needed = is_height_process_needed(layer)

    # Check mask source tree
    check_mask_source_tree(layer)

    # Check height pack/unpack
    # Lazy import to avoid circular dependency
    from .check_channel_blend_nodes import check_create_height_pack, check_create_spread_alpha
    if check_create_height_pack(layer, tree, root_ch, ch):
        need_reconnect = True

    # Check spread alpha if its needed
    if check_create_spread_alpha(layer, tree, root_ch, ch):
        need_reconnect = True

    # Dealing with neighbor related nodes
    if channel_enabled and root_ch.enable_smooth_bump and height_process_needed:
        enable_layer_source_tree(layer)
    else:
        disable_layer_source_tree(layer, False)
        disable_modifiers_tree(ch)

    # Dealing with channel override
    if (
        channel_enabled
        and ch.override
        and root_ch.enable_smooth_bump
        and ch.override_type != "DEFAULT"
        and ch.normal_map_type in {"BUMP_MAP", "BUMP_NORMAL_MAP"}
        and height_process_needed
    ):
        enable_channel_source_tree(layer, root_ch, ch)
    else:
        disable_channel_source_tree(layer, root_ch, ch, False)

    if channel_enabled:
        # Check modifier trees
        check_modifiers_trees(ch)

        max_height = get_displacement_max_height(root_ch, layer)
        update_displacement_height_ratio(root_ch)

    if channel_enabled and height_process_needed:
        need_reconnect = _check_height_process_nodes(
            tree, layer, root_ch, ch, channel_enabled, need_reconnect
        )
    else:
        need_reconnect = remove_height_process_nodes(tree, ch, need_reconnect)

    # Normal Process
    if channel_enabled and is_normal_process_needed(layer):
        max_height = get_displacement_max_height(root_ch, layer)
        need_reconnect = _check_normal_process_nodes(
            tree, layer, root_ch, ch, mp, max_height, need_reconnect
        )
    else:
        need_reconnect = remove_normal_process_nodes(tree, ch, need_reconnect)

    # Vector Displacement Process
    if channel_enabled and is_vdisp_process_needed(layer):
        need_reconnect = check_vdisp_process_nodes(tree, layer, ch, need_reconnect)
    else:
        need_reconnect = remove_vdisp_process_nodes(tree, ch, need_reconnect)

    return need_reconnect


def _check_height_process_nodes(tree, layer, root_ch, ch, channel_enabled, need_reconnect):
    """
    Check and create all height process related nodes.

    Parameters:
        tree: Node tree to check and update nodes in.
        layer: Layer object containing the channel.
        root_ch: Root channel object.
        ch: Channel to check height process nodes for.
        channel_enabled: Whether the channel is enabled.
        need_reconnect: Initial reconnection flag state.

    Returns:
        Updated need_reconnect flag.
    """
    # Bump distance nodes
    need_reconnect = check_bump_distance_nodes(tree, layer, ch, need_reconnect)

    # Transition bump delta calculation
    need_reconnect = check_transition_bump_delta_calc(tree, ch, need_reconnect)

    # Max height calculation node
    need_reconnect = check_max_height_calc_node(tree, ch, need_reconnect)

    # Height process node
    need_reconnect = check_height_process_node(
        tree, layer, root_ch, ch, channel_enabled, need_reconnect
    )

    # RGB to BW node for luminance extraction (IMAGE layers with Color channel)
    need_reconnect = check_height_rgb_to_bw_node(tree, layer, ch, need_reconnect)

    # Height blend node
    need_reconnect = check_height_blend_node(tree, layer, root_ch, ch, need_reconnect)

    return need_reconnect


def _check_normal_process_nodes(tree, layer, root_ch, ch, mp, max_height, need_reconnect):
    """
    Check and create all normal process related nodes.

    Parameters:
        tree: Node tree to check and update nodes in.
        layer: Layer object containing the channel.
        root_ch: Root channel object.
        ch: Channel to check normal process nodes for.
        mp: Material properties object.
        max_height: Maximum height value for the displacement.
        need_reconnect: Initial reconnection flag state.

    Returns:
        Updated need_reconnect flag.
    """
    # Normal map process node
    need_reconnect = check_normal_map_proc_node(tree, layer, ch, need_reconnect)

    # Normal process (bump to normal) node
    need_reconnect = check_normal_proc_node(
        tree, layer, root_ch, ch, max_height, need_reconnect
    )

    # Normal flip node
    need_reconnect = check_normal_flip_node(tree, layer, root_ch, ch, mp, need_reconnect)

    return need_reconnect


def check_extra_alpha(layer, need_reconnect=False):
    """
    Check and manage extra alpha nodes for channels when displacement compare mode is used.

    Parameters:
        layer: Layer object to check extra alpha nodes for.
        need_reconnect (optional): Initial reconnection flag state. Default: False.

    Returns:
        True if any nodes were modified and reconnection is needed, False otherwise.
    """

    mp = layer.id_data.mp

    disp_ch = get_height_channel(layer)
    if not disp_ch:
        return

    tree = get_tree(layer)

    for i, ch in enumerate(layer.channels):
        if disp_ch == ch:
            continue

        root_ch = mp.channels[i]
        channel_enabled = get_channel_enabled(ch, layer, root_ch)

        extra_alpha = tree.nodes.get(ch.extra_alpha)

        if (
            channel_enabled
            and disp_ch.enable
            and disp_ch.normal_blend_type == "COMPARE"
        ):

            if not extra_alpha:
                extra_alpha = new_node(
                    tree, ch, "extra_alpha", "ShaderNodeMath", "Extra Alpha"
                )
                extra_alpha.operation = "MULTIPLY"
                need_reconnect = True

        elif extra_alpha:
            remove_node(tree, ch, "extra_alpha")
            need_reconnect = True

    return need_reconnect
