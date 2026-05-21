# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

def check_set_node_loc(tree, node_name, loc, hide=False, parent_unset=False):
    """Check if a node exists and set its location, hide state, and parent.

    Retrieves a node by name from the tree and updates its location, accounting
    for parent node offsets if applicable. Also manages the node's hide state
    and can optionally unset the node's parent.

    Args:
        tree: The node tree containing the node to update.
        node_name (str): The name of the node to locate and update.
        loc: The target location for the node. If the node has a parent,
             the actual location will be offset by the parent's location.
        hide: Whether to hide the node. Defaults to False.
        parent_unset: Whether to unset the node's parent. Defaults to False.
                     If True, sets node.parent to None.

    Returns:
        bool: True if the node was found and updated, False if the node
              doesn't exist in the tree.
    """
    node = tree.nodes.get(node_name)
    if node:
        if node.parent is not None:
            if node.location != loc - node.parent.location:
                node.location = loc - node.parent.location

        elif node.location != loc:
            node.location = loc

        if node.hide != hide:
            node.hide = hide

        if parent_unset and node.parent is not None:
            node.parent = None

        return True
    return False