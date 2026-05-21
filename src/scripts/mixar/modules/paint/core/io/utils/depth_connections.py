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

def reconnect_depth_layer_nodes(group_tree, parallax_ch, parallax):
    """
    Reconnect nodes for depth/height layers used in parallax mapping.

    Sets up connections for all layers that contribute height/depth information to the
    parallax effect. Processes each layer in the parallax channel and connects their
    height outputs to the appropriate parallax depth processing nodes.

    Parameters:
        group_tree: The main node tree containing the parallax system.
        parallax_ch: The parallax channel configuration.
        parallax: The parallax group node.

    Returns:
        None
    """

    mp = group_tree.mp

    depth_source_0 = parallax.node_tree.nodes.get("_depth_source_0")
    tree = depth_source_0.node_tree

    start = tree.nodes.get(TREE_START)
    end = tree.nodes.get(TREE_END)

    unpack = tree.nodes.get("_unpack")
    normalize = tree.nodes.get("_normalize")

    if parallax_ch.enable_smooth_bump:
        io_height_name = parallax_ch.name + io_suffix["HEIGHT_ONS"]
    else:
        io_height_name = parallax_ch.name + io_suffix["HEIGHT"]

    io_alpha_name = parallax_ch.name + io_suffix["ALPHA"]
    if parallax_ch.enable_smooth_bump:
        io_height_alpha_name = (
            parallax_ch.name + io_suffix["HEIGHT_ONS"] + io_suffix["ALPHA"]
        )
    else:
        io_height_alpha_name = (
            parallax_ch.name + io_suffix["HEIGHT"] + io_suffix["ALPHA"]
        )

    height = start.outputs["base"]

    parallax_ch_idx = get_channel_index(parallax_ch)

    for i, layer in reversed(list(enumerate(mp.layers))):

        # if mp.disable_quick_toggle and (not layer.enable or not layer.channels[parallax_ch_idx].enable): continue
        if not layer.enable or not layer.channels[parallax_ch_idx].enable:
            continue

        node = tree.nodes.get(layer.depth_group_node)

        uv_names = []
        if layer.texcoord_type == "UV":
            uv_names.append(layer.uv_name)

        for mask in layer.masks:
            if mask.texcoord_type == "UV" and mask.uv_name not in uv_names:
                uv_names.append(mask.uv_name)

        for uv_name in uv_names:
            inp = node.inputs.get(uv_name + io_suffix["UV"])
            uv = mp.uvs.get(uv_name)
            if not uv:
                continue
            current_uv = tree.nodes.get(uv.parallax_current_uv)

            if inp and current_uv:
                create_link(tree, current_uv.outputs[0], inp)

        for tc in texcoord_lists:
            inp = node.inputs.get(TEXCOORD_IO_PREFIX + tc)
            if not inp:
                continue
            current_uv = tree.nodes.get(
                PARALLAX_CURRENT_PREFIX + TEXCOORD_IO_PREFIX + tc
            )
            if not current_uv:
                continue
            create_link(tree, current_uv.outputs[0], inp)

        if layer.parent_idx != -1:
            continue

        height = create_link(tree, height, node.inputs[io_height_name])[io_height_name]

    if parallax_ch.enable_smooth_bump:
        height = create_link(tree, height, unpack.inputs[0])[0]

    create_link(tree, height, normalize.inputs[0])
    create_link(tree, normalize.outputs[0], end.inputs["depth_from_tex"])

    # List of last members
    last_members = []
    for layer in mp.layers:
        if not layer.enable:
            continue
        if is_bottom_member(layer, True):
            last_members.append(layer)

        # Remove unused input links
        node = tree.nodes.get(layer.depth_group_node)
        if layer.type == "GROUP":
            remove_unused_group_node_connections(
                tree, layer, node
            )  # , height_only=True)
        remove_all_prev_inputs(tree, layer, node)  # , height_only=True)

    # Group stuff
    for layer in last_members:

        node = tree.nodes.get(layer.depth_group_node)

        cur_layer = layer
        cur_node = node

        io_alpha = cur_node.outputs.get(io_alpha_name)
        io_height = cur_node.outputs.get(io_height_name)
        io_height_alpha = cur_node.outputs.get(io_height_alpha_name)

        while True:
            # Get upper layer
            upper_idx, upper_layer = get_upper_neighbor(cur_layer)
            upper_node = tree.nodes.get(upper_layer.depth_group_node)

            # Connect
            if upper_layer.parent_idx == cur_layer.parent_idx:

                # if not mp.disable_quick_toggle or upper_layer.enable:
                if upper_layer.enable:

                    if io_alpha_name in upper_node.inputs:
                        if io_alpha:
                            io_alpha = create_link(
                                tree, io_alpha, upper_node.inputs[io_alpha_name]
                            )[io_alpha_name]
                        else:
                            io_alpha = upper_node.outputs[io_alpha_name]

                    if io_height_name in upper_node.inputs:
                        if io_height:
                            io_height = create_link(
                                tree, io_height, upper_node.inputs[io_height_name]
                            )[io_height_name]
                        else:
                            io_height = upper_node.outputs[io_height_name]

                    if io_height_alpha_name in upper_node.inputs:
                        if io_height_alpha:
                            io_height_alpha = create_link(
                                tree,
                                io_height_alpha,
                                upper_node.inputs[io_height_alpha_name],
                            )[io_height_alpha_name]
                        else:
                            io_height_alpha = upper_node.outputs[io_height_alpha_name]

                cur_layer = upper_layer
                cur_node = upper_node

            else:

                io_name = io_alpha_name + io_suffix["GROUP"]
                if io_alpha and io_name in upper_node.inputs:
                    # create_link(tree, cur_node.outputs[io_alpha_name], upper_node.inputs[io_name])
                    create_link(tree, io_alpha, upper_node.inputs[io_name])

                io_name = io_height_name + io_suffix["GROUP"]
                if io_height and io_name in upper_node.inputs:
                    create_link(tree, io_height, upper_node.inputs[io_name])

                io_name = io_height_alpha_name + io_suffix["GROUP"]
                if io_height_alpha and io_name in upper_node.inputs:
                    # create_link(tree, cur_node.outputs[io_height_alpha_name], upper_node.inputs[io_name])
                    create_link(tree, io_height_alpha, upper_node.inputs[io_name])

                break


