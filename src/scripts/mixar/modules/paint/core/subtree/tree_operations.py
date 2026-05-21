# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tree retrieval operations for node trees.

This module provides functions for retrieving and navigating node trees
associated with layers, channels, and masks.
"""

import re


def get_tree(entity):
    """Get the node tree associated with an entity (layer or channel).

    Searches for the entity's group node in the mp tree or trash and returns
    the associated node tree.

    Args:
        entity: The entity (layer or channel) to get the tree for.

    Returns:
        NodeTree or None: The node tree if the group node exists and is valid,
            None otherwise.
    """
    # Search inside mp tree
    tree = entity.id_data
    mp = tree.mp
    group_node = None

    if entity.trash_group_node != "":
        trash = tree.nodes.get(mp.trash)
        if trash:
            group_node = trash.node_tree.nodes.get(entity.trash_group_node)
    else:
        group_node = tree.nodes.get(entity.group_node)

    if not group_node or group_node.type != "GROUP":
        return None
    return group_node.node_tree


def get_source_tree(layer, tree=None):
    """Get the source tree for a layer.

    Returns the layer's source group node tree if it exists, otherwise returns
    the layer's main tree.

    Args:
        layer: The layer object to get the source tree for.
        tree (NodeTree, optional): The layer's node tree. If None, retrieves it
            using get_tree(). Defaults to None.

    Returns:
        NodeTree or None: The source tree if available, the layer tree if no
            source group exists, or None if the tree cannot be retrieved.
    """
    if not tree:
        tree = get_tree(layer)
    if not tree:
        return None

    if layer.source_group != "":
        source_group = tree.nodes.get(layer.source_group)
        return source_group.node_tree

    return tree


def get_mod_tree(entity):
    """Get the modifier tree for an entity (channel or layer).

    Determines the appropriate modifier node tree based on the entity's path
    and structure. Handles both layer channels and standalone channels.

    Args:
        entity: The entity (channel or layer) to get the modifier tree for.

    Returns:
        NodeTree or None: The modifier node tree if it exists, the layer/channel
            tree if no modifier group exists, or None if not found.
    """
    mp = entity.id_data.mp

    m = re.match(r"^mp\.channels\[(\d+)\].*", entity.path_from_id())
    if m:
        return entity.id_data

    m = re.match(r"^mp\.layers\[(\d+)\]\.channels\[(\d+)\].*", entity.path_from_id())
    if m:
        layer = mp.layers[int(m.group(1))]
        ch = layer.channels[int(m.group(2))]
        tree = get_tree(layer)

        mod_group = tree.nodes.get(ch.mod_group)
        if mod_group and mod_group.type == "GROUP":
            return mod_group.node_tree

        return tree

    m = re.match(r"^mp\.layers\[(\d+)\].*", entity.path_from_id())
    if m:
        layer = mp.layers[int(m.group(1))]
        tree = get_tree(layer)

        source_group = tree.nodes.get(layer.source_group)
        if source_group and source_group.type == "GROUP":
            tree = source_group.node_tree

        mod_group = tree.nodes.get(layer.mod_group)
        if mod_group and mod_group.type == "GROUP":
            return mod_group.node_tree

        return tree


def get_mask_tree(mask, ignore_group=False):
    """Get the node tree associated with a mask.

    Returns the mask's group node tree if it exists, or the parent layer tree
    if the mask has no group node.

    Args:
        mask: The mask object to get the tree for.
        ignore_group (bool, optional): If True, returns the layer tree directly
            without checking for a mask group node. Defaults to False.

    Returns:
        NodeTree or None: The mask's node tree (group tree or layer tree),
            or None if the mask path is invalid or tree cannot be retrieved.
    """
    m = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", mask.path_from_id())
    if not m:
        return None

    mp = mask.id_data.mp
    layer = mp.layers[int(m.group(1))]
    layer_tree = get_tree(layer)

    if ignore_group:
        return layer_tree

    if layer_tree:
        group_node = layer_tree.nodes.get(mask.group_node)
    else:
        return None

    if not group_node or group_node.type != "GROUP":
        return layer_tree
    return group_node.node_tree


def get_channel_source_tree(ch, layer=None, tree=None):
    """Get the source tree for a channel.

    Returns the channel's source group node tree if it exists, otherwise returns
    the channel's main tree.

    Args:
        ch: The channel object to get the source tree for.
        layer (optional): The layer containing the channel. If None, derives it
            from the channel's path. Defaults to None.
        tree (NodeTree, optional): The layer's node tree. If None, retrieves it
            using get_tree(). Defaults to None.

    Returns:
        NodeTree or None: The source tree if available, the channel tree if no
            source group exists, or None if the tree cannot be retrieved.
    """
    mp = ch.id_data.mp

    if not layer:
        m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", ch.path_from_id())
        if not m:
            return None
        layer = mp.layers[int(m.group(1))]

    if not tree:
        tree = get_tree(layer)
    if not tree:
        return None

    if ch.source_group != "":
        source_group = tree.nodes.get(ch.source_group)
        return source_group.node_tree

    return tree
