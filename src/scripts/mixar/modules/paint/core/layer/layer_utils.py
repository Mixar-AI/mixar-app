# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from ...utils.common import is_parallax_enabled


def get_channel_index_by_name(mp, name):
    """
    Get the index of a channel by its name.

    Parameters:
        mp: The MPaint node group.
        name (str): The name of the channel to find.

    Returns:
        int or None: The index of the channel if found, None otherwise.
    """
    for i, ch in enumerate(mp.channels):
        if ch.name == name:
            return i

    return None


def get_layer_channel_index(layer, ch):
    """
    Get the index of a specific channel within a layer's channel list.

    Parameters:
        layer: The layer to search within.
        ch: The channel to find.

    Returns:
        int or None: The index of the channel if found, None otherwise.
    """
    for i, c in enumerate(layer.channels):
        if c == ch:
            return i
    return None


def get_layer_channel_type(layer, ch):
    """
    Get the type of a layer channel.

    Parameters:
        layer: The layer containing the channel.
        ch: The channel to get the type for.

    Returns:
        str or None: The type of the channel (e.g., "NORMAL", "IMAGE") if found, None otherwise.
    """
    mp = layer.id_data.mp
    idx = get_layer_channel_index(layer, ch)
    if idx is not None:
        return mp.channels[idx].type
    return None


def get_active_layer(mp):
    """
    Get the currently active layer from the MPaint node group.

    Parameters:
        mp: The MPaint node group.

    Returns:
        Layer or None: The active layer if a valid index is set, None otherwise.
    """
    if mp.active_layer_index >= 0 and mp.active_layer_index < len(mp.layers):
        return mp.layers[mp.active_layer_index]

    return None


def get_layer_index(layer):
    """
    Get the index of a layer in the MPaint layer list.

    Parameters:
        layer: The layer to find the index for.

    Returns:
        int or None: The index of the layer if found, None otherwise.
    """
    mp = layer.id_data.mp

    for i, t in enumerate(mp.layers):
        if layer == t:
            return i


def get_layer_index_by_name(mp, name):
    """
    Get the index of a layer by its name.

    Parameters:
        mp: The MPaint node group.
        name (str): The name of the layer to find.

    Returns:
        int: The index of the layer if found, -1 otherwise.
    """
    for i, t in enumerate(mp.layers):
        if name == t.name:
            return i

    return -1


def get_layer_from_node_name(mp, node_name):
    """
    Get a layer by its associated node name.

    Parameters:
        mp: The MPaint node group.
        node_name (str): The name of the node associated with the layer.

    Returns:
        Layer or None: The layer if found, None otherwise.
    """
    layer = None

    for l in mp.layers:
        if l.group_node == node_name:
            layer = l
            break

    return layer


def get_transition_bump_channel(layer):
    """
    Get the first enabled transition bump channel from a layer.

    Parameters:
        layer: The layer to search for a transition bump channel.

    Returns:
        Channel or None: The first enabled transition bump channel if found, None otherwise.
    """
    mp = layer.id_data.mp

    bump_ch = None
    for i, ch in enumerate(layer.channels):
        if mp.channels[i].type == "NORMAL" and ch.enable and ch.enable_transition_bump:
            bump_ch = ch
            break

    return bump_ch


def get_showed_transition_bump_channel(layer):
    """
    Get the first visible transition bump channel from a layer.

    Parameters:
        layer: The layer to search for a visible transition bump channel.

    Returns:
        Channel or None: The first visible transition bump channel if found, None otherwise.
    """
    mp = layer.id_data.mp

    bump_ch = None
    for i, ch in enumerate(layer.channels):
        if mp.channels[i].type == "NORMAL" and ch.show_transition_bump:
            bump_ch = ch
            break

    return bump_ch


def get_root_parallax_channel(mp):
    """
    Get the first root channel with parallax enabled.

    Parameters:
        mp: The MPaint node group.

    Returns:
        Channel or None: The first NORMAL type channel with parallax enabled if found, None otherwise.
    """
    for ch in mp.channels:
        if ch.type == "NORMAL" and is_parallax_enabled(ch):
            return ch

    return None


def get_root_height_channel(mp):
    """
    Get the first root channel of NORMAL type (used for height maps).

    Parameters:
        mp: The MPaint node group.

    Returns:
        Channel or None: The first NORMAL type channel if found, None otherwise.
    """
    for ch in mp.channels:
        if ch.type == "NORMAL":
            return ch

    return None


def get_height_channel(layer):
    """
    Get the height channel from a layer (corresponding to the first NORMAL root channel).

    Parameters:
        layer: The layer to get the height channel from.

    Returns:
        Channel or None: The layer channel corresponding to the first NORMAL root channel if found, None otherwise.
    """
    mp = layer.id_data.mp

    for i, ch in enumerate(layer.channels):
        root_ch = mp.channels[i]
        if root_ch.type == "NORMAL":
            return ch

    return None


