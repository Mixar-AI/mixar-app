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

def reconnect_mask_modifier_nodes(tree, mod, start_value):
    """
    Reconnect nodes for a mask modifier based on its type.

    Creates appropriate node connections for different mask modifier types (INVERT, RAMP, or CURVE).
    The function processes the start_value through the modifier's nodes and returns the modified output.

    Parameters:
        tree: The node tree containing the modifier nodes.
        mod: The modifier object containing type and node references.
        start_value: The input socket or value to connect to the modifier.

    Returns:
        The output socket from the modifier nodes after processing.
    """

    value = start_value

    if mod.type == "INVERT":
        invert = tree.nodes.get(mod.invert)
        create_link(tree, value, invert.inputs[1])
        value = invert.outputs[0]

    elif mod.type == "RAMP":
        ramp = tree.nodes.get(mod.ramp)
        ramp_mix = tree.nodes.get(mod.ramp_mix)
        mixcol0, mixcol1, mixout = get_mix_color_indices(ramp_mix)

        create_link(tree, value, ramp.inputs[0])
        create_link(tree, value, ramp_mix.inputs[mixcol0])
        create_link(tree, ramp.outputs[0], ramp_mix.inputs[mixcol1])

        value = ramp_mix.outputs[mixout]

    elif mod.type == "CURVE":
        curve = tree.nodes.get(mod.curve)
        create_link(tree, value, curve.inputs[1])
        value = curve.outputs[0]

    return value


def reconnect_mask_internal_nodes(mask, mask_source_index=0):
    """
    Reconnect the internal nodes within a mask's node tree.

    Sets up all internal node connections for a mask, including source nodes, color channel
    separation, linearization, and modifiers. Connects from the tree start node through
    all processing nodes to the tree end node.

    Parameters:
        mask: The mask object containing node references and configuration.
        mask_source_index (int, optional): The output index from the source node to use. Default is 0.

    Returns:
        None
    """

    tree = get_mask_tree(mask)

    baked_source = tree.nodes.get(mask.baked_source)
    if baked_source and mask.use_baked:
        source = baked_source
    else:
        source = tree.nodes.get(mask.source)
    linear = tree.nodes.get(mask.linear)
    separate_color_channels = tree.nodes.get(mask.separate_color_channels)
    start = tree.nodes.get(TREE_START)
    end = tree.nodes.get(TREE_END)

    if mask.type == "MODIFIER" and mask.modifier_type in {"INVERT", "CURVE"}:
        create_link(tree, start.outputs[0], source.inputs[1])
    elif mask.use_baked or mask.type not in {
        "VCOL",
        "HEMI",
        "OBJECT_INDEX",
        "BACKFACE",
        "EDGE_DETECT",
        "AO",
    }:
        create_link(tree, start.outputs[0], source.inputs[0])

    val = source.outputs[mask_source_index]

    if mask.source_input in {"R", "G", "B"}:
        separate_color_channels_outputs = create_link(
            tree, val, separate_color_channels.inputs[0]
        )
        if mask.source_input == "R":
            val = separate_color_channels_outputs[0]
        elif mask.source_input == "G":
            val = separate_color_channels_outputs[1]
        elif mask.source_input == "B":
            val = separate_color_channels_outputs[2]

    if linear:
        val = create_link(tree, val, linear.inputs[0])[0]

    for mod in mask.modifiers:
        val = reconnect_mask_modifier_nodes(tree, mod, val)

    create_link(tree, val, end.inputs[0])


