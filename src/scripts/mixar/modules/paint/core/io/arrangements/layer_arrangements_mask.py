# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mask node arrangement functions.

This module handles the arrangement of mask-related nodes including
mask sources, modifiers, and tree structure.
"""

from mathutils import Vector

from ....utils.constants import TREE_END, TREE_START
from ...node.loc import check_set_node_loc
from ...subtree.get_subtree import get_mask_tree


def arrange_mask_modifier_nodes(tree, mask, loc):
    """Arrange modifier nodes for a mask in the node tree.

    Positions mask modifier nodes (invert, ramp, curve, etc.) horizontally
    from the given location.

    Args:
        tree: The node tree containing the mask modifier nodes.
        mask: The mask object containing modifiers to arrange.
        loc (Vector): The starting location for arranging nodes (modified in place).

    Returns:
        Vector: The updated location after arranging all modifier nodes.
    """
    for m in mask.modifiers:

        if m.type == "INVERT":
            if check_set_node_loc(tree, m.invert, loc):
                loc.x += 170.0

        elif m.type == "RAMP":
            if check_set_node_loc(tree, m.ramp, loc):
                loc.x += 265.0

            if check_set_node_loc(tree, m.ramp_mix, loc):
                loc.x += 170.0

        elif m.type == "CURVE":
            if check_set_node_loc(tree, m.curve, loc):
                loc.x += 265.0

    return loc


def rearrange_mask_tree_nodes(mask):
    """Arrange all nodes in a mask's node tree.

    Positions source nodes, mapping nodes, linear conversion, color separation,
    and modifier nodes in a horizontal layout.

    Args:
        mask: The mask object whose tree nodes will be arranged.

    Returns:
        None
    """
    tree = get_mask_tree(mask)
    loc = Vector((0, 0))

    if check_set_node_loc(tree, TREE_START, loc):
        loc.x += 180

    if check_set_node_loc(tree, mask.baked_source, loc):
        loc.y -= 270

    if check_set_node_loc(tree, mask.source, loc):
        loc.x += 280

    if mask.baked_source != "":
        loc.y = 0

    if check_set_node_loc(tree, mask.linear, loc):
        loc.x += 180

    if check_set_node_loc(tree, mask.separate_color_channels, loc):
        loc.x += 180

    arrange_mask_modifier_nodes(tree, mask, loc)

    if check_set_node_loc(tree, TREE_END, loc):
        loc.x += 180
