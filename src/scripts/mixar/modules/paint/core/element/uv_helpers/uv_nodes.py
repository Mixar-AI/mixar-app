# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
UV node management functions.
"""

from ..update_vcol import remove_tangent_sign_vcol
from ...node.node_utils import remove_node


def remove_uv_nodes(uv, obj):
    """
    Remove all nodes associated with a UV layer from the node tree.

    This function removes various UV-related nodes (uv_map, tangent, bitangent,
    parallax preparation nodes, etc.) from the node tree and also removes the
    associated tangent sign vertex color data from the object.

    Parameters
    ----------
    uv : object
        The UV layer object whose associated nodes should be removed.
    obj : bpy.types.Object
        The Blender object containing the UV layer and vertex color data.

    Returns
    -------
    None
    """
    tree = uv.id_data
    mp = tree.mp

    remove_node(tree, uv, 'uv_map')
    remove_node(tree, uv, 'tangent_process')
    remove_node(tree, uv, 'tangent')
    remove_node(tree, uv, 'tangent_flip')
    remove_node(tree, uv, 'bitangent')
    remove_node(tree, uv, 'bitangent_flip')
    remove_node(tree, uv, 'parallax_prep')

    remove_tangent_sign_vcol(obj, uv.name)
