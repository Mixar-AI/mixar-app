# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Utility functions for managing parallax input connections.

This module contains helper functions for removing and managing input connections
from previous layers in parallax processing.
"""

from ......config.logging_config import get_logger
logger = get_logger(__name__)

from ....utils.constants import io_suffix, nsew_letters
from ..utils.io_utils import break_input_link, create_link
from ...layer.check_layers import has_previous_layer_channels
from ...node.node_utils import get_essential_node
from ....utils.constants import GEOMETRY


def remove_all_prev_inputs(tree, layer, node):
    """
    Remove all previous layer input connections from a node.

    Disconnects all input connections from previous layers that are no longer needed,
    including height, normal, alpha, and smooth bump inputs. For normal channels,
    replaces the input with the geometry normal when appropriate.

    Parameters:
        tree: The node tree containing the node.
        layer: The layer object being processed.
        node: The node to remove previous input connections from.

    Returns:
        None
    """

    mp = layer.id_data.mp

    if layer.parent_idx == -1:
        return

    for i, ch in enumerate(layer.channels):
        root_ch = mp.channels[i]
        if has_previous_layer_channels(layer, root_ch):
            continue

        if root_ch.type == "NORMAL":

            io_name = root_ch.name + io_suffix["HEIGHT"]
            if io_name in node.inputs:
                break_input_link(tree, node.inputs[io_name])

            io_name = root_ch.name + io_suffix["HEIGHT"] + io_suffix["ALPHA"]
            if io_name in node.inputs:
                break_input_link(tree, node.inputs[io_name])

            # if height_only: continue

            if root_ch.enable_smooth_bump:

                for letter in nsew_letters:

                    io_name = root_ch.name + io_suffix["HEIGHT_" + letter.upper()]
                    if io_name in node.inputs:
                        break_input_link(tree, node.inputs[io_name])

                    io_name = (
                        root_ch.name
                        + io_suffix["HEIGHT_" + letter.upper()]
                        + io_suffix["ALPHA"]
                    )
                    if io_name in node.inputs:
                        break_input_link(tree, node.inputs[io_name])

            io_name = root_ch.name + io_suffix["MAX_HEIGHT"]
            if io_name in node.inputs:
                break_input_link(tree, node.inputs[io_name])

            io_name = root_ch.name + io_suffix["VDISP"]
            if io_name in node.inputs:
                break_input_link(tree, node.inputs[io_name])

            io_name = root_ch.name + io_suffix["VDISP"] + io_suffix["ALPHA"]
            if io_name in node.inputs:
                break_input_link(tree, node.inputs[io_name])

        # if height_only: continue

        io_name = root_ch.name
        if io_name in node.inputs:
            # Should always fill normal input
            # geometry = tree.nodes.get(GEOMETRY)
            if root_ch.type == "NORMAL":  # and geometry:
                create_link(
                    tree,
                    get_essential_node(tree, GEOMETRY)["Normal"],
                    node.inputs[io_name],
                )
            else:
                break_input_link(tree, node.inputs[io_name])

        io_name = root_ch.name + io_suffix["ALPHA"]
        if io_name in node.inputs:
            break_input_link(tree, node.inputs[io_name])
