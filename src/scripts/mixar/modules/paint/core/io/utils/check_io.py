# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ....utils.constants import CURRENT_UV, DELTA_UV, START_UV
from ..input_outputs.inputs import get_tree_input_by_name, new_tree_input, remove_tree_input
from ..input_outputs.outputs import get_tree_output_by_name, new_tree_output, remove_tree_output


def check_parallax_process_outputs(parallax, uv_name, remove=False):
    """Check and manage parallax process outputs for a given UV name.

    This function checks if an output with the specified UV name exists in the parallax
    node tree. It can either remove the output if it exists or create it if it doesn't,
    based on the remove parameter.

    Args:
        parallax: The parallax node object containing the node_tree.
        uv_name (str): The name of the UV output to check or manage.
        remove (bool, optional): If True, removes the output if it exists. If False,
            creates the output if it doesn't exist. Defaults to False.

    Returns:
        None
    """

    outp = get_tree_output_by_name(parallax.node_tree, uv_name)
    if remove and outp:
        remove_tree_output(parallax.node_tree, outp)
    elif not remove and not outp:
        outp = new_tree_output(parallax.node_tree, uv_name, 'NodeSocketVector')

def check_start_delta_uv_inputs(tree, uv_name, remove=False):
    """Check and manage start and delta UV inputs for a node tree.

    This function manages two types of UV inputs for a given tree: start UV and delta UV.
    It can either remove these inputs if they exist or create them if they don't exist,
    based on the remove parameter.

    Args:
        tree: The node tree object to check or modify inputs for.
        uv_name (str): The base name of the UV inputs.
        remove (bool, optional): If True, removes the inputs if they exist. If False,
            creates the inputs if they don't exist. Defaults to False.

    Returns:
        None
    """

    start_uv_name = uv_name + START_UV
    delta_uv_name = uv_name + DELTA_UV

    start = get_tree_input_by_name(tree, start_uv_name)
    if remove and start:
        remove_tree_input(tree, start)
    elif not remove and not start:
        new_tree_input(tree, start_uv_name, 'NodeSocketVector')

    delta = get_tree_input_by_name(tree, delta_uv_name)
    if remove and delta:
        remove_tree_input(tree, delta)
    elif not remove and not delta:
        new_tree_input(tree, delta_uv_name, 'NodeSocketVector')

def check_current_uv_outputs(tree, uv_name, remove=False):
    """Check and manage current UV outputs for a node tree.

    This function checks if a current UV output exists in the tree and either removes
    it or creates it based on the remove parameter.

    Args:
        tree: The node tree object to check or modify outputs for.
        uv_name (str): The base name of the UV output.
        remove (bool, optional): If True, removes the output if it exists. If False,
            creates the output if it doesn't exist. Defaults to False.

    Returns:
        None
    """
    current_uv_name = uv_name + CURRENT_UV

    #current = tree.outputs.get(current_uv_name)
    current = get_tree_output_by_name(tree, current_uv_name)
    if remove and current:
        #tree.outputs.remove(current)
        remove_tree_output(tree, current)
    elif not remove and not current:
        #tree.outputs.new('NodeSocketVector', current_uv_name)
        new_tree_output(tree, current_uv_name, 'NodeSocketVector')

def check_current_uv_inputs(tree, uv_name, remove=False):
    """Check and manage current UV inputs for a node tree.

    This function checks if a current UV input exists in the tree and either removes
    it or creates it based on the remove parameter.

    Args:
        tree: The node tree object to check or modify inputs for.
        uv_name (str): The base name of the UV input.
        remove (bool, optional): If True, removes the input if it exists. If False,
            creates the input if it doesn't exist. Defaults to False.

    Returns:
        None
    """
    current_uv_name = uv_name + CURRENT_UV

    current = get_tree_input_by_name(tree, current_uv_name)
    if remove and current:
        remove_tree_input(tree, current)
    elif not remove and not current:
        new_tree_input(tree, current_uv_name, 'NodeSocketVector')