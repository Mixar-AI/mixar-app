# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Main entry point for reconnecting mp nodes in the MPaint node tree.
"""

from ......config.logging_config import get_logger
logger = get_logger(__name__)

from ....utils.blender_commons import get_user_preferences
from ....utils.constants import io_suffix
from ...element.modifier_utils import reconnect_all_modifier_nodes
from ..utils.io_utils import create_link
from ...layer.layer_utils import (
    get_root_height_channel,
    is_bottom_member,
)
from ...node.node_utils import clean_essential_nodes
from ...subtree.get_subtree import get_upper_neighbor
from ..parallax.parallax_connections import remove_all_prev_inputs
from ..utils.depth_connections import remove_unused_group_node_connections

# Import helper modules
from .mp_connections_parallax import (
    setup_uv_maps,
    get_main_tangent_bitangent,
    setup_baked_uv,
    reconnect_parallax_nodes,
    reconnect_parallax_preparations,
    connect_parallax_height_inputs,
)
from .mp_connections_channels import (
    initialize_channel_values,
    initialize_normal_channel_values,
    process_start_bump,
    process_start_linear,
    process_end_linear_normal,
    process_clamp_and_backface,
    process_baked_channel,
    process_baked_vcol,
    connect_channel_to_tree_end,
)
from .mp_connections_layers import (
    process_layer_preview,
    should_skip_layer,
    connect_layer_uv_inputs,
    connect_layer_texcoord_inputs,
    connect_background_layer,
    connect_layer_channel_io,
)


def reconnect_mp_nodes(tree, merged_layer_ids=[]):
    """
    Reconnect all nodes in the main MPaint (Texture Paint) node tree.

    This is the master reconnection function that handles all node connections for the entire
    texture painting system. It processes UV maps, parallax effects, all layers, channels,
    and their interconnections. This ensures the complete node network is properly connected.

    Parameters:
        tree: The main MPaint node tree.
        merged_layer_ids (list, optional): List of layer IDs that have been merged. Default is [].

    Returns:
        None
    """
    mp = tree.mp
    nodes = tree.nodes

    # Setup UV maps and tangents
    uv_maps, tangents, bitangents = setup_uv_maps(mp, nodes)
    tangent, bitangent = get_main_tangent_bitangent(mp, tangents, bitangents)
    height_ch = get_root_height_channel(mp)

    # Setup baked UV
    baked_uv_map = setup_baked_uv(tree, mp, nodes)

    # Reconnect parallax nodes
    reconnect_parallax_nodes(tree, mp)

    # Reconnect parallax preparations
    reconnect_parallax_preparations(
        tree, mp, uv_maps, tangents, bitangents, tangent, bitangent
    )

    # Connect parallax height inputs
    connect_parallax_height_inputs(tree, mp)

    # Process channels
    for i, ch in enumerate(mp.channels):
        _process_channel(
            tree, mp, nodes, ch, i, merged_layer_ids,
            uv_maps, tangents, bitangents, tangent, bitangent,
            height_ch, baked_uv_map
        )

    # Connect bake target image nodes
    for bt in mp.bake_targets:
        image_node = nodes.get(bt.image_node)
        if image_node and baked_uv_map:
            create_link(tree, baked_uv_map, image_node.inputs[0])

    # Merge process doesn't care with parents
    if merged_layer_ids:
        return

    # Post-processing: group connections and cleanup
    _process_group_connections(tree, mp, nodes)

    # Clean unused essential nodes
    clean_essential_nodes(tree)


def _process_channel(tree, mp, nodes, ch, ch_index, merged_layer_ids,
                     uv_maps, tangents, bitangents, tangent, bitangent,
                     height_ch, baked_uv_map):
    """
    Process a single channel's layer connections and end node connections.

    Parameters:
        tree: The node tree.
        mp: The MPaint data from the tree.
        nodes: The nodes in the tree.
        ch: The current channel.
        ch_index: Index of the channel.
        merged_layer_ids: List of merged layer IDs.
        uv_maps: Dictionary of UV map outputs.
        tangents: Dictionary of tangent outputs.
        bitangents: Dictionary of bitangent outputs.
        tangent: Main tangent output.
        bitangent: Main bitangent output.
        height_ch: The height channel.
        baked_uv_map: Baked UV map output.
    """
    # Initialize channel values and nodes
    channel_nodes, io_names_dict, channel_values = initialize_channel_values(
        tree, ch, nodes
    )

    # Initialize normal channel values if applicable
    if ch.type == "NORMAL":
        normal_values = initialize_normal_channel_values(tree, ch)
        channel_values.update(normal_values)

        # Process start bump
        channel_values = process_start_bump(tree, ch, channel_values, channel_nodes)

    # Process start linear
    channel_values["rgb"] = process_start_linear(tree, ch, channel_values, channel_nodes)

    # Store background values
    bg_rgb = channel_values["rgb"]
    bg_alpha = channel_values["alpha"]
    bg_height = channel_values.get("height")

    # Process layers
    for j, layer in reversed(list(enumerate(mp.layers))):
        node = nodes.get(layer.group_node)

        # Skip if layer doesn't have this channel (can happen during channel removal)
        if ch_index >= len(layer.channels):
            continue
        layer_ch = layer.channels[ch_index]

        # Handle layer preview mode
        if process_layer_preview(tree, mp, ch, layer, layer_ch, node):
            continue

        # Check if layer should be skipped
        skip_entirely, skip_channel = should_skip_layer(
            mp, layer, layer_ch, ch, merged_layer_ids, j, tree, nodes
        )
        if skip_entirely or skip_channel:
            if skip_entirely:
                continue
            if skip_channel:
                continue

        # Connect UV inputs
        connect_layer_uv_inputs(
            tree, mp, layer, node, uv_maps, tangents, bitangents, height_ch
        )

        # Connect texcoord inputs
        connect_layer_texcoord_inputs(tree, mp, layer, node)

        # Connect background layer
        connect_background_layer(
            tree, layer, node, ch, bg_rgb, bg_alpha, bg_height
        )

        # Merge process doesn't care with parents
        if not merged_layer_ids and layer.parent_idx != -1:
            continue

        # Connect channel IO
        channel_values = connect_layer_channel_io(
            tree, node, ch, io_names_dict, channel_values
        )

    # Reconnect modifier nodes
    rgb, alpha = reconnect_all_modifier_nodes(
        tree, ch, channel_values["rgb"], channel_values["alpha"]
    )
    channel_values["rgb"] = rgb
    channel_values["alpha"] = alpha

    # Process end linear
    end_linear = channel_nodes.get("end_linear")
    if end_linear and (end_linear.type != "GROUP" or end_linear.node_tree):
        if ch.type == "NORMAL":
            rgb, normal_no_bump = process_end_linear_normal(
                tree, ch, channel_values, channel_nodes, uv_maps, tangent, bitangent
            )
            channel_values["rgb"] = rgb
        else:
            channel_values["rgb"] = create_link(
                tree, channel_values["rgb"], end_linear.inputs[0]
            )[0]

    # Process clamp and backface
    rgb, alpha = process_clamp_and_backface(
        tree, ch, channel_values["rgb"], channel_values["alpha"], channel_nodes
    )
    channel_values["rgb"] = rgb
    channel_values["alpha"] = alpha

    # Process baked channel
    rgb, alpha, height, max_height, vdisp = process_baked_channel(
        tree, mp, ch, nodes, channel_values["rgb"], channel_values["alpha"],
        baked_uv_map, channel_values, channel_nodes
    )
    channel_values["rgb"] = rgb
    channel_values["alpha"] = alpha
    channel_values["height"] = height
    channel_values["max_height"] = max_height
    channel_values["vdisp"] = vdisp

    # Process baked vertex color
    rgb, alpha = process_baked_vcol(
        tree, mp, ch, nodes, channel_values["rgb"], channel_values["alpha"]
    )
    channel_values["rgb"] = rgb
    channel_values["alpha"] = alpha

    # Connect to tree end
    connect_channel_to_tree_end(
        tree, mp, ch,
        channel_values["rgb"],
        channel_values["alpha"],
        channel_values.get("height"),
        channel_values.get("max_height"),
        channel_values.get("vdisp")
    )


def _process_group_connections(tree, mp, nodes):
    """
    Process group layer connections and cleanup.

    Parameters:
        tree: The node tree.
        mp: The MPaint data from the tree.
        nodes: The nodes in the tree.
    """
    # List of last members
    last_members = []
    for layer in mp.layers:
        if not layer.enable:
            continue
        if is_bottom_member(layer, True):
            last_members.append(layer)

        # Remove unused input links
        node = tree.nodes.get(layer.group_node)
        if layer.type == "GROUP":
            remove_unused_group_node_connections(tree, layer, node)
        remove_all_prev_inputs(tree, layer, node)

    # Group stuff
    for layer in last_members:
        node = nodes.get(layer.group_node)

        cur_layer = layer
        cur_node = node

        # Dictionary of Outputs
        outs = {}
        for outp in node.outputs:
            outs[outp.name] = outp

        while True:
            # Get upper layer
            upper_idx, upper_layer = get_upper_neighbor(cur_layer)

            # Check if we've reached the top of the layer stack
            if upper_layer is None:
                break

            upper_node = nodes.get(upper_layer.group_node)

            # Connect
            if upper_layer.parent_idx == cur_layer.parent_idx:
                if upper_layer.enable:
                    for inp in upper_node.inputs:
                        if inp.name in outs:
                            o = create_link(tree, outs[inp.name], inp)
                            if inp.name in o:
                                outs[inp.name] = o[inp.name]
                        elif inp.name in upper_node.outputs:
                            outs[inp.name] = upper_node.outputs[inp.name]

                cur_layer = upper_layer
                cur_node = upper_node
            else:
                for output_name, outp in outs.items():
                    io_name = output_name + io_suffix["GROUP"]
                    if io_name in upper_node.inputs:
                        create_link(tree, outp, upper_node.inputs[io_name])

                break
