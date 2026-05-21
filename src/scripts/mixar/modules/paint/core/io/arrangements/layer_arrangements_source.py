# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Source tree and transition bump node arrangement functions.

This module handles the arrangement of source tree nodes and transition
bump nodes for layers and channels.
"""

from mathutils import Vector

from ....utils.constants import (
    ONE_VALUE,
    TREE_END,
    TREE_START,
    ZERO_VALUE,
)
from ...node.loc import check_set_node_loc
from ...subtree.get_subtree import get_channel_source_tree, get_source_tree


def rearrange_source_tree_nodes(layer):
    """Arrange nodes in the source tree of a layer.

    Positions source nodes, mapping nodes, modifier groups, and utility nodes
    (ONE_VALUE, ZERO_VALUE) in a horizontal layout with appropriate spacing.

    Args:
        layer: The layer object whose source tree nodes will be arranged.

    Returns:
        None
    """
    # Import here to avoid circular imports
    from .layer_arrangements import arrange_modifier_nodes

    source_tree = get_source_tree(layer)

    loc = Vector((0, 0))

    if check_set_node_loc(source_tree, TREE_START, loc):
        loc.x += 180

    loc.y -= 300
    if check_set_node_loc(source_tree, ONE_VALUE, loc):
        loc.y -= 90
    check_set_node_loc(source_tree, ZERO_VALUE, loc)

    loc.y = 0
    bookmark_x = loc.x

    if check_set_node_loc(source_tree, layer.source, loc):
        loc.x += 280

    if layer.baked_source != '':
        loc.x = bookmark_x
        loc.y -= 320
        check_set_node_loc(source_tree, layer.baked_source, loc)
        loc.x += 280
        loc.y = 0

    if check_set_node_loc(source_tree, layer.divider_alpha, loc):
        loc.x += 200

    if check_set_node_loc(source_tree, layer.linear, loc):
        loc.x += 200

    if check_set_node_loc(source_tree, layer.flip_y, loc):
        loc.x += 200

    if layer.type in {'IMAGE', 'VCOL', 'MUSGRAVE'}:
        arrange_modifier_nodes(source_tree, layer, loc)
    else:
        if check_set_node_loc(source_tree, layer.mod_group, loc, True):
            mod_group = source_tree.nodes.get(layer.mod_group)
            arrange_modifier_nodes(mod_group.node_tree, layer, loc=Vector((0, 0)))
            loc.y -= 40
        if check_set_node_loc(source_tree, layer.mod_group_1, loc, True):
            loc.y += 40
            loc.x += 150

    check_set_node_loc(source_tree, TREE_END, loc)


def rearrange_channel_source_tree_nodes(layer, ch):
    """Arrange nodes in a channel's source tree.

    Positions channel-specific source nodes, linear conversion nodes, and utility
    nodes in a horizontal layout.

    Args:
        layer: The layer containing the channel.
        ch: The channel object whose source tree nodes will be arranged.

    Returns:
        None
    """
    source_tree = get_channel_source_tree(ch, layer)

    loc = Vector((0, 0))

    if check_set_node_loc(source_tree, TREE_START, loc):
        loc.x += 180

    loc.y -= 300
    if check_set_node_loc(source_tree, ONE_VALUE, loc):
        loc.y -= 90
    check_set_node_loc(source_tree, ZERO_VALUE, loc)

    loc.y = 0

    if check_set_node_loc(source_tree, ch.source, loc):
        loc.x += 280

    if check_set_node_loc(source_tree, ch.linear, loc):
        loc.x += 200

    check_set_node_loc(source_tree, TREE_END, loc)


def rearrange_transition_bump_nodes(tree, ch, loc):
    """Arrange transition bump nodes for a channel.

    Positions nodes related to transition bump effects including inverse,
    intensity multiplier, and falloff nodes.

    Args:
        tree: The node tree containing the transition bump nodes.
        ch: The channel object containing transition bump node references.
        loc (Vector): The starting location for arranging nodes (modified in place).

    Returns:
        None
    """
    ori_x = loc.x

    if check_set_node_loc(tree, ch.tb_inverse, loc):
        loc.x += 170.0

    if check_set_node_loc(tree, ch.tb_intensity_multiplier, loc):
        loc.x += 170.0

    save_x = loc.x
    loc.x = ori_x

    loc.y -= 170

    if check_set_node_loc(tree, ch.tb_falloff, loc):
        loc.y -= 150

    loc.x = save_x
