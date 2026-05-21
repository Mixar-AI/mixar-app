# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer hierarchy operations.

This module provides functions for navigating layer hierarchies including
parent-child relationships, neighbors, and index/name mappings.
"""

from ..layer.layer_utils import get_layer_index


def get_list_of_direct_child_ids(layer):
    """Get the indices of all direct child layers of a group layer.

    Args:
        layer: The layer object to get children for.

    Returns:
        list: List of integer indices of direct child layers. Returns empty list
            if the layer is not a GROUP type.
    """
    mp = layer.id_data.mp

    if layer.type != "GROUP":
        return []

    layer_idx = get_layer_index(layer)

    children = []
    for i, t in enumerate(mp.layers):
        if t.parent_idx == layer_idx:
            children.append(i)

    return children


def get_list_of_direct_children(layer):
    """Get all direct child layer objects of a group layer.

    Args:
        layer: The layer object to get children for.

    Returns:
        list: List of layer objects that are direct children. Returns empty list
            if the layer is not a GROUP type.
    """
    mp = layer.id_data.mp

    if layer.type != "GROUP":
        return []

    layer_idx = get_layer_index(layer)

    children = []
    for t in mp.layers:
        if t.parent_idx == layer_idx:
            children.append(t)

    return children


def get_list_of_all_children_and_child_ids(layer):
    """Get all descendant layers and their indices recursively.

    Returns both direct children and nested children (grandchildren, etc.)
    of a group layer.

    Args:
        layer: The layer object to get all descendants for.

    Returns:
        tuple: A tuple containing:
            - children (list): List of all descendant layer objects.
            - child_ids (list): List of all descendant layer indices.
            Returns ([], []) if the layer is not a GROUP type.
    """
    mp = layer.id_data.mp

    if layer.type != "GROUP":
        return [], []

    layer_idx = get_layer_index(layer)

    children = []
    child_ids = []
    for i, t in enumerate(mp.layers):
        if t.parent_idx == layer_idx or t.parent_idx in child_ids:
            children.append(t)
            child_ids.append(i)

    return children, child_ids


def get_list_of_parent_ids(layer):
    """Get the indices of all parent layers in the hierarchy chain.

    Traverses up the layer hierarchy and collects all GROUP parent layer indices.

    Args:
        layer: The layer object to get parents for.

    Returns:
        list: List of integer indices of all parent GROUP layers, ordered from
            immediate parent to topmost parent.
    """
    mp = layer.id_data.mp

    cur = layer
    parent = layer
    parent_list = []

    while True:
        if cur.parent_idx != -1:

            try:
                layer = mp.layers[cur.parent_idx]
            except (IndexError, KeyError):
                break

            if layer.type == "GROUP":
                parent = layer
                parent_list.append(cur.parent_idx)

        if parent == cur:
            break

        cur = parent

    return parent_list


def get_last_chained_up_layer_ids(layer, idx_limit):
    """Get the topmost parent layer index up to a specified limit.

    Traverses up the parent chain until reaching the limit index or the top
    of the hierarchy.

    Args:
        layer: The layer object to start from.
        idx_limit (int): The parent index to stop at. Traversal stops when
            reaching this parent.

    Returns:
        int: The index of the topmost parent layer found before the limit,
            or the original layer index if no parents exist.
    """
    mp = layer.id_data.mp
    layer_idx = get_layer_index(layer)

    cur = layer
    parent = layer
    parent_idx = layer_idx

    while True:
        if cur.parent_idx != -1 and cur.parent_idx != idx_limit:

            try:
                layer = mp.layers[cur.parent_idx]
            except (IndexError, KeyError):
                break

            if layer.type == "GROUP":
                parent = layer
                parent_idx = cur.parent_idx

        if parent == cur:
            break

        cur = parent

    return parent_idx


def get_last_child_idx(layer):
    """Get the index of the last descendant layer in a group.

    For GROUP layers, finds the last (deepest) child layer in the hierarchy.
    For non-GROUP layers, returns the layer's own index.

    Args:
        layer: The layer object to find the last child for.

    Returns:
        int: The index of the last descendant layer, or the layer's own index
            if it's not a GROUP or has no children.
    """
    mp = layer.id_data.mp
    layer_idx = get_layer_index(layer)

    if layer.type != "GROUP":
        return layer_idx

    for i, t in reversed(list(enumerate(mp.layers))):
        if i > layer_idx and layer_idx in get_list_of_parent_ids(t):
            return i

    return layer_idx


def get_upper_neighbor(layer):
    """Get the neighboring layer above the current layer in the hierarchy.

    Finds the layer that appears immediately above in the layer stack,
    accounting for parent-child relationships.

    Args:
        layer: The layer object to find the upper neighbor for.

    Returns:
        tuple: A tuple containing:
            - neighbor_idx (int or None): Index of the upper neighbor layer,
                or None if at the top of the stack.
            - neighbor (Layer or None): The upper neighbor layer object,
                or None if at the top of the stack.
    """
    mp = layer.id_data.mp
    layer_idx = get_layer_index(layer)

    if layer_idx == 0:
        return None, None

    if layer.parent_idx == layer_idx - 1:
        return layer_idx - 1, mp.layers[layer_idx - 1]

    upper_layer = mp.layers[layer_idx - 1]

    neighbor_idx = get_last_chained_up_layer_ids(upper_layer, layer.parent_idx)
    neighbor = mp.layers[neighbor_idx]

    return neighbor_idx, neighbor


def get_lower_neighbor(layer):
    """Get the neighboring layer below the current layer in the hierarchy.

    Finds the layer that appears immediately below in the layer stack,
    accounting for GROUP layers and their children.

    Args:
        layer: The layer object to find the lower neighbor for.

    Returns:
        tuple: A tuple containing:
            - neighbor_idx (int or None): Index of the lower neighbor layer,
                or None if at the bottom of the stack.
            - neighbor (Layer or None): The lower neighbor layer object,
                or None if at the bottom of the stack.
    """
    mp = layer.id_data.mp
    layer_idx = get_layer_index(layer)
    last_index = len(mp.layers) - 1

    if layer_idx == last_index:
        return None, None

    if layer.type == "GROUP":
        last_child_idx = get_last_child_idx(layer)

        if last_child_idx == last_index:
            return None, None

        neighbor_idx = last_child_idx + 1
    else:
        neighbor_idx = layer_idx + 1

    neighbor = mp.layers[neighbor_idx]

    return neighbor_idx, neighbor


def get_parent_dict(mp):
    """Create a dictionary mapping layer names to their parent layer names.

    Args:
        mp: The MPaint data structure containing layer information.

    Returns:
        dict: Dictionary where keys are layer names and values are parent layer
            names (or None if the layer has no parent or parent is invalid).
    """
    parent_dict = {}
    for t in mp.layers:
        if t.parent_idx != -1:
            try:
                parent_dict[t.name] = mp.layers[t.parent_idx].name
            except (IndexError, KeyError):
                parent_dict[t.name] = None
        else:
            parent_dict[t.name] = None

    return parent_dict


def get_index_dict(mp):
    """Create a dictionary mapping layer names to their indices.

    Args:
        mp: The MPaint data structure containing layer information.

    Returns:
        dict: Dictionary where keys are layer names and values are their
            integer indices in the layers list.
    """
    index_dict = {}
    for i, t in enumerate(mp.layers):
        index_dict[t.name] = i

    return index_dict


def get_parent(layer):
    """Get the parent layer object of a layer.

    Args:
        layer: The layer object to get the parent for.

    Returns:
        Layer or None: The parent layer object, or None if the layer has
            no parent (parent_idx is -1).
    """
    mp = layer.id_data.mp

    if layer.parent_idx == -1:
        return None

    return mp.layers[layer.parent_idx]
