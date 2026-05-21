# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parallax and depth node arrangement functions.

This module handles the arrangement of parallax-related nodes including depth
groups, iteration nodes, and UV mixing nodes.
"""

from mathutils import Vector

from ....utils.constants import (
    PARALLAX,
    PARALLAX_CURRENT_MIX_PREFIX,
    PARALLAX_CURRENT_PREFIX,
    PARALLAX_DELTA_PREFIX,
    PARALLAX_MIX_PREFIX,
    TEXCOORD_IO_PREFIX,
    TREE_END,
    TREE_START,
    texcoord_lists,
)
from ...layer.layer_utils import get_root_parallax_channel
from ...node.loc import check_set_node_loc
from ...subtree.get_subtree import get_list_of_parent_ids


def rearrange_depth_layer_nodes(group_tree):
    """Arrange depth layer nodes for parallax effects.

    Positions layer depth group nodes vertically based on their parent hierarchy,
    followed by normalize and unpack nodes.

    Args:
        group_tree: The group node tree containing parallax and depth nodes.

    Returns:
        None
    """
    mp = group_tree.mp

    parallax_ch = get_root_parallax_channel(mp)
    if not parallax_ch:
        return

    parallax = group_tree.nodes.get(PARALLAX)
    if not parallax:
        return

    depth_source_0 = parallax.node_tree.nodes.get("_depth_source_0")
    tree = depth_source_0.node_tree

    start = tree.nodes.get(TREE_START)

    loc = start.location.copy()
    loc.x += 200

    # Layer nodes
    for i, t in enumerate(reversed(mp.layers)):

        parent_ids = get_list_of_parent_ids(t)

        loc.y = len(parent_ids) * -250

        if check_set_node_loc(tree, t.depth_group_node, loc):
            loc.x += 200

    if check_set_node_loc(tree, "_normalize", loc):
        loc.y -= 170

    if check_set_node_loc(tree, "_unpack", loc):
        loc.x += 200

    check_set_node_loc(tree, TREE_END, loc)


def rearrange_parallax_iteration(tree, prefix):
    """Arrange parallax iteration nodes in sequence.

    Positions numbered iteration nodes (prefix0, prefix1, etc.) horizontally
    between TREE_START and TREE_END nodes.

    Args:
        tree: The node tree containing parallax iteration nodes.
        prefix (str): The prefix for iteration node names (e.g., '_iterate_').

    Returns:
        None
    """
    loc = Vector((0, 0))
    check_set_node_loc(tree, TREE_START, loc)

    loc.x += 200

    i = 0
    while True:
        if check_set_node_loc(tree, prefix + str(i), loc):
            loc.x += 200
        else:
            break
        i += 1

    check_set_node_loc(tree, TREE_END, loc)


def rearrange_parallax_depth_group(tree):
    """Arrange parallax depth group iteration nodes.

    Positions depth iteration nodes vertically below the main iterate node,
    recursively arranging their internal iteration structures.

    Args:
        tree: The node tree containing parallax depth group nodes.

    Returns:
        None
    """
    loc = Vector((0, 0))

    iterate = tree.nodes.get("_iterate")
    loc.x = iterate.location.x
    loc.y = iterate.location.y - 400

    counter = 0
    while True:
        if check_set_node_loc(tree, "_iterate_depth_" + str(counter), loc):
            idp = tree.nodes.get("_iterate_depth_" + str(counter))
            rearrange_parallax_iteration(idp.node_tree, "_iterate_")
            loc.y -= 400
            counter += 1
        else:
            break


def rearrange_parallax_layer_nodes_(mp, parallax):
    """Arrange parallax layer iteration and depth group nodes.

    Organizes the parallax loop structure including iteration nodes and
    depth group processing nodes.

    Args:
        mp: The MPaint data containing parallax channel information.
        parallax: The parallax node containing the loop structure.

    Returns:
        None
    """
    parallax_ch = get_root_parallax_channel(mp)
    if not parallax_ch:
        return

    loop = parallax.node_tree.nodes.get("_parallax_loop")
    if loop:
        rearrange_parallax_iteration(loop.node_tree, "_iterate_")

        # Rearrange parallax depth group source
        rearrange_parallax_depth_group(loop.node_tree)


def rearrange_parallax_process_internal_nodes(group_tree, node_name):
    """Arrange internal nodes of a parallax processing node.

    Positions UV nodes, texture coordinate nodes, and mix nodes within the
    parallax processing structure. Recursively arranges the parallax layer iteration.

    Args:
        group_tree: The group node tree containing the parallax node.
        node_name (str): The name of the parallax node to process.

    Returns:
        None
    """
    mp = group_tree.mp

    parallax = group_tree.nodes.get(node_name)

    # Depth source nodes
    depth_source_0 = parallax.node_tree.nodes.get("_depth_source_0")

    start = depth_source_0.node_tree.nodes.get(TREE_START)
    loc = start.location.copy()
    loc.y -= 200

    for uv in mp.uvs:
        if check_set_node_loc(depth_source_0.node_tree, uv.parallax_delta_uv, loc):
            loc.y -= 200

        elif check_set_node_loc(
            depth_source_0.node_tree, uv.baked_parallax_delta_uv, loc
        ):
            loc.y -= 200

        if check_set_node_loc(depth_source_0.node_tree, uv.parallax_current_uv, loc):
            loc.y -= 200

        elif check_set_node_loc(
            depth_source_0.node_tree, uv.baked_parallax_current_uv, loc
        ):
            loc.y -= 200

    for tc in texcoord_lists:

        if check_set_node_loc(
            depth_source_0.node_tree,
            PARALLAX_DELTA_PREFIX + TEXCOORD_IO_PREFIX + tc,
            loc,
        ):
            loc.y -= 200

        if check_set_node_loc(
            depth_source_0.node_tree,
            PARALLAX_CURRENT_PREFIX + TEXCOORD_IO_PREFIX + tc,
            loc,
        ):
            loc.y -= 200

    # Parallax iteration nodes
    parallax_loop = parallax.node_tree.nodes.get("_parallax_loop")
    iterate = parallax_loop.node_tree.nodes.get("_iterate")

    depth_mix = iterate.node_tree.nodes.get("_depth_from_tex_mix")
    loc = depth_mix.location.copy()
    loc.y -= 200

    for uv in mp.uvs:
        if check_set_node_loc(iterate.node_tree, uv.parallax_current_uv_mix, loc):
            loc.y -= 200
        elif check_set_node_loc(
            iterate.node_tree, uv.baked_parallax_current_uv_mix, loc
        ):
            loc.y -= 200

    for tc in texcoord_lists:

        if check_set_node_loc(
            iterate.node_tree, PARALLAX_CURRENT_MIX_PREFIX + TEXCOORD_IO_PREFIX + tc, loc
        ):
            loc.y -= 200

    # Parallax mix nodes
    parallax_end = parallax.node_tree.nodes.get(TREE_END)
    loc = parallax_end.location.copy()
    loc.x -= 200

    for uv in mp.uvs:
        if check_set_node_loc(parallax.node_tree, uv.parallax_mix, loc):
            loc.y -= 200

        elif check_set_node_loc(parallax.node_tree, uv.baked_parallax_mix, loc):
            loc.y -= 200

    for tc in texcoord_lists:

        if check_set_node_loc(
            parallax.node_tree, PARALLAX_MIX_PREFIX + TEXCOORD_IO_PREFIX + tc, loc
        ):
            loc.y -= 200

    rearrange_parallax_layer_nodes_(mp, parallax)
