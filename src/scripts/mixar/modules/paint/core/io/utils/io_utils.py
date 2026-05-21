# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

def get_tree_input_index(interface, item):
    """Get the index position of an input item in the tree interface.

    Counts only input items (in_out is 'INPUT' or 'BOTH') to determine
    the position of the specified item.

    Args:
        interface: The tree interface to search.
        item: The interface item whose index to find.

    Returns:
        int: The zero-based index of the item among inputs, or -1 if not found.
    """
    index = -1
    for it in interface.items_tree:
        if item.in_out in {'INPUT', 'BOTH'} and it.in_out in {'INPUT', 'BOTH'}:
            index += 1
        if it == item:
             return index

    return index

def fix_tree_input_index(tree, item, correct_index):
    """Reorder an input item to the correct index position in the tree interface.

    Handles both regular inputs and bidirectional (BOTH) items. For BOTH items,
    uses a workaround to try all positions due to inconsistent interface.move behavior.

    Args:
        tree: The node tree containing the interface.
        item: The interface item to reposition.
        correct_index (int): The desired index position for the input.

    Returns:
        None
    """
    interface = tree.interface
    if item.in_out != 'BOTH':
        outputs = [it for it in interface.items_tree if it.in_out in {'OUTPUT', 'BOTH'}]
        offset = len(outputs)
        cur_index = [i for i, it in enumerate(interface.items_tree) if it == item]
        if cur_index and cur_index[0] != correct_index + offset:
            interface.move(item, correct_index + offset)
    else:
        if get_tree_input_index(interface, item) == correct_index:
            return

        # HACK: Try to move using all index because interface move is still inconsistent
        for i in range(len(interface.items_tree)):
            interface.move(item, i)
            if get_tree_input_index(interface, item) == correct_index:
                return

def fix_tree_output_index(tree, item, correct_index):
    """Reorder an output item to the correct index position in the tree interface.

    Handles both regular outputs and bidirectional (BOTH) items. For BOTH items,
    uses a workaround to try all positions due to inconsistent interface.move behavior.

    Args:
        tree: The node tree containing the interface.
        item: The interface item to reposition.
        correct_index (int): The desired index position for the output.

    Returns:
        None
    """
    interface = tree.interface
    if item.in_out != 'BOTH':
        cur_index = [i for i, it in enumerate(interface.items_tree) if it == item]
        if cur_index and cur_index[0] != correct_index:
            interface.move(item, correct_index)
    else:
        if get_tree_output_index(interface, item) == correct_index:
            return

        # HACK: Try to move using all index because interface move is still inconsistent
        for i in range(len(interface.items_tree)):
            interface.move(item, i)
            if get_tree_output_index(interface, item) == correct_index:
                return

def get_tree_output_index(interface, item):
    """Get the index position of an output item in the tree interface.

    Counts only output items (in_out is 'OUTPUT' or 'BOTH') to determine
    the position of the specified item.

    Args:
        interface: The tree interface to search.
        item: The interface item whose index to find.

    Returns:
        int: The zero-based index of the item among outputs, or -1 if not found.
    """
    index = -1
    for it in interface.items_tree:
        if item.in_out in {'OUTPUT', 'BOTH'} and it.in_out in {'OUTPUT', 'BOTH'}:
            index += 1
        if it == item:
             return index

    return index

def create_link(tree, out, inp):
    """Create a link between two sockets if it doesn't already exist.

    Checks if a link already exists between the output and input sockets
    before creating a new one to avoid duplicates.

    Args:
        tree: The node tree to create the link in.
        out: The output socket to connect from.
        inp: The input socket to connect to.

    Returns:
        list: The outputs of the input socket's node if it exists, empty list otherwise.
    """
    node = inp.node
    if not any(l for l in out.links if l.to_socket == inp):
        tree.links.new(out, inp)
        #print(out, 'is connected to', inp)
    if node: return node.outputs
    return []

def break_link(tree, out, inp):
    """Break a link between two specific sockets.

    Searches for a link from the output socket to the input socket and removes it.

    Args:
        tree: The node tree containing the link.
        out: The output socket.
        inp: The input socket.

    Returns:
        bool: True if a link was found and removed, False otherwise.
    """
    for link in out.links:
        if link.to_socket == inp:
            tree.links.remove(link)
            return True
    return False
    
def break_input_link(tree, inp):
    """Break all links connected to an input socket.

    Removes all incoming links to the specified input socket.

    Args:
        tree: The node tree containing the links.
        inp: The input socket to disconnect.

    Returns:
        None
    """
    for link in inp.links:
        tree.links.remove(link)

def break_output_link(tree, outp):
    """Break all links connected to an output socket.

    Removes all outgoing links from the specified output socket.

    Args:
        tree: The node tree containing the links.
        outp: The output socket to disconnect.

    Returns:
        None
    """
    for link in outp.links:
        tree.links.remove(link)