def remove_unused_group_node_connections(tree, layer, node):  # , height_only=False):
    """
    Remove unused connections from a group layer node.

    Disconnects inputs from channels that are not used by any child layers within the group.
    This keeps the node tree clean and prevents unnecessary data flow through unused channels.

    Parameters:
        tree: The node tree containing the group node.
        layer: The group layer object.
        node: The group node to clean up connections from.

    Returns:
        None
    """

    mp = layer.id_data.mp
    # node = tree.nodes.get(layer.group_node)

    if layer.type != "GROUP":
        return

    for i, ch in enumerate(layer.channels):
        root_ch = mp.channels[i]
        if has_channel_children(layer, root_ch):
            continue

        io_name = root_ch.name + io_suffix["HEIGHT"] + io_suffix["GROUP"]
        if io_name in node.inputs:
            break_input_link(tree, node.inputs[io_name])

        io_name = (
            root_ch.name + io_suffix["HEIGHT"] + io_suffix["ALPHA"] + io_suffix["GROUP"]
        )
        if io_name in node.inputs:
            break_input_link(tree, node.inputs[io_name])

        # if height_only: continue

        io_name = root_ch.name + io_suffix["GROUP"]
        if io_name in node.inputs:
            # Should always fill normal input
            # geometry = tree.nodes.get(GEOMETRY)
            # if root_ch.type == 'NORMAL' and geometry:
            #    create_link(tree, geometry.outputs['Normal'], node.inputs[io_name])
            # else:
            break_input_link(tree, node.inputs[io_name])

        io_name = root_ch.name + io_suffix["ALPHA"] + io_suffix["GROUP"]
        if io_name in node.inputs:
            break_input_link(tree, node.inputs[io_name])

        if root_ch.enable_smooth_bump:

            for letter in nsew_letters:
                io_name = (
                    root_ch.name
                    + io_suffix["HEIGHT_" + letter.upper()]
                    + io_suffix["GROUP"]
                )
                if io_name in node.inputs:
                    break_input_link(tree, node.inputs[io_name])

                io_name = (
                    root_ch.name
                    + io_suffix["HEIGHT_" + letter.upper()]
                    + io_suffix["ALPHA"]
                    + io_suffix["GROUP"]
                )
                if io_name in node.inputs:
                    break_input_link(tree, node.inputs[io_name])


