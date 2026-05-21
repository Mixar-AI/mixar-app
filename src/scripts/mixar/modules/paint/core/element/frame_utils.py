# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ...utils.constants import INFO_PREFIX


def get_frame(tree, name, suffix='', label=''):
    """Get or create a frame node in a node tree.

    Retrieves an existing frame node by name, or creates a new NodeFrame if it doesn't exist.
    Updates the frame's label if it differs from the provided label.

    Parameters
    ----------
    tree : bpy.types.NodeTree
        The node tree to search or add the frame to.
    name : str
        The base name for the frame node.
    suffix : str, optional
        Suffix to append to the frame name (default: '').
    label : str, optional
        The display label for the frame node (default: '').

    Returns
    -------
    bpy.types.NodeFrame
        The retrieved or newly created frame node.
    """

    frame_name = name + suffix

    frame = tree.nodes.get(frame_name)
    if not frame:
        frame = tree.nodes.new('NodeFrame')
        frame.name = frame_name

    if frame.label != label:
        frame.label = label

    return frame

def clean_unused_frames(tree):
    """Remove all unused frame nodes from a node tree.

    Identifies frame nodes that have no child nodes and removes them from the tree.
    Frames whose names start with INFO_PREFIX are excluded from removal.

    Parameters
    ----------
    tree : bpy.types.NodeTree
        The node tree from which to remove unused frames.

    Returns
    -------
    None
    """

    #T = time.time()

    # Collect all parents and frames
    parents = []
    frames = []
    for node in tree.nodes:
        if node.parent and node.parent not in parents:
            parents.append(node.parent)
        if node.type == 'FRAME' and not node.name.startswith(INFO_PREFIX):
            frames.append(node)

    # Remove frame with no child
    for frame in frames:
        if frame not in parents:
            tree.nodes.remove(frame)

    #print('INFO: Unused frames cleaned in ', '{:0.2f}'.format((time.time() - T) * 1000), 'ms!')

def rearrange_mp_frame_nodes(mp):
    """Rearrange and clean up frame nodes for a MP object.

    Retrieves the node tree associated with the MP object and removes all unused
    frame nodes from it.

    Parameters
    ----------
    mp : object
        A MP object that has an id_data attribute pointing to a node tree.

    Returns
    -------
    None
    """
    tree = mp.id_data
    clean_unused_frames(tree)

def check_set_node_parent(tree, child_name, parent_node):
    """Set the parent of a node if it exists and the parent differs from the current one.

    Looks up a child node by name in the tree and assigns it a new parent node
    only if the child exists and its current parent is different from the specified parent.

    Parameters
    ----------
    tree : bpy.types.NodeTree
        The node tree containing the child node.
    child_name : str
        The name of the child node to update.
    parent_node : bpy.types.Node or None
        The new parent node to assign to the child.

    Returns
    -------
    None
    """
    child = tree.nodes.get(child_name)
    if child and child.parent != parent_node:
        child.parent = parent_node

def check_set_node_width(node, width):
    """Set the width of a node if it exists and the width differs from the current one.

    Updates the node's width property only if the node exists and its current width
    is different from the specified width.

    Parameters
    ----------
    node : bpy.types.Node or None
        The node whose width should be updated.
    width : float
        The new width value to set for the node.

    Returns
    -------
    bool
        True if the node exists, False otherwise.
    """
    if node:
        if node.width != width:
            node.width = width
        return True
    return False