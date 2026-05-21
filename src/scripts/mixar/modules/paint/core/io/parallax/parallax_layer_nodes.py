# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Functions for connecting parallax layer and iteration nodes.

This module contains helper functions for managing connections between
parallax iteration nodes and layer nodes in the node tree.
"""

from ......config.logging_config import get_logger
logger = get_logger(__name__)

from ....utils.constants import TREE_START, TREE_END
from ..utils.io_utils import create_link
from ...layer.layer_utils import get_root_parallax_channel


def connect_parallax_iteration(tree, prefix):
    """
    Connect parallax iteration nodes in sequence.

    Creates connections between sequential iteration nodes (numbered with the given prefix)
    from the start node to the end node. Each iteration node is connected to the next,
    forming a chain of processing steps.

    Parameters:
        tree: The node tree containing the iteration nodes.
        prefix (str): The prefix for iteration node names (e.g., "_iterate_" for nodes named "_iterate_0", "_iterate_1", etc.).

    Returns:
        None
    """

    start = tree.nodes.get(TREE_START)
    end = tree.nodes.get(TREE_END)

    # Inside iterate group
    prev_it = start
    counter = 0
    while True:
        it = tree.nodes.get(prefix + str(counter))

        if it:
            for inp in it.inputs:
                if inp.name in prev_it.outputs:
                    create_link(tree, prev_it.outputs[inp.name], inp)
                elif inp.name in start.outputs:
                    create_link(tree, start.outputs[inp.name], inp)
        else:
            for inp in end.inputs:
                if inp.name == "":
                    continue
                if inp.name in prev_it.outputs:
                    create_link(tree, prev_it.outputs[inp.name], inp)
                elif inp.name in start.outputs:
                    create_link(tree, start.outputs[inp.name], inp)
            break

        prev_it = it
        counter += 1


def reconnect_parallax_layer_nodes__(group_tree, parallax, uv_name=""):
    """
    Reconnect parallax layer nodes (current implementation).

    Connects the iteration nodes within the parallax loop, including top-level iterations
    and depth library iterations. This is the currently active implementation for reconnecting
    parallax layer nodes.

    Parameters:
        group_tree: The main node tree containing the parallax node.
        parallax: The parallax group node.
        uv_name (str, optional): Specific UV map name to process. If empty, processes all. Default is "".

    Returns:
        None
    """
    mp = group_tree.mp

    parallax_ch = get_root_parallax_channel(mp)
    if not parallax_ch:
        return

    # Connect iterate group
    loop = parallax.node_tree.nodes.get("_parallax_loop")
    if not loop:
        return

    # Connect top level iteration
    connect_parallax_iteration(loop.node_tree, "_iterate_")

    # Connect depth lib iteration
    counter = 0
    while True:
        it = loop.node_tree.nodes.get("_iterate_depth_" + str(counter))
        if it:
            connect_parallax_iteration(it.node_tree, "_iterate_")
        else:
            break

        counter += 1


def reconnect_parallax_layer_nodes_(group_tree, parallax, uv_name=""):
    """
    Reconnect parallax layer nodes (alternative implementation).

    An alternative implementation for connecting parallax iteration nodes. Connects both
    top-level iterate groups and internal iterate nodes within those groups.

    Parameters:
        group_tree: The main node tree containing the parallax node.
        parallax: The parallax group node.
        uv_name (str, optional): Specific UV map name to process. If empty, processes all. Default is "".

    Returns:
        None
    """

    mp = group_tree.mp

    parallax_ch = get_root_parallax_channel(mp)
    if not parallax_ch:
        return

    # Connect iterate group
    loop = parallax.node_tree.nodes.get("_parallax_loop")
    if not loop:
        return

    connect_parallax_iteration(loop.node_tree, "_iterate_group_")

    # Connect inside iterate group
    iterate_group_0 = loop.node_tree.nodes.get("_iterate_group_0")
    if not iterate_group_0:
        return

    connect_parallax_iteration(iterate_group_0.node_tree, "_iterate_")
