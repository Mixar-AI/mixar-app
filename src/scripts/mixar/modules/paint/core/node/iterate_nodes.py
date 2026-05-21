# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Functions for managing iterate nodes in parallax mapping.

This module contains functions for creating, deleting, and configuring
iterate nodes used in parallax occlusion mapping calculations.
"""

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...utils.blender_commons import (
    get_bpy_data,
    remove_datablock,
)
from ...utils.constants import (
    ITERATE_GROUP,
)
from ...utils.math_utils import (
    calculate_group_needed,
    calculate_parallax_group_depth,
    calculate_parallax_top_level_count,
)
from ..io.utils.connections import match_io_between_node_tree
from ..layer.layer_utils import get_root_parallax_channel
from ..subtree.get_subtree import get_displacement_max_height
from .create_nodes import create_essential_nodes


def create_iterate_group_nodes(iter_tree, match_io=False):
    """Create a group of iteration nodes for parallax mapping.

    Creates a new node group containing multiple iterate nodes based on the
    PARALLAX_DIVIDER constant. Optionally matches IO between the iteration tree
    and the group tree.

    Args:
        iter_tree: The iteration tree template to duplicate.
        match_io (bool): Whether to match IO between trees (default: False).

    Returns:
        The newly created group tree.
    """
    from ...utils.constants import PARALLAX_DIVIDER

    group_tree = get_bpy_data().node_groups.new(ITERATE_GROUP, 'ShaderNodeTree')
    create_essential_nodes(group_tree)

    for i in range(PARALLAX_DIVIDER):
        it = group_tree.nodes.new('ShaderNodeGroup')
        it.name = '_iterate_' + str(i)
        it.node_tree = iter_tree

    if match_io:
        match_io_between_node_tree(iter_tree, group_tree)

    return group_tree


def create_delete_iterate_nodes__(tree, num_of_iteration):
    """Create or delete iterate nodes using hierarchical grouping.

    Creates a hierarchical structure of iterate nodes organized by depth levels
    to handle the specified number of iterations efficiently. Removes excess nodes
    and groups when the iteration count decreases.

    Args:
        tree: The Blender node tree to modify.
        num_of_iteration (int): The number of iterations needed.
    """
    from ...utils.constants import PARALLAX_DIVIDER

    iter_tree = tree.nodes.get('_iterate').node_tree

    # Get group depth
    depth = calculate_parallax_group_depth(num_of_iteration)
    #print(depth)

    # Top level group needed
    #top_level_count = int(num_of_iteration / pow(PARALLAX_DIVIDER, depth))
    top_level_count = calculate_parallax_top_level_count(num_of_iteration)

    # Create group depth node
    counter = 0
    while True:
        ig = tree.nodes.get('_iterate_depth_' + str(counter))

        ig_found = False
        if ig: ig_found = True

        if not ig and counter < depth:
            ig = tree.nodes.new('ShaderNodeGroup')
            ig.name = '_iterate_depth_' + str(counter)
            #ig.node_tree = iter_group.node_tree

        if ig and counter >= depth:
            if ig.node_tree:
                remove_datablock(get_bpy_data().node_groups, ig.node_tree, user=ig, user_prop='node_tree')
            tree.nodes.remove(ig)

        if not ig_found and counter >= depth:
            break

        counter += 1

    # Fill group depth
    cur_tree = iter_tree
    for i in range(depth):
        ig = tree.nodes.get('_iterate_depth_' + str(i))
        if ig and not ig.node_tree:
            ig.node_tree = create_iterate_group_nodes(cur_tree, True)

        if ig and ig.node_tree:
            cur_tree = ig.node_tree

    # Create top level group
    top_level = tree.nodes.get('_iterate_depth_' + str(depth-1))
    if top_level:
        top_level_tree = top_level.node_tree
    else: top_level_tree = iter_tree

    counter = 0
    while True:
        it = tree.nodes.get('_iterate_' + str(counter))

        it_found = False
        if it: it_found = True

        if not it and counter < top_level_count:
            it = tree.nodes.new('ShaderNodeGroup')
            it.name = '_iterate_' + str(counter)

        if it:
            if counter >= top_level_count:
                tree.nodes.remove(it)
            elif it.node_tree != top_level_tree:
                it.node_tree = top_level_tree

        if not it_found and counter >= top_level_count:
            break

        counter += 1


def create_delete_iterate_nodes_(tree, num_of_iteration):
    """Create or delete iterate nodes using flat grouping (legacy method).

    Creates iterate nodes organized in flat groups to handle the specified number
    of iterations. This is an older method compared to the hierarchical approach.

    Args:
        tree: The Blender node tree to modify.
        num_of_iteration (int): The number of iterations needed.
    """
    iter_tree = tree.nodes.get('_iterate').node_tree

    # Calculate group needed
    group_needed = calculate_group_needed(num_of_iteration)

    # Create group
    iter_group = tree.nodes.get('_iterate_group_0')
    if not iter_group:
        iter_group = tree.nodes.new('ShaderNodeGroup')
        iter_group.node_tree = create_iterate_group_nodes(iter_tree, True)
        iter_group.name = '_iterate_group_0'

    counter = 0
    while True:
        ig = tree.nodes.get('_iterate_group_' + str(counter))

        ig_found = False
        if ig: ig_found = True

        if not ig and counter < group_needed:
            ig = tree.nodes.new('ShaderNodeGroup')
            ig.name = '_iterate_group_' + str(counter)
            ig.node_tree = iter_group.node_tree

        if ig and counter >= group_needed:
            tree.nodes.remove(ig)

        if not ig_found and counter >= group_needed:
            break

        counter += 1


def create_delete_iterate_nodes(tree, num_of_iteration):
    """Create or delete iterate nodes (simple flat method).

    Creates or removes iterate nodes in a simple flat structure without grouping.
    Each iteration gets its own node instance.

    Args:
        tree: The Blender node tree to modify.
        num_of_iteration (int): The number of iterations needed.
    """
    iter_tree = tree.nodes.get('_iterate').node_tree

    counter = 0
    while True:
        it = tree.nodes.get('_iterate_' + str(counter))

        it_found = False
        if it: it_found = True

        if not it and counter < num_of_iteration:
            it = tree.nodes.new('ShaderNodeGroup')
            it.name = '_iterate_' + str(counter)
            it.node_tree = iter_tree

        if it and counter >= num_of_iteration:
            tree.nodes.remove(it)

        if not it_found and counter >= num_of_iteration:
            break

        counter += 1


def set_relief_mapping_nodes(mp, node, img=None):
    """Configure relief mapping nodes for parallax occlusion mapping.

    Sets up the parameters for relief mapping including displacement height,
    reference plane, linear and binary search steps, and depth source image.
    Also configures iteration nodes for both linear and binary search loops.

    Args:
        mp: The MPaint root object.
        node: The relief mapping node to configure.
        img: Optional depth source image (default: None).
    """
    ch = get_root_parallax_channel(mp)

    # Set node parameters
    #node.inputs[0].default_value = ch.displacement_height_ratio
    node.inputs[0].default_value = get_displacement_max_height(ch)
    node.inputs[1].default_value = ch.parallax_ref_plane

    tree = node.node_tree

    linear_steps = tree.nodes.get('_linear_search_steps')
    linear_steps.outputs[0].default_value = float(ch.parallax_num_of_linear_samples)

    binary_steps = tree.nodes.get('_binary_search_steps')
    binary_steps.outputs[0].default_value = float(ch.parallax_num_of_binary_samples)

    if img:
        depth_source = tree.nodes.get('_depth_source')
        depth_from_tex = depth_source.node_tree.nodes.get('_depth_from_tex')
        depth_from_tex.image = img

    linear_loop = tree.nodes.get('_linear_search')
    create_delete_iterate_nodes(linear_loop.node_tree, ch.parallax_num_of_linear_samples)

    binary_loop = tree.nodes.get('_binary_search')
    create_delete_iterate_nodes(binary_loop.node_tree, ch.parallax_num_of_binary_samples)
