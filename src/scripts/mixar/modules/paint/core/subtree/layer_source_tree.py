# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer source tree operations for texture painting.

This module contains functions for enabling and disabling layer source trees,
which handle layer-specific texture processing, modifier management,
and UV neighbor node configuration.
"""

from ...utils.blender_commons import get_bpy_data
from ...utils.constants import LAYERGROUP_PREFIX
from ..element.update_uv import set_uv_neighbor_resolution
from ..io.arrangements.layer_arrangements import rearrange_layer_nodes
from ..io.connections.layer_connections import reconnect_layer_nodes
from ..io.utils.update_io import refresh_source_tree_ios
from ..layer.check_layers import get_channel_enabled, is_height_process_needed
from ..lib.lib import NEIGHBOR_FAKE
from ..lib.lib_operations import get_neighbor_uv_tree_name
from ..modifier.modifier_commons import check_modifier_nodes
from ..node.create_nodes import create_essential_nodes, new_node, replace_new_node
from ..node.node_utils import copy_node_props, remove_node
from ..subtree.update_subtree import move_mod_group
from .get_subtree import get_tree


def enable_layer_source_tree(layer, rearrange=False):
    """Enable and create a source tree for a layer.

    Creates a node group for the layer source, sets up inputs/outputs,
    transfers source and related nodes from the layer tree to the new source tree,
    and configures UV neighbor nodes as needed.

    Args:
        layer: The layer object to enable source tree for.
        rearrange (bool, optional): If True, reconnects and rearranges layer nodes
            after enabling the source tree. Defaults to False.

    Returns:
        None
    """
    # Check if source tree is already available
    if layer.type in {"BACKGROUND", "COLOR"}:
        return
    if (
        layer.type not in {"VCOL", "HEMI", "OBJECT_INDEX", "BACKFACE", "EDGE_DETECT"}
        and layer.source_group != ""
    ):
        return

    layer_tree = get_tree(layer)

    if layer.type not in {
        "VCOL",
        "GROUP",
        "HEMI",
        "OBJECT_INDEX",
        "BACKFACE",
        "EDGE_DETECT",
    }:
        # Get current source for reference
        source_ref = layer_tree.nodes.get(layer.source)
        linear_ref = layer_tree.nodes.get(layer.linear)
        flip_y_ref = layer_tree.nodes.get(layer.flip_y)
        divider_alpha_ref = layer_tree.nodes.get(layer.divider_alpha)

        # Create source tree
        source_tree = get_bpy_data().node_groups.new(
            LAYERGROUP_PREFIX + layer.name + " Source", "ShaderNodeTree"
        )

        create_essential_nodes(source_tree, True)

        refresh_source_tree_ios(source_tree, layer.type)

        # Copy source from reference
        source = new_node(source_tree, layer, "source", source_ref.bl_idname)
        copy_node_props(source_ref, source)

        if linear_ref:
            linear = new_node(source_tree, layer, "linear", linear_ref.bl_idname)
            copy_node_props(linear_ref, linear)

        if flip_y_ref:
            flip_y = new_node(source_tree, layer, "flip_y", flip_y_ref.bl_idname)
            copy_node_props(flip_y_ref, flip_y)

        if divider_alpha_ref:
            divider_alpha = new_node(
                source_tree, layer, "divider_alpha", divider_alpha_ref.bl_idname
            )
            copy_node_props(divider_alpha_ref, divider_alpha)

        # Create source node group
        source_group = new_node(
            layer_tree, layer, "source_group", "ShaderNodeGroup", "source_group"
        )
        source_n = new_node(
            layer_tree, layer, "source_n", "ShaderNodeGroup", "source_n"
        )
        source_s = new_node(
            layer_tree, layer, "source_s", "ShaderNodeGroup", "source_s"
        )
        source_e = new_node(
            layer_tree, layer, "source_e", "ShaderNodeGroup", "source_e"
        )
        source_w = new_node(
            layer_tree, layer, "source_w", "ShaderNodeGroup", "source_w"
        )

        source_group.node_tree = source_tree
        source_n.node_tree = source_tree
        source_s.node_tree = source_tree
        source_e.node_tree = source_tree
        source_w.node_tree = source_tree

        # Remove previous source
        layer_tree.nodes.remove(source_ref)
        if linear_ref:
            layer_tree.nodes.remove(linear_ref)
        if flip_y_ref:
            layer_tree.nodes.remove(flip_y_ref)
        if divider_alpha_ref:
            layer_tree.nodes.remove(divider_alpha_ref)

        # Bring modifiers to source tree
        if layer.type in {"IMAGE", "MUSGRAVE"}:
            for mod in layer.modifiers:
                check_modifier_nodes(mod, source_tree, layer_tree)
        else:
            move_mod_group(layer, layer_tree, source_tree)

    # Create uv neighbor
    if layer.type in {"VCOL", "HEMI", "EDGE_DETECT"}:
        uv_neighbor = replace_new_node(
            layer_tree,
            layer,
            "uv_neighbor",
            "ShaderNodeGroup",
            "Neighbor UV",
            NEIGHBOR_FAKE,
            hard_replace=True,
        )
        if layer.type == "VCOL":
            uv_neighbor_1 = replace_new_node(
                layer_tree,
                layer,
                "uv_neighbor_1",
                "ShaderNodeGroup",
                "Neighbor UV 1",
                NEIGHBOR_FAKE,
                hard_replace=True,
            )
    elif layer.type not in {"GROUP", "OBJECT_INDEX", "BACKFACE"}:
        uv_neighbor = replace_new_node(
            layer_tree,
            layer,
            "uv_neighbor",
            "ShaderNodeGroup",
            "Neighbor UV",
            get_neighbor_uv_tree_name(layer.texcoord_type, entity=layer),
            hard_replace=True,
        )
        set_uv_neighbor_resolution(layer, uv_neighbor)

    if rearrange:
        # Reconnect outside nodes
        reconnect_layer_nodes(layer)

        # Rearrange nodes
        rearrange_layer_nodes(layer)


def disable_layer_source_tree(layer, rearrange=True, force=False):
    """Disable and remove the layer source tree, restoring nodes to the layer tree.

    Converts layer source nodes back from the source tree group to individual nodes
    in the layer tree, transfers modifiers back, and cleans up all associated
    group and UV neighbor nodes.

    Args:
        layer: The layer object to disable source tree for.
        rearrange (bool, optional): If True, reconnects and rearranges layer nodes
            after disabling the source tree. Defaults to True.
        force (bool, optional): If True, forces disabling even if smooth bump
            is active for the layer. Defaults to False.

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
                and is_height_process_needed(layer)
            ):
                smooth_bump_ch = root_ch

        if (
            layer.type
            not in {"VCOL", "HEMI", "OBJECT_INDEX", "BACKFACE", "EDGE_DETECT"}
            and layer.source_group == ""
        ) or smooth_bump_ch:
            return

    layer_tree = get_tree(layer)

    if force or layer.type not in {
        "VCOL",
        "HEMI",
        "OBJECT_INDEX",
        "BACKFACE",
        "EDGE_DETECT",
    }:
        source_group = layer_tree.nodes.get(layer.source_group)
        if source_group:
            source_ref = source_group.node_tree.nodes.get(layer.source)
            linear_ref = source_group.node_tree.nodes.get(layer.linear)
            flip_y_ref = source_group.node_tree.nodes.get(layer.flip_y)
            divider_alpha_ref = source_group.node_tree.nodes.get(layer.divider_alpha)

            # Create new source
            source = new_node(layer_tree, layer, "source", source_ref.bl_idname)
            copy_node_props(source_ref, source)

            if linear_ref:
                linear = new_node(layer_tree, layer, "linear", linear_ref.bl_idname)
                copy_node_props(linear_ref, linear)

            if flip_y_ref:
                flip_y = new_node(layer_tree, layer, "flip_y", flip_y_ref.bl_idname)
                copy_node_props(flip_y_ref, flip_y)

            if divider_alpha_ref:
                divider_alpha = new_node(
                    layer_tree, layer, "divider_alpha", divider_alpha_ref.bl_idname
                )
                copy_node_props(divider_alpha_ref, divider_alpha)

            # Bring back layer modifier to original tree
            if layer.type in {"IMAGE", "MUSGRAVE"}:
                for mod in layer.modifiers:
                    check_modifier_nodes(mod, layer_tree, source_group.node_tree)
            else:
                move_mod_group(layer, source_group.node_tree, layer_tree)

            # Remove previous source
            remove_node(layer_tree, layer, "source_group")
            remove_node(layer_tree, layer, "source_n")
            remove_node(layer_tree, layer, "source_s")
            remove_node(layer_tree, layer, "source_e")
            remove_node(layer_tree, layer, "source_w")

    remove_node(layer_tree, layer, "uv_neighbor")
    remove_node(layer_tree, layer, "uv_neighbor_1")

    if rearrange:
        # Reconnect outside nodes
        reconnect_layer_nodes(layer)

        # Rearrange nodes
        rearrange_layer_nodes(layer)
