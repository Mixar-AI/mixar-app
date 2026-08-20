# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Main layer I/O node operations module.

This module contains functions for checking and updating layer I/O nodes,
channel nodes, and linear nodes. Texcoord node operations are delegated
to check_texcoord_nodes.py.
"""

from ..element.check_elements import check_entity_image_flip_y
from ..element.check_processes import check_layer_bump_process
from ..io.input_outputs.input_outputs_nodes import (
    check_layer_channel_linear_node,
    check_layer_image_linear_node,
    check_layer_texcoord_nodes as _check_layer_texcoord_nodes,
    check_mask_image_linear_node,
)
from ..io.input_outputs.input_outputs_layer_ios import check_layer_tree_ios
from ..io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ..io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ..layer.check_layers import (
    check_layer_divider_alpha,
    get_layer_enabled,
    is_layer_using_vector,
)
from ..layer.layer_utils import get_height_channel, get_layer_index
from ..node.create_nodes import new_node
from ..subtree.get_subtree import (
    get_list_of_all_children_and_child_ids,
    get_list_of_parent_ids,
    get_tree,
)
from .check_channel_blend_nodes import check_blend_type_nodes
from .check_mask_nodes import check_mask_mix_nodes
from .check_transition_bump import (
    check_transition_bump_influences_to_other_channels,
    check_transition_bump_nodes,
)
from .check_uv_nodes import check_uv_nodes

# Import from the new helper module and re-export for backward compatibility
from .check_texcoord_nodes import (
    check_layer_texcoord_nodes,
    check_mask_texcoord_nodes,
)

# Re-export all public functions for backward compatibility
__all__ = [
    "check_all_layer_channel_io_and_nodes",
    "check_mp_channel_nodes",
    "check_mask_texcoord_nodes",
    "check_layer_texcoord_nodes",
    "check_mp_linear_nodes",
]


def check_all_layer_channel_io_and_nodes(
    layer,
    tree=None,
    specific_ch=None,
    do_recursive=True,
    remove_props=False,
    hard_reset=False,
):
    """
    Check and update all input/output and channel nodes for a layer.

    Parameters:
        layer: Layer object to check nodes for.
        tree (optional): Node tree to check. If None, will be obtained from layer. Default: None.
        specific_ch (optional): If provided, only check this specific channel. Default: None.
        do_recursive (optional): If True, recursively check parent and child layers. Default: True.
        remove_props (optional): If True, remove properties during check. Default: False.
        hard_reset (optional): If True, perform a hard reset of nodes. Default: False.

    Returns:
        None. Nodes are checked and updated directly in the tree.
    """

    mp = layer.id_data.mp
    if not tree:
        tree = get_tree(layer)

    # Check layer tree io
    check_layer_tree_ios(layer, tree, remove_props=remove_props, hard_reset=hard_reset)

    # Check texcoord nodes
    _check_layer_texcoord_nodes(layer, tree)

    # Create mapping if necessary
    if is_layer_using_vector(layer):
        mapping = tree.nodes.get(layer.mapping)
        if not mapping:
            mapping = new_node(tree, layer, "mapping", "ShaderNodeMapping", "Mapping")

    # Linear node
    check_layer_image_linear_node(layer)

    # Check the need of bump process
    check_layer_bump_process(layer, tree)

    # Check the need of divider alpha
    check_layer_divider_alpha(layer)

    # Check the need of flip y
    check_entity_image_flip_y(layer)

    # Update transition related nodes
    height_ch = get_height_channel(layer)
    if height_ch:
        check_transition_bump_nodes(layer, tree, height_ch)

    # Channel nodes
    for i, ch in enumerate(layer.channels):
        if specific_ch and specific_ch != ch:
            continue
        root_ch = mp.channels[i]

        # Update layer ch blend type
        check_blend_type_nodes(root_ch, layer, ch)

        if (
            root_ch.type != "NORMAL"
        ):  # Because normal map related nodes should already created
            # Check mask mix nodes
            check_mask_mix_nodes(layer, tree, specific_ch=ch)

        else:
            # Check flip y
            if ch.normal_map_type in {"NORMAL_MAP", "BUMP_NORMAL_MAP"}:
                check_entity_image_flip_y(ch)

    # Mask nodes
    for mask in layer.masks:
        check_mask_texcoord_nodes(layer, mask, tree)

    # Linear nodes
    check_mp_linear_nodes(mp, layer, False)

    # Check other affected layers
    if do_recursive:
        do_recursive = False
        other_layers = []

        # Check parent layers
        for pid in get_list_of_parent_ids(layer):
            parent = mp.layers[pid]
            other_layers.append(parent)

        # Check child layers
        children, child_ids = get_list_of_all_children_and_child_ids(layer)
        for child in children:
            other_layers.append(child)

        # Check background layers
        layer_idx = get_layer_index(layer)
        bgs = [
            l
            for i, l in enumerate(mp.layers)
            if i < layer_idx and l.type == "BACKGROUND"
        ]
        other_layers.extend(bgs)

        # Recursive to other affected layers
        for ol in other_layers:
            check_all_layer_channel_io_and_nodes(
                ol, do_recursive=do_recursive, hard_reset=hard_reset
            )
            reconnect_layer_nodes(ol)
            rearrange_layer_nodes(ol)


def check_mp_channel_nodes(mp, reconnect=False):
    """
    Check and update all channel nodes across all layers in the mpaint tree.

    Parameters:
        mp: MPaint object containing all layers and channels.
        reconnect (optional): If True, reconnect and rearrange nodes after checking. Default: False.

    Returns:
        None. Nodes are checked and updated directly in the tree.
    """

    # Link between layers
    for layer in mp.layers:
        layer_tree = get_tree(layer)

        # Make sure the number of channels are correct
        num_difference = len(mp.channels) - len(layer.channels)
        if num_difference > 0:
            for i in range(num_difference):
                # Add new channel
                c = layer.channels.add()
        elif num_difference < 0:
            for i in range(abs(num_difference)):
                last_idx = len(layer.channels) - 1
                # Remove layer channel
                layer.channels.remove(channel_idx)

        for mask in layer.masks:
            num_difference = len(mp.channels) - len(mask.channels)
            if num_difference > 0:
                for i in range(num_difference):
                    # Add new channel to mask
                    mc = mask.channels.add()
            elif num_difference < 0:
                for i in range(abs(num_difference)):
                    last_idx = len(mask.channels) - 1
                    # Remove mask channel
                    mask.channels.remove(channel_idx)

        # Check and set mask intensity nodes
        check_transition_bump_influences_to_other_channels(layer, layer_tree)

        # Set mask multiply nodes
        check_mask_mix_nodes(layer, layer_tree)

        # Add new nodes
        check_all_layer_channel_io_and_nodes(layer, layer_tree)

    # Check uv maps
    check_uv_nodes(mp)

    if reconnect:
        for layer in mp.layers:
            reconnect_layer_nodes(layer)
            rearrange_layer_nodes(layer)

        reconnect_mp_nodes(mp.id_data)
        rearrange_mp_nodes(mp.id_data)


def check_mp_linear_nodes(mp, specific_layer=None, reconnect=True):
    """
    Check and update linear color space nodes for all layers.

    Parameters:
        mp: MPaint object containing all layers.
        specific_layer (optional): If provided, only check this specific layer. Default: None.
        reconnect (optional): If True, reconnect and rearrange nodes after checking. Default: True.

    Returns:
        None. Nodes are checked and updated directly in the tree.
    """
    for layer in mp.layers:
        if specific_layer and layer != specific_layer:
            continue
        if layer.type == "IMAGE":
            check_layer_image_linear_node(layer)
        for ch in layer.channels:
            check_layer_channel_linear_node(ch)
        for mask in layer.masks:
            if mask.type == "IMAGE":
                check_mask_image_linear_node(mask)

        if reconnect:
            reconnect_layer_nodes(layer)
            rearrange_layer_nodes(layer)