def get_smooth_bump_channel(layer):
    """
    Get the first smooth bump channel from a layer.

    Parameters:
        layer: The layer to get the smooth bump channel from.

    Returns:
        Channel or None: The first layer channel corresponding to a NORMAL root channel with smooth bump enabled, None otherwise.
    """
    mp = layer.id_data.mp

    for i, root_ch in enumerate(mp.channels):
        if root_ch.type == "NORMAL" and root_ch.enable_smooth_bump:
            return layer.channels[i]

    return None


def get_smooth_bump_channels(layer):
    """
    Get all smooth bump channels from a layer.

    Parameters:
        layer: The layer to get smooth bump channels from.

    Returns:
        list: A list of layer channels corresponding to NORMAL root channels with smooth bump enabled.
    """
    mp = layer.id_data.mp

    channels = []

    for i, root_ch in enumerate(mp.channels):
        if root_ch.type == "NORMAL" and root_ch.enable_smooth_bump:
            channels.append(layer.channels[i])

    return channels


def get_layer_and_root_ch_from_layer_ch(ch):
    """
    Extract the parent layer and root channel from a layer channel using path parsing.

    Parameters:
        ch: The layer channel to extract information from.

    Returns:
        tuple: A tuple containing (layer, root_ch) where:
            - layer: The parent layer of the channel, or None if not found.
            - root_ch: The corresponding root channel, or None if not found.
    """
    mp = ch.id_data.mp
    layer = None
    root_ch = None

    match = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", ch.path_from_id())
    if match:
        layer = mp.layers[int(match.group(1))]
        root_ch = mp.channels[int(match.group(2))]

    return layer, root_ch


def update_preview_mix(ch, preview):
    """
    Update the mix blend type in a preview node to match the channel's blend type.

    Parameters:
        ch: The channel whose blend type should be applied.
        preview: The preview node (must be of type "GROUP").

    Returns:
        None
    """
    if preview.type != "GROUP":
        return
    # Set channel layer blending
    mix = preview.node_tree.nodes.get("Mix")
    if mix and mix.blend_type != ch.blend_type:
        mix.blend_type = ch.blend_type


def get_uv_layers(obj):
    """
    Get UV layers from a mesh object.

    Parameters:
        obj: The Blender object to get UV layers from.

    Returns:
        list: A list of UV layers if the object is a mesh, empty list otherwise.
    """
    if obj.type != "MESH":
        return []
    uv_layers = obj.data.uv_layers

    return uv_layers


def has_children(layer):
    """
    Check if a layer has child layers (only GROUP type layers can have children).

    Parameters:
        layer: The layer to check for children.

    Returns:
        bool: True if the layer has at least one child layer, False otherwise.
    """
    mp = layer.id_data.mp

    if layer.type != "GROUP":
        return False

    layer_idx = get_layer_index(layer)

    if layer_idx < len(mp.layers) - 1:
        neighbor = mp.layers[layer_idx + 1]
        if neighbor.parent_idx == layer_idx:
            return True

    return False


def is_top_member(layer, enabled_only=False):
    """
    Check if a layer is the top member of its parent group.

    Parameters:
        layer: The layer to check.
        enabled_only (bool): If True, only consider enabled layers. Default: False.

    Returns:
        bool: True if the layer is the first child of its parent, False otherwise.
    """
    if layer.parent_idx == -1:
        return False

    mp = layer.id_data.mp

    for i, t in enumerate(mp.layers):
        if enabled_only and not t.enable:
            continue
        if t == layer:
            if layer.parent_idx == i - 1:
                return True
            else:
                return False

    return False


def is_bottom_member(layer, enabled_only=False):
    """
    Check if a layer is the bottom member of its parent group.

    Parameters:
        layer: The layer to check.
        enabled_only (bool): If True, only consider enabled layers. Default: False.

    Returns:
        bool: True if the layer is the last child of its parent, False otherwise.
    """
    if layer.parent_idx == -1:
        return False

    mp = layer.id_data.mp

    layer_idx = -1
    last_member_idx = -1
    for i, t in enumerate(mp.layers):
        if enabled_only and not t.enable:
            continue
        if t == layer:
            layer_idx = i
        if t.parent_idx == layer.parent_idx:
            last_member_idx = i

    if layer_idx == last_member_idx:
        return True

    return False


def is_parent_hidden(layer):
    """
    Check if any parent layer in the hierarchy is hidden (disabled).

    Parameters:
        layer: The layer to check parent visibility for.

    Returns:
        bool: True if any parent in the hierarchy is disabled, False otherwise.
    """
    mp = layer.id_data.mp

    hidden = False

    cur = layer
    parent = layer

    while True:
        if cur.parent_idx != -1:

            try:
                layer = mp.layers[cur.parent_idx]
            except (IndexError, KeyError):
                break

            if layer.type == "GROUP":
                parent = layer
                if not parent.enable:
                    hidden = True
                    break

        if parent == cur:
            break

        cur = parent

    return hidden
