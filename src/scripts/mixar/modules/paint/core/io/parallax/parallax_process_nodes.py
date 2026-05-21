# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Main parallax process node reconnection functionality.

This module contains the primary function for reconnecting nodes
in parallax processing, including depth sources, iteration loops,
UV transformations, and final mixing nodes.
"""

from ......config.logging_config import get_logger
logger = get_logger(__name__)

from ....utils.common import get_mix_color_indices
from ....utils.constants import (
    TREE_START,
    TREE_END,
    START_UV,
    DELTA_UV,
    CURRENT_UV,
    HEIGHT_MAP,
    TEXCOORD_IO_PREFIX,
    PARALLAX_MIX_PREFIX,
    PARALLAX_DELTA_PREFIX,
    PARALLAX_CURRENT_PREFIX,
    PARALLAX_CURRENT_MIX_PREFIX,
    texcoord_lists,
)
from ..utils.io_utils import create_link
from .parallax_layer_nodes import reconnect_parallax_layer_nodes__


def reconnect_parallax_process_nodes(
    group_tree, parallax, baked=False, uv_name=""
):  # , uv_maps, tangents, bitangents):
    """
    Reconnect nodes for parallax processing.

    Sets up all node connections for parallax occlusion mapping, including depth sources,
    iteration loops, UV transformations, and final mixing nodes. Handles both baked and
    real-time parallax processing.

    Parameters:
        group_tree: The main node tree containing the parallax node.
        parallax: The parallax group node to reconnect.
        baked (bool, optional): Whether this is for baked parallax. Default is False.
        uv_name (str, optional): Specific UV map name to process. If empty, processes all UV maps. Default is "".

    Returns:
        None
    """

    mp = group_tree.mp

    # parallax = group_tree.nodes.get(PARALLAX)
    # if not parallax: return

    tree = parallax.node_tree

    start = tree.nodes.get(TREE_START)
    end = tree.nodes.get(TREE_END)

    # Depth source
    depth_source_0 = tree.nodes.get("_depth_source_0")
    depth_source_1 = tree.nodes.get("_depth_source_1")

    depth_start = depth_source_0.node_tree.nodes.get(TREE_START)
    depth_end = depth_source_0.node_tree.nodes.get(TREE_END)

    # Iteration
    loop = tree.nodes.get("_parallax_loop")
    iterate = loop.node_tree.nodes.get("_iterate")

    iterate_start = iterate.node_tree.nodes.get(TREE_START)
    iterate_end = iterate.node_tree.nodes.get(TREE_END)
    iterate_depth = iterate.node_tree.nodes.get("_depth_from_tex")
    iterate_branch = iterate.node_tree.nodes.get("_branch")

    # iterate_group_0 = loop.node_tree.nodes.get('_iterate')
    # iterate_group_start = iterate_group_0.node_tree.nodes.get(TREE_START)
    # iterate_group_end = iterate_group_0.node_tree.nodes.get(TREE_END)

    weight = tree.nodes.get("_weight")

    for uv in mp.uvs:
        if uv_name != "" and uv.name != uv_name:
            continue

        # Start and delta uv inputs
        create_link(
            tree,
            start.outputs[uv.name + START_UV],
            depth_source_0.inputs[uv.name + START_UV],
        )
        create_link(
            tree,
            start.outputs[uv.name + START_UV],
            depth_source_1.inputs[uv.name + START_UV],
        )
        create_link(
            tree, start.outputs[uv.name + START_UV], loop.inputs[uv.name + START_UV]
        )

        create_link(
            tree,
            start.outputs[uv.name + DELTA_UV],
            depth_source_0.inputs[uv.name + DELTA_UV],
        )
        create_link(
            tree,
            start.outputs[uv.name + DELTA_UV],
            depth_source_1.inputs[uv.name + DELTA_UV],
        )
        create_link(
            tree, start.outputs[uv.name + DELTA_UV], loop.inputs[uv.name + DELTA_UV]
        )

        create_link(
            tree,
            depth_source_0.outputs[uv.name + CURRENT_UV],
            loop.inputs[uv.name + CURRENT_UV],
        )

        # Parallax final mix
        if baked:
            parallax_mix = tree.nodes.get(uv.baked_parallax_mix)
        else:
            parallax_mix = tree.nodes.get(uv.parallax_mix)

        mixcol0, mixcol1, mixout = get_mix_color_indices(parallax_mix)

        create_link(tree, weight.outputs[0], parallax_mix.inputs[0])
        create_link(
            tree, loop.outputs[uv.name + CURRENT_UV], parallax_mix.inputs[mixcol0]
        )
        create_link(
            tree,
            depth_source_1.outputs[uv.name + CURRENT_UV],
            parallax_mix.inputs[mixcol1],
        )

        # End uv
        # create_link(tree, loop.outputs[uv.name + CURRENT_UV], end.inputs[uv.name])
        create_link(tree, parallax_mix.outputs[mixout], end.inputs[uv.name])

        # Inside depth source
        if baked:
            delta_uv = depth_source_0.node_tree.nodes.get(uv.baked_parallax_delta_uv)
        else:
            delta_uv = depth_source_0.node_tree.nodes.get(uv.parallax_delta_uv)
        mixcol0, mixcol1, mixout = get_mix_color_indices(delta_uv)

        if baked:
            current_uv = depth_source_0.node_tree.nodes.get(
                uv.baked_parallax_current_uv
            )
        else:
            current_uv = depth_source_0.node_tree.nodes.get(uv.parallax_current_uv)
        height_map = depth_source_0.node_tree.nodes.get(HEIGHT_MAP)

        create_link(
            depth_source_0.node_tree,
            depth_start.outputs["index"],
            delta_uv.inputs[mixcol0],
        )
        create_link(
            depth_source_0.node_tree,
            depth_start.outputs[uv.name + DELTA_UV],
            delta_uv.inputs[mixcol1],
        )

        create_link(
            depth_source_0.node_tree,
            depth_start.outputs[uv.name + START_UV],
            current_uv.inputs[0],
        )
        create_link(
            depth_source_0.node_tree, delta_uv.outputs[mixout], current_uv.inputs[1]
        )

        create_link(
            depth_source_0.node_tree,
            current_uv.outputs[0],
            depth_end.inputs[uv.name + CURRENT_UV],
        )

        if height_map:
            create_link(
                depth_source_0.node_tree, current_uv.outputs[0], height_map.inputs[0]
            )
            create_link(
                depth_source_0.node_tree, height_map.outputs[0], depth_end.inputs[0]
            )

        # Inside iteration
        create_link(
            iterate.node_tree,
            iterate_start.outputs[uv.name + START_UV],
            iterate_depth.inputs[uv.name + START_UV],
        )
        create_link(
            iterate.node_tree,
            iterate_start.outputs[uv.name + DELTA_UV],
            iterate_depth.inputs[uv.name + DELTA_UV],
        )

        if baked:
            parallax_current_uv_mix = iterate.node_tree.nodes.get(
                uv.baked_parallax_current_uv_mix
            )
        else:
            parallax_current_uv_mix = iterate.node_tree.nodes.get(
                uv.parallax_current_uv_mix
            )

        mixcol0, mixcol1, mixout = get_mix_color_indices(parallax_current_uv_mix)

        create_link(
            iterate.node_tree,
            iterate_branch.outputs[0],
            parallax_current_uv_mix.inputs[0],
        )

        create_link(
            iterate.node_tree,
            iterate_depth.outputs[uv.name + CURRENT_UV],
            parallax_current_uv_mix.inputs[mixcol0],
        )
        create_link(
            iterate.node_tree,
            iterate_start.outputs[uv.name + CURRENT_UV],
            parallax_current_uv_mix.inputs[mixcol1],
        )
        create_link(
            iterate.node_tree,
            parallax_current_uv_mix.outputs[mixout],
            iterate_end.inputs[uv.name + CURRENT_UV],
        )

    if not baked:
        _process_texcoord_connections(
            tree, start, end, depth_source_0, depth_source_1,
            depth_start, depth_end, loop, iterate, iterate_start,
            iterate_end, iterate_depth, iterate_branch, weight
        )

    # reconnect_parallax_layer_nodes(group_tree, parallax, uv_name)
    # reconnect_parallax_layer_nodes_(group_tree, parallax, uv_name)
    reconnect_parallax_layer_nodes__(group_tree, parallax, uv_name)


def _process_texcoord_connections(
    tree, start, end, depth_source_0, depth_source_1,
    depth_start, depth_end, loop, iterate, iterate_start,
    iterate_end, iterate_depth, iterate_branch, weight
):
    """
    Process texture coordinate connections for non-baked parallax.

    This helper function handles the texture coordinate (non-UV) connections
    for parallax processing when not in baked mode.

    Parameters:
        tree: The parallax node tree.
        start: The tree start node.
        end: The tree end node.
        depth_source_0: First depth source node.
        depth_source_1: Second depth source node.
        depth_start: Depth source start node.
        depth_end: Depth source end node.
        loop: The parallax loop node.
        iterate: The iteration node.
        iterate_start: Iteration start node.
        iterate_end: Iteration end node.
        iterate_depth: Iteration depth node.
        iterate_branch: Iteration branch node.
        weight: The weight node.

    Returns:
        None
    """
    for tc in texcoord_lists:

        base_name = TEXCOORD_IO_PREFIX + tc
        if base_name + START_UV not in start.outputs:
            continue

        # Start and delta uv inputs
        create_link(
            tree,
            start.outputs[base_name + START_UV],
            depth_source_0.inputs[base_name + START_UV],
        )
        create_link(
            tree,
            start.outputs[base_name + START_UV],
            depth_source_1.inputs[base_name + START_UV],
        )
        create_link(
            tree,
            start.outputs[base_name + START_UV],
            loop.inputs[base_name + START_UV],
        )

        create_link(
            tree,
            start.outputs[base_name + DELTA_UV],
            depth_source_0.inputs[base_name + DELTA_UV],
        )
        create_link(
            tree,
            start.outputs[base_name + DELTA_UV],
            depth_source_1.inputs[base_name + DELTA_UV],
        )
        create_link(
            tree,
            start.outputs[base_name + DELTA_UV],
            loop.inputs[base_name + DELTA_UV],
        )

        create_link(
            tree,
            depth_source_0.outputs[base_name + CURRENT_UV],
            loop.inputs[base_name + CURRENT_UV],
        )

        # Parallax final mix
        parallax_mix = tree.nodes.get(PARALLAX_MIX_PREFIX + base_name)
        mixcol0, mixcol1, mixout = get_mix_color_indices(parallax_mix)

        create_link(tree, weight.outputs[0], parallax_mix.inputs[0])
        create_link(
            tree, loop.outputs[base_name + CURRENT_UV], parallax_mix.inputs[mixcol0]
        )
        create_link(
            tree,
            depth_source_1.outputs[base_name + CURRENT_UV],
            parallax_mix.inputs[mixcol1],
        )

        # End uv
        create_link(tree, parallax_mix.outputs[mixout], end.inputs[base_name])

        # Inside depth source
        delta_uv = depth_source_0.node_tree.nodes.get(
            PARALLAX_DELTA_PREFIX + base_name
        )
        mixcol0, mixcol1, mixout = get_mix_color_indices(delta_uv)
        current_uv = depth_source_0.node_tree.nodes.get(
            PARALLAX_CURRENT_PREFIX + base_name
        )

        create_link(
            depth_source_0.node_tree,
            depth_start.outputs["index"],
            delta_uv.inputs[mixcol0],
        )
        create_link(
            depth_source_0.node_tree,
            depth_start.outputs[base_name + DELTA_UV],
            delta_uv.inputs[mixcol1],
        )

        create_link(
            depth_source_0.node_tree,
            depth_start.outputs[base_name + START_UV],
            current_uv.inputs[0],
        )
        create_link(
            depth_source_0.node_tree, delta_uv.outputs[mixout], current_uv.inputs[1]
        )

        create_link(
            depth_source_0.node_tree,
            current_uv.outputs[0],
            depth_end.inputs[base_name + CURRENT_UV],
        )

        # Inside iteration
        create_link(
            iterate.node_tree,
            iterate_start.outputs[base_name + START_UV],
            iterate_depth.inputs[base_name + START_UV],
        )
        create_link(
            iterate.node_tree,
            iterate_start.outputs[base_name + DELTA_UV],
            iterate_depth.inputs[base_name + DELTA_UV],
        )

        parallax_current_uv_mix = iterate.node_tree.nodes.get(
            PARALLAX_CURRENT_MIX_PREFIX + base_name
        )
        mixcol0, mixcol1, mixout = get_mix_color_indices(parallax_current_uv_mix)

        create_link(
            iterate.node_tree,
            iterate_branch.outputs[0],
            parallax_current_uv_mix.inputs[0],
        )
        create_link(
            iterate.node_tree,
            iterate_depth.outputs[base_name + CURRENT_UV],
            parallax_current_uv_mix.inputs[mixcol0],
        )
        create_link(
            iterate.node_tree,
            iterate_start.outputs[base_name + CURRENT_UV],
            parallax_current_uv_mix.inputs[mixcol1],
        )

        create_link(
            iterate.node_tree,
            parallax_current_uv_mix.outputs[mixout],
            iterate_end.inputs[base_name + CURRENT_UV],
        )
