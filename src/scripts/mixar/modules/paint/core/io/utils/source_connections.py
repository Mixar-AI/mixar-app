# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from mathutils import Vector

from ......config.logging_config import get_logger
logger = get_logger(__name__)

from ....utils.blender_commons import get_user_preferences
from ....utils.common import get_channel_index, get_entity_input_name, get_mix_color_indices, get_write_height
from ....utils.constants import *
from ...element.modifier_utils import reconnect_all_modifier_nodes
from ..utils.io_utils import break_input_link, break_link, create_link
from ...layer.check_layers import check_need_prev_normal, get_channel_enabled, has_previous_layer_channels, is_layer_using_vector
from ...layer.layer_utils import (
    get_height_channel,
    get_root_height_channel,
    get_root_parallax_channel,
    get_transition_bump_channel,
    is_bottom_member,
)
from ...node.node_utils import (
    clean_essential_nodes,
    get_essential_node,
    is_normal_height_input_connected,
)
from ...subtree.get_subtree import get_mask_tree, get_source_tree, get_tree, get_upper_neighbor, has_channel_children
from ....procedural_materials.material_registry import is_custom_material

def reconnect_source_internal_nodes(layer):
    """
    Reconnect the internal nodes within a layer's source node tree.

    Sets up all connections within a layer's source tree, including the source node,
    color/alpha processing, linearization, Y-axis flipping, and modifier groups.
    Handles different layer types (IMAGE, VCOL, procedural textures, etc.) appropriately.

    Parameters:
        layer: The layer object containing source node references and configuration.

    Returns:
        None
    """
    tree = get_source_tree(layer)

    source = tree.nodes.get(layer.source)
    linear = tree.nodes.get(layer.linear)
    divider_alpha = tree.nodes.get(layer.divider_alpha)
    flip_y = tree.nodes.get(layer.flip_y)
    start = tree.nodes.get(TREE_START)
    # solid = tree.nodes.get(ONE_VALUE)
    end = tree.nodes.get(TREE_END)

    create_link(tree, start.outputs[0], source.inputs[0])

    if layer.type == "VORONOI" and layer.voronoi_feature == "N_SPHERE_RADIUS":
        rgb = source.outputs["Radius"]
    else:
        rgb = source.outputs[0]

    # Check if this is a custom procedural material

    is_custom = is_custom_material(layer.type)

    if layer.type == "MUSGRAVE" or is_custom:
        alpha = get_essential_node(tree, ONE_VALUE)[0]
    else:
        alpha = source.outputs[1]

    if divider_alpha:
        mixcol0, mixcol1, mixout = get_mix_color_indices(divider_alpha)
        rgb = create_link(tree, rgb, divider_alpha.inputs[mixcol0])[mixout]
        create_link(tree, alpha, divider_alpha.inputs[mixcol1])

    if linear:
        rgb = create_link(tree, rgb, linear.inputs[0])[0]

    if flip_y:
        rgb = create_link(tree, rgb, flip_y.inputs[0])[0]

    if not is_custom and layer.type not in {
        "IMAGE",
        "VCOL",
        "HEMI",
        "OBJECT_INDEX",
        "MUSGRAVE",
        "EDGE_DETECT",
        "AO",
    }:
        rgb_1 = source.outputs[1]
        alpha = get_essential_node(tree, ONE_VALUE)[0]
        alpha_1 = get_essential_node(tree, ONE_VALUE)[0]

        mod_group = tree.nodes.get(layer.mod_group)
        if mod_group:
            rgb, alpha = reconnect_all_modifier_nodes(
                tree, layer, rgb, alpha, mod_group
            )

        mod_group_1 = tree.nodes.get(layer.mod_group_1)
        if mod_group_1:
            rgb_1 = create_link(tree, rgb_1, mod_group_1.inputs[0])[0]
            alpha_1 = create_link(tree, alpha_1, mod_group_1.inputs[1])[1]

        create_link(tree, rgb_1, end.inputs[2])
        create_link(tree, alpha_1, end.inputs[3])

    if layer.type in {
        "IMAGE",
        "VCOL",
        "HEMI",
        "OBJECT_INDEX",
        "MUSGRAVE",
        "EDGE_DETECT",
        "AO",
    }:

        rgb, alpha = reconnect_all_modifier_nodes(tree, layer, rgb, alpha)

    create_link(tree, rgb, end.inputs[0])
    create_link(tree, alpha, end.inputs[1])

    # Clean unused essential nodes
    clean_essential_nodes(tree, exclude_texcoord=True, exclude_geometry=True)


def reconnect_channel_source_internal_nodes(channel, tree):
    """Reconnect the internal nodes within a channel's source group tree.

    Similar to reconnect_source_internal_nodes but for channel override sources.
    Sets up connections within a channel's source group including the source node,
    linearization, and modifier processing.

    Parameters:
        channel: The channel object containing source node references and configuration.
        tree: The node tree of the channel's source group.

    Returns:
        None
    """
    if not tree:
        return

    source = tree.nodes.get(channel.source) if hasattr(channel, 'source') else None
    linear = tree.nodes.get(channel.linear) if hasattr(channel, 'linear') else None
    start = tree.nodes.get(TREE_START)
    end = tree.nodes.get(TREE_END)

    if not source or not start or not end:
        return

    # Connect start to source
    if len(start.outputs) > 0 and len(source.inputs) > 0:
        create_link(tree, start.outputs[0], source.inputs[0])

    # Get RGB output
    if hasattr(channel, 'override_type') and channel.override_type == "VORONOI":
        if hasattr(channel, 'voronoi_feature') and channel.voronoi_feature == "N_SPHERE_RADIUS":
            rgb = source.outputs.get("Radius", source.outputs[0])
        else:
            rgb = source.outputs[0]
    else:
        rgb = source.outputs[0]

    # Alpha defaults to one
    alpha = get_essential_node(tree, ONE_VALUE)[0]

    # Process through linear
    if linear:
        rgb = create_link(tree, rgb, linear.inputs[0])[0]

    # Process through modifiers if any
    mod_group = tree.nodes.get(channel.mod_group) if hasattr(channel, 'mod_group') else None
    if mod_group:
        rgb, alpha = reconnect_all_modifier_nodes(tree, channel, rgb, alpha, mod_group)

    # Connect to end
    if len(end.inputs) > 0:
        create_link(tree, rgb, end.inputs[0])
    if len(end.inputs) > 1:
        create_link(tree, alpha, end.inputs[1])

    # Clean unused essential nodes
    clean_essential_nodes(tree, exclude_texcoord=True, exclude_geometry=True)
