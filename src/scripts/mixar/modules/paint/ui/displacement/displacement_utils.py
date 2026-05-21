# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ...core.io.utils.io_utils import create_link

def is_node_a_displacement(node, is_vector_disp=False):
    """Check if a node is a displacement or vector displacement node.

    Args:
        node: The Blender shader node to check.
        is_vector_disp (bool, optional): If True, check for vector displacement type.
            If False, check for standard displacement type. Defaults to False.

    Returns:
        bool: True if the node matches the specified displacement type, False otherwise.
    """
    if is_vector_disp:
        return node.type == "VECTOR_DISPLACEMENT"
    return node.type == "DISPLACEMENT"


def get_closest_disp_node_backward(node, socket_name="", is_vector_disp=False):
    """Search backward through the node tree to find the closest displacement node.

    Recursively traverses the input links of a node to find a displacement or
    vector displacement node.

    Args:
        node: The starting Blender shader node to search from.
        socket_name (str, optional): Specific input socket name to search from.
            If empty, searches all inputs. Defaults to "".
        is_vector_disp (bool, optional): If True, search for vector displacement nodes.
            If False, search for standard displacement nodes. Defaults to False.

    Returns:
        The closest displacement node found, or None if no displacement node exists
        in the backward path.
    """

    # Get input list
    if socket_name != "":
        inp = node.inputs.get(socket_name)
        if not inp:
            return None
        inputs = [inp]
    else:
        inputs = node.inputs

    # Search for displacement node
    for inp in inputs:
        for link in inp.links:
            n = link.from_node
            if is_node_a_displacement(n, is_vector_disp=is_vector_disp):
                return n
            else:
                n = get_closest_disp_node_backward(n, is_vector_disp=is_vector_disp)
                if n:
                    return n

    return None


def create_displacement_node(tree, connect_to=None):
    """Create a new displacement shader node in the node tree.

    Args:
        tree: The Blender shader node tree to add the displacement node to.
        connect_to (optional): The input socket to connect the displacement output to.
            If None, no connection is made. Defaults to None.

    Returns:
        The newly created ShaderNodeDisplacement node.
    """
    disp = tree.nodes.new("ShaderNodeDisplacement")

    if connect_to:
        create_link(tree, disp.outputs[0], connect_to)

    return disp

def create_vector_displacement_node(tree, connect_to=None):
    """Create a new vector displacement shader node in the node tree.

    Creates a ShaderNodeVectorDisplacement node and sets its scale to 1.0.

    Args:
        tree: The Blender shader node tree to add the vector displacement node to.
        connect_to (optional): The input socket to connect the vector displacement output to.
            If None, no connection is made. Defaults to None.

    Returns:
        The newly created ShaderNodeVectorDisplacement node.
    """
    vdisp = None
    vdisp = tree.nodes.new("ShaderNodeVectorDisplacement")

    # Make sure vector displacement node has 1.0 scale
    if "Scale" in vdisp.inputs:
        vdisp.inputs["Scale"].default_value = 1.0

    if vdisp and connect_to:
        create_link(tree, vdisp.outputs[0], connect_to)

    return vdisp
