# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel source tree operations for texture painting.

This module contains functions for enabling and disabling channel source trees,
which handle channel-specific texture processing and UV neighbor management.
"""

from ...utils.blender_commons import get_bpy_data
from ...utils.constants import LAYERGROUP_PREFIX
from ..element.update_uv import set_uv_neighbor_resolution
from ..io.arrangements.layer_arrangements import rearrange_layer_nodes
from ..io.connections.layer_connections import reconnect_layer_nodes
from ..io.utils.update_io import refresh_source_tree_ios
from ..layer.check_layers import get_channel_enabled
from ..lib.lib import NEIGHBOR_FAKE
from ..lib.lib_operations import get_neighbor_uv_tree_name
from ..node.create_nodes import create_essential_nodes, new_node, replace_new_node
from ..node.node_utils import copy_node_props, remove_node
from .get_subtree import get_tree


def enable_channel_source_tree(layer, root_ch, ch, rearrange=False):
    """Enable and create a source tree for a channel override.

    Creates a node group for the channel source, sets up inputs/outputs,
    and transfers source nodes from the layer tree to the new source tree.

    Args:
        layer: The layer object containing the channel.
        root_ch: The root channel object from mp.channels.
        ch: The channel object to enable source tree for.
        rearrange (bool, optional): If True, reconnects and rearranges layer nodes
            after enabling the source tree. Defaults to False.

    Returns:
        None
    """
    # if not ch.override: return

    if ch.source_group != "":
        return

    layer_tree = get_tree(layer)

    if ch.override_type not in {"VCOL", "HEMI", "DEFAULT"}:

        # Get current source for reference
        source_ref = layer_tree.nodes.get(ch.source)
        linear_ref = layer_tree.nodes.get(ch.linear)

        if not source_ref:
            return

        # Create source tree
        source_tree = get_bpy_data().node_groups.new(
            LAYERGROUP_PREFIX + root_ch.name + " Source", "ShaderNodeTree"
        )

        create_essential_nodes(source_tree, True)

        refresh_source_tree_ios(source_tree, ch.override_type)

        # Copy source from reference
        source = new_node(source_tree, ch, "source", source_ref.bl_idname)
        copy_node_props(source_ref, source)

        # Copy linear node from reference
        if linear_ref:
            linear = new_node(source_tree, ch, "linear", linear_ref.bl_idname)
            copy_node_props(linear_ref, linear)

        # Create source node group
        source_group = new_node(
            layer_tree, ch, "source_group", "ShaderNodeGroup", "source_group"
        )
        source_n = new_node(layer_tree, ch, "source_n", "ShaderNodeGroup", "source_n")
        source_s = new_node(layer_tree, ch, "source_s", "ShaderNodeGroup", "source_s")
        source_e = new_node(layer_tree, ch, "source_e", "ShaderNodeGroup", "source_e")
        source_w = new_node(layer_tree, ch, "source_w", "ShaderNodeGroup", "source_w")

        source_group.node_tree = source_tree
        source_n.node_tree = source_tree
        source_s.node_tree = source_tree
        source_e.node_tree = source_tree
        source_w.node_tree = source_tree

        layer_tree.nodes.remove(source_ref)
        if linear_ref:
            layer_tree.nodes.remove(linear_ref)

    # Create uv neighbor
    if ch.override_type in {"VCOL", "HEMI"}:
        uv_neighbor = replace_new_node(
            layer_tree,
            ch,
            "uv_neighbor",
            "ShaderNodeGroup",
            "Neighbor UV",
            NEIGHBOR_FAKE,
            hard_replace=True,
        )
    # else:
    elif ch.override_type not in {"DEFAULT"}:
        uv_neighbor = replace_new_node(
            layer_tree,
            ch,
            "uv_neighbor",
            "ShaderNodeGroup",
            "Neighbor UV",
            get_neighbor_uv_tree_name(layer.texcoord_type, entity=layer),
            hard_replace=True,
        )
        set_uv_neighbor_resolution(ch, uv_neighbor)

    if rearrange:
        # Reconnect outside nodes
        reconnect_layer_nodes(layer)

        # Rearrange nodes
        rearrange_layer_nodes(layer)


def disable_channel_source_tree(layer, root_ch, ch, rearrange=True, force=False):
    """Disable and remove the channel source tree, restoring nodes to the layer tree.

    Converts channel source nodes back from the source tree group to individual nodes
    in the layer tree, and cleans up all associated group and UV neighbor nodes.

    Args:
        layer: The layer object containing the channel.
        root_ch: The root channel object from mp.channels.
        ch: The channel object to disable source tree for.
        rearrange (bool, optional): If True, reconnects and rearranges layer nodes
            after disabling the source tree. Defaults to True.
        force (bool, optional): If True, forces disabling even if smooth bump
            is active. Defaults to False.

    Returns:
        None
    """
    mp = layer.id_data.mp

    # Check if fine bump map is used on some of layer channels
    if not force:
        smooth_bump_ch = None
        for i, root_ch in enumerate(mp.channels):
            if (
                root_ch.type == "NORMAL"
                and root_ch.enable_smooth_bump
                and get_channel_enabled(layer.channels[i], layer, root_ch)
            ):
                smooth_bump_ch = root_ch

        if (ch.override_type not in {"DEFAULT"} and ch.source_group == "") or (
            not ch.override and smooth_bump_ch
        ):
            return

    layer_tree = get_tree(layer)
    if not layer_tree:
        return

    # if ch.override_type not in {'DEFAULT'}:
    source_group = layer_tree.nodes.get(ch.source_group)
    if source_group:
        source_ref = source_group.node_tree.nodes.get(ch.source)
        linear_ref = source_group.node_tree.nodes.get(ch.linear)

        # Create new source
        source = new_node(layer_tree, ch, "source", source_ref.bl_idname)
        copy_node_props(source_ref, source)

        # Create new linear
        if linear_ref:
            linear = new_node(layer_tree, ch, "linear", linear_ref.bl_idname)
            copy_node_props(linear_ref, linear)

    # Remove previous source
    remove_node(layer_tree, ch, "source_group")
    remove_node(layer_tree, ch, "source_n")
    remove_node(layer_tree, ch, "source_s")
    remove_node(layer_tree, ch, "source_e")
    remove_node(layer_tree, ch, "source_w")

    remove_node(layer_tree, ch, "uv_neighbor")
    # remove_node(layer_tree, ch, 'uv_neighbor_1')

    if rearrange:
        # Reconnect outside nodes
        reconnect_layer_nodes(layer)

        # Rearrange nodes
        rearrange_layer_nodes(layer)
