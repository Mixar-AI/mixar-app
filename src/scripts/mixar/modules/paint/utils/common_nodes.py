# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Node utility functions for the paint module."""


def get_node(tree, name, parent=None):
    """Get a node from a node tree, optionally filtered by parent.

    Args:
        tree: Node tree to search in.
        name (str): Name of the node to find.
        parent (optional): Parent node to filter by. Defaults to None.

    Returns:
        Node object if found and matches parent filter, None otherwise.
    """
    node = tree.nodes.get(name)

    if node and parent and node.parent != parent:
        return None

    return node


# ShaderNodeVertexColor can't use bump map, so ShaderNodeAttribute will be used for now
def get_vcol_bl_idname():
    """Get the Blender ID name for vertex color nodes.

    Note: ShaderNodeVertexColor can't use bump maps, so ShaderNodeAttribute is used instead.

    Returns:
        str: The string "ShaderNodeAttribute".
    """
    # if is_bl_newer_than(2, 81):
    #    return 'ShaderNodeVertexColor'
    return "ShaderNodeAttribute"


def set_source_vcol_name(src, name):
    """Set the vertex color name on a source node.

    Args:
        src: Source node to update.
        name (str): Name of the vertex color attribute to set.

    Returns:
        None
    """
    # if is_bl_newer_than(2, 81):
    #    src.layer_name = name
    # else:
    src.attribute_name = name


def set_mix_clamp(mix, bool_val):
    """Set the clamp property on a mix node.

    Args:
        mix: Mix node to update.
        bool_val (bool): Boolean value to set for clamping.

    Returns:
        None
    """
    if hasattr(mix, "clamp_result") and mix.clamp_result != bool_val:
        mix.clamp_result = bool_val
    elif hasattr(mix, "use_clamp") and mix.use_clamp != bool_val:
        mix.use_clamp = bool_val


def get_mix_color_indices(mix):
    """Get the input and output indices for color sockets on a mix node.

    Args:
        mix: Mix node to get indices from.

    Returns:
        tuple: Three integers (input1_index, input2_index, output_index) for color sockets.
    """
    if mix is None:
        return 0, 0, 0

    if mix.bl_idname == "ShaderNodeMix":
        if mix.data_type == "FLOAT":
            return 2, 3, 0
        elif mix.data_type == "VECTOR":
            return 4, 5, 1
        return 6, 7, 2

    # Check for Color1 input name
    idx0 = [i for i, inp in enumerate(mix.inputs) if inp.name == "Color1"]
    if len(idx0) > 0:
        idx0 = idx0[0]
    else:
        idx0 = 1

    idx1 = [i for i, inp in enumerate(mix.inputs) if inp.name == "Color2"]
    if len(idx1) > 0:
        idx1 = idx1[0]
    else:
        idx1 = 2

    outidx = 0

    return idx0, idx1, outidx


def is_first_socket_bsdf(node):
    """Check if the first output socket of a node is a BSDF shader socket.

    Args:
        node: Node to check.

    Returns:
        bool: True if first output exists and is type SHADER, False otherwise.
    """
    return len(node.outputs) > 0 and node.outputs[0].type == "SHADER"


def is_valid_bsdf_node(node, valid_types=[]):
    """Check if a node is a valid BSDF node.

    Args:
        node: Node to validate.
        valid_types (list, optional): List of valid node types. Defaults to [].

    Returns:
        bool: True if node is valid BSDF type, False otherwise.
    """
    if not valid_types:
        return (
            node.type == "EMISSION"
            or node.type.startswith("BSDF_")
            or node.type.endswith("_SHADER")
            or is_first_socket_bsdf(node)
        )

    return node.type in valid_types
