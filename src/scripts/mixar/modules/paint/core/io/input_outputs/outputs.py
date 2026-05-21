# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ..utils.io_utils import fix_tree_output_index


def get_tree_outputs(tree):
    """
    Get all output sockets from a node tree's interface.

    Retrieves all interface items that are configured as outputs or bidirectional (both input and output).

    Parameters:
        tree: The node tree to query for outputs.

    Returns:
        list: A list of interface items that have in_out attribute set to 'OUTPUT' or 'BOTH'.
    """
    return [ui for ui in tree.interface.items_tree if hasattr(ui, 'in_out') and ui.in_out in {'OUTPUT', 'BOTH'}]
    
def get_tree_output_by_name(tree, name):
    """
    Get a specific output socket from a node tree by name.

    Searches the tree's interface for an output socket with the specified name.

    Parameters:
        tree: The node tree to search.
        name (str): The name of the output socket to find.

    Returns:
        The output socket interface item if found, None otherwise.
    """
    outp = [ui for ui in tree.interface.items_tree if ui.name == name and hasattr(ui, 'in_out') and ui.in_out in {'OUTPUT', 'BOTH'}]
    if outp: return outp[0]

    return None

def new_tree_output(tree, name, socket_type, description='', use_both=False):
    """
    Create a new output socket in a node tree's interface.

    Creates a new output socket with the specified parameters. Automatically converts
    NodeSocketFloatFactor type to NodeSocketFloat for compatibility.

    Parameters:
        tree: The node tree to add the output socket to.
        name (str): The name for the new output socket.
        socket_type (str): The type of socket to create (e.g., 'NodeSocketColor', 'NodeSocketFloat').
        description (str, optional): A description for the output socket. Default is ''.
        use_both (bool, optional): Whether to make the socket bidirectional (unused in current implementation). Default is False.

    Returns:
        The newly created output socket interface item.
    """
    if socket_type == 'NodeSocketFloatFactor': socket_type = 'NodeSocketFloat'

    outp = None

    if not outp:
        outp = tree.interface.new_socket(name, description=description, in_out='OUTPUT', socket_type=socket_type)

    return outp

def remove_tree_output(tree, item):
    """
    Remove an output socket from a node tree's interface.

    If the socket is bidirectional (BOTH), it converts it to INPUT only.
    If it's OUTPUT only, it removes it completely from the interface.

    Parameters:
        tree: The node tree containing the output socket.
        item: The interface item (output socket) to remove or convert.

    Returns:
        None
    """
    if item.in_out == 'BOTH':
        item.in_out = 'INPUT'
    elif item.in_out == 'OUTPUT':
        tree.interface.remove(item)

def get_output_index(root_ch):
    """
    Get the output index for a root channel.

    Retrieves the I/O index assigned to a root channel.

    Parameters:
        root_ch: The root channel object to get the output index from.

    Returns:
        int: The I/O index of the root channel.
    """
    mp = root_ch.id_data.mp

    output_index = root_ch.io_index

    return output_index

def create_output(tree, name, socket_type, valid_outputs, index, dirty=False, default_value=None):
    """
    Create or retrieve an output socket and add it to the valid outputs list.

    Creates a new output socket if one with the given name doesn't exist, or retrieves
    the existing one. The output is added to the valid_outputs list and positioned at
    the specified index.

    Parameters:
        tree: The node tree to create/retrieve the output from.
        name (str): The name of the output socket.
        socket_type (str): The type of socket to create if it doesn't exist.
        valid_outputs (list): List to append the output socket to.
        index (int): The index position for the output socket.
        dirty (bool, optional): Flag indicating if the tree has been modified. Default is False.
        default_value (optional): Default value to set for the output socket if newly created. Default is None.

    Returns:
        bool: True if a new output was created (tree is dirty), False if existing output was used.
    """

    outp = get_tree_output_by_name(tree, name)
    if not outp:
        outp = new_tree_output(tree, name, socket_type, use_both=True)
        dirty = True
        if default_value is not None: outp.default_value = default_value

    valid_outputs.append(outp)
    fix_tree_output_index(tree, outp, index)

    return dirty

def get_tree_output_by_index(tree, index):
    """
    Get an output socket from a node tree by its index position.

    Iterates through the tree's interface items and returns the output socket
    at the specified index position (counting only OUTPUT and BOTH items).

    Parameters:
        tree: The node tree to search.
        index (int): The zero-based index of the output socket to retrieve.

    Returns:
        The output socket interface item at the specified index, or None if not found.
    """
    i = -1
    for item in tree.interface.items_tree:
        if item.in_out in {'OUTPUT', 'BOTH'}:
            i += 1

        if i == index:
            return item

    return None