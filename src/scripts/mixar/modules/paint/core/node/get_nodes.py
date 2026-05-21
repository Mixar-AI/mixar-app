# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from ...utils.common import is_valid_bsdf_node
from ..subtree.get_subtree import (
    get_channel_source_tree,
    get_mask_tree,
    get_source_tree,
    get_tree,
)

def get_active_mat_output_node(tree):
    """
    Search for and return the active material output node in a node tree.

    Parameters:
        tree: Node tree to search in for material output nodes.

    Returns:
        The active ShaderNodeOutputMaterial node if found, None otherwise.
    """
    # Search for output
    for node in tree.nodes:
        if node.bl_idname == 'ShaderNodeOutputMaterial' and node.is_active_output:
            return node

    return None

def get_material_output(mat):
    """
    Get the active material output node from a material.

    Parameters:
        mat: Material object to search for output node.

    Returns:
        The active OUTPUT_MATERIAL node if found, None otherwise.
    """
    if mat is not None and mat.node_tree:
        output = [n for n in mat.node_tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output]
        if output: return output[0]
    return None

def get_list_of_mpaint_nodes(mat):
    """
    Get a list of all mpaint nodes in a material's node tree.

    Parameters:
        mat: Material object to search for mpaint nodes.

    Returns:
        List of GROUP nodes that are marked as mpaint nodes. Returns empty list if material has no node tree.
    """

    if not mat.node_tree: return []

    mp_nodes = []
    for node in mat.node_tree.nodes:
        if node.type == 'GROUP' and node.node_tree.mp.is_mpaint_node:
            mp_nodes.append(node)

    return mp_nodes


def get_nodes_using_mp(mat, mp):
    """
    Get all nodes in a material that use a specific mp (mpaint) instance.

    Parameters:
        mat: Material object to search for nodes.
        mp: Specific mpaint instance to match against.

    Returns:
        List of GROUP nodes whose node_tree.mp matches the given mp instance. Returns empty list if material doesn't use nodes.
    """
    if not mat.use_nodes: return []
    mp_nodes = []
    for node in mat.node_tree.nodes:
        if node.type == 'GROUP' and node.node_tree and node.node_tree.mp == mp:
            mp_nodes.append(node)
    return mp_nodes

def get_channel_source_1(ch, layer=None, tree=None):
    """
    Get the source_1 node for a channel.

    Parameters:
        ch: Channel object to get source_1 node from.
        layer (optional): Layer containing the channel. If None, will be extracted from channel path. Default: None.
        tree (optional): Node tree to search in. If None, will be obtained from layer. Default: None.

    Returns:
        The source_1 node from the tree if found, None otherwise.
    """
    mp = ch.id_data.mp
    if not layer:
        m = re.match(r'mp\.layers\[(\d+)\]\.channels\[(\d+)\]', ch.path_from_id())
        if not m : return None
        layer = mp.layers[int(m.group(1))]

    if not tree: tree = get_tree(layer)
    if tree: return tree.nodes.get(ch.source_1)

    return None

def get_layer_source(layer, tree=None, get_baked=False):
    """
    Get the source node for a layer.

    Parameters:
        layer: Layer object to get source node from.
        tree (optional): Node tree to search in. If None, will be obtained from layer. Default: None.
        get_baked (optional): If True, get baked_source instead of source. Default: False.

    Returns:
        The source or baked_source node from the appropriate tree if found, None otherwise.
    """
    if not tree: tree = get_tree(layer)

    prop_name = 'source' if not get_baked else 'baked_source'

    source_tree = get_source_tree(layer, tree)
    if source_tree: return source_tree.nodes.get(getattr(layer, prop_name))
    if tree: return tree.nodes.get(getattr(layer, prop_name))

    return None

def get_mask_source(mask, get_baked=False):
    """
    Get the source node for a mask.

    Parameters:
        mask: Mask object to get source node from.
        get_baked (optional): If True, get baked_source instead of source. Default: False.

    Returns:
        The source or baked_source node from the mask tree if found, None otherwise.
    """
    tree = get_mask_tree(mask)
    if tree:
        if get_baked:
            return tree.nodes.get(mask.baked_source)
        return tree.nodes.get(mask.source)
    return None

def get_entity_source(entity, get_baked=False):
    """
    Get the source node for an entity (either a layer or mask).

    Parameters:
        entity: Entity object (layer or mask) to get source node from.
        get_baked (optional): If True, get baked_source instead of source. Default: False.

    Returns:
        The source or baked_source node based on entity type (layer or mask). Returns None if entity is neither.
    """

    m1 = re.match(r'^mp\.layers\[(\d+)\]$', entity.path_from_id())
    m2 = re.match(r'^mp\.layers\[(\d+)\]\.masks\[(\d+)\]$', entity.path_from_id())

    if m1: return get_layer_source(entity, get_baked=get_baked)
    elif m2: return get_mask_source(entity, get_baked=get_baked)

    return None

def get_channel_source(ch, layer=None, tree=None):
    """
    Get the source node for a channel.

    Parameters:
        ch: Channel object to get source node from.
        layer (optional): Layer containing the channel. Default: None.
        tree (optional): Node tree to search in. Default: None.

    Returns:
        The source node from the channel's source tree if found, None otherwise.
    """
    source_tree = get_channel_source_tree(ch, layer, tree)
    if source_tree: return source_tree.nodes.get(ch.source)

    return None

def get_closest_mp_node_backward(node):
    """
    Recursively search backward through node connections to find the closest mpaint node.

    Parameters:
        node: Starting node to search backward from.

    Returns:
        The closest GROUP node marked as a mpaint node found by traversing backward through connections, None if not found.
    """
    for inp in node.inputs:
        for link in inp.links:
            n = link.from_node
            if n.type == 'GROUP' and n.node_tree and n.node_tree.mp.is_mpaint_node:
                return n
            else:
                n = get_closest_mp_node_backward(n)
                if n: return n

    return None

def get_closest_bsdf_backward(node, valid_types=[]):
    """
    Recursively search backward through node connections to find the closest valid BSDF node.

    Parameters:
        node: Starting node to search backward from.
        valid_types (optional): List of valid BSDF node types to match. Default: [].

    Returns:
        The closest valid BSDF node found by traversing backward through connections, None if not found.
    """
    for inp in node.inputs:
        for link in inp.links:
            if is_valid_bsdf_node(link.from_node, valid_types):
                return link.from_node
            else:
                n = get_closest_bsdf_backward(link.from_node, valid_types)
                if n: return n

    return None

def get_closest_bsdf_forward(node, valid_types=[]):
    """
    Recursively search forward through node connections to find the closest valid BSDF node.

    Parameters:
        node: Starting node to search forward from.
        valid_types (optional): List of valid BSDF node types to match. Default: [].

    Returns:
        The closest valid BSDF node found by traversing forward through connections, None if not found.
    """
    for outp in node.outputs:
        for link in outp.links:
            if is_valid_bsdf_node(link.to_node, valid_types):
                return link.to_node
            else:
                n = get_closest_bsdf_forward(link.to_node, valid_types)
                if n: return n

    return None
