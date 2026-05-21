# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

def is_mp_on_material(mp, mat):
    """Check if a specific MPaint node is used on a material.

    Iterates through all nodes in the material's node tree to determine if
    any GROUP node contains the specified MPaint (mp) instance.

    Parameters
    ----------
    mp : bpy.types.NodeTree
        The MPaint node tree to search for.
    mat : bpy.types.Material
        The material to check for the presence of the MPaint node.

    Returns
    -------
    bool
        True if the material contains the specified MPaint node, False otherwise.
        Returns False if the material does not use nodes.
    """
    if not mat.use_nodes: return False
    for node in mat.node_tree.nodes:
        if node.type == 'GROUP' and node.node_tree and node.node_tree.mp == mp:
            return True

    return False