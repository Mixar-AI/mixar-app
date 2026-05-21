# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ..input_outputs.inputs import get_tree_input_by_name, new_tree_input
from ..input_outputs.outputs import get_tree_output_by_name, new_tree_output, remove_tree_output


def refresh_source_tree_ios(source_tree, layer_type):
    """
    Refresh the input and output sockets of a source tree based on layer type.

    Ensures that the source tree has the appropriate input and output sockets for the
    given layer type. Creates standard Color, Alpha, and Vector sockets, and manages
    Color 1 and Alpha 1 sockets based on whether the layer type requires them.

    For IMAGE and MUSGRAVE layer types, Color 1 and Alpha 1 outputs are removed if they exist.
    For all other layer types, Color 1 and Alpha 1 outputs are created if they don't exist.

    Parameters:
        source_tree: The node tree to refresh the I/O sockets for.
        layer_type (str): The type of layer (e.g., 'IMAGE', 'MUSGRAVE', etc.) that determines
                         which I/O sockets are needed.

    Returns:
        None
    """

    # Create input and outputs
    inp = get_tree_input_by_name(source_tree, 'Vector')
    if not inp: new_tree_input(source_tree, 'Vector', 'NodeSocketVector')

    out = get_tree_output_by_name(source_tree, 'Color')
    if not out: new_tree_output(source_tree, 'Color', 'NodeSocketColor')

    out = get_tree_output_by_name(source_tree, 'Alpha')
    if not out: new_tree_output(source_tree, 'Alpha', 'NodeSocketFloat')

    col1 = get_tree_output_by_name(source_tree, 'Color 1')
    alp1 = get_tree_output_by_name(source_tree, 'Alpha 1')

    if layer_type not in {'IMAGE', 'MUSGRAVE'}:

        if not col1: col1 = new_tree_output(source_tree, 'Color 1', 'NodeSocketColor')
        if not alp1: alp1 = new_tree_output(source_tree, 'Alpha 1', 'NodeSocketFloat')

    else:
        if col1: remove_tree_output(source_tree, col1)
        if alp1: remove_tree_output(source_tree, alp1)