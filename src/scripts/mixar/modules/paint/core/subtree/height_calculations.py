# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Height calculation operations for layers and channels.

This module provides functions for calculating height values including
maximum heights, transition displacement, and channel heights.
"""

from ...utils.common import get_channel_index, get_write_height
from ..node.node_graph import (
    get_layer_channel_bump_distance,
    get_transition_bump_max_distance,
    get_transition_bump_max_distance_with_crease,
)
from .layer_hierarchy import get_list_of_direct_children


def get_max_child_height(layer, ch_idx):
    """Get the maximum height value among all child layers for a specific channel.

    Recursively calculates the maximum height across all direct children of a
    GROUP layer for the specified channel index.

    Args:
        layer: The GROUP layer to get child heights for.
        ch_idx (int): The channel index to evaluate.

    Returns:
        float: The maximum height value found among all children, or 0.0 if
            the layer has no children.
    """
    # Get children
    children = get_list_of_direct_children(layer)

    if len(children) == 0:
        return 0.0

    max_child_height = None
    for child in children:
        for i, c in enumerate(child.channels):
            if i != ch_idx:
                continue

            # Do recursive the children is a group
            if child.type == "GROUP":
                h = get_max_child_height(child, ch_idx)
            else:
                h = get_layer_channel_max_height(child, c, ch_idx)

            if max_child_height is None or h > max_child_height:
                max_child_height = h

    return max_child_height


def get_transition_disp_delta(layer, ch):
    """Calculate the transition displacement delta for a channel.

    Computes the difference between the maximum transition bump distance and
    the current height/bump distance.

    Args:
        layer: The layer object to calculate the delta for.
        ch: The channel object to calculate the delta for.

    Returns:
        float: The displacement delta value.
    """
    if layer.type == "GROUP":

        # Get channel index
        ch_idx = [i for i, c in enumerate(layer.channels) if c == ch][0]

        max_child_height = get_max_child_height(layer, ch_idx)
        delta = get_transition_bump_max_distance(ch) - max_child_height

    else:
        ##### REPLACED_BY_SHADERS

        bump_distance = (
            ch.normal_bump_distance
            if ch.normal_map_type == "NORMAL_MAP"
            else get_layer_channel_bump_distance(layer, ch)
        )
        delta = get_transition_bump_max_distance(ch) - abs(bump_distance)

        #####

    return delta


def get_max_height_from_list_of_layers(
    layers, ch_index, layer=None, top_layers_only=False
):
    """Calculate the maximum height from a list of layers for a specific channel.

    Evaluates layers based on their blend types (MIX, COMPARE, OVERLAY) and
    calculates the cumulative maximum height value.

    Args:
        layers (list): List of layer objects to evaluate.
        ch_index (int): The channel index to calculate height for.
        layer (optional): If provided, stops evaluation at this layer.
            Defaults to None.
        top_layers_only (bool, optional): If True, only evaluates top-level
            layers (with parent_idx == -1). Defaults to False.

    Returns:
        float: The maximum height value calculated from the layers.
    """
    max_height = 0.0

    for l in reversed(layers):
        if ch_index > len(l.channels) - 1:
            continue
        if top_layers_only and l.parent_idx != -1:
            continue
        c = l.channels[ch_index]
        write_height = get_write_height(c)
        ch_max_height = get_layer_channel_max_height(l, c)
        if (
            l.enable
            and c.enable
            and (write_height or (not write_height and l == layer))
            and c.normal_blend_type in {"MIX", "COMPARE"}
            and max_height < ch_max_height
        ):
            max_height = ch_max_height
        if l == layer:
            break

    for l in reversed(layers):
        if ch_index > len(l.channels) - 1:
            continue
        if top_layers_only and l.parent_idx != -1:
            continue
        c = l.channels[ch_index]
        write_height = get_write_height(c)
        ch_max_height = get_layer_channel_max_height(l, c)
        if (
            l.enable
            and c.enable
            and (write_height or (not write_height and l == layer))
            and c.normal_blend_type == "OVERLAY"
        ):
            max_height += ch_max_height
        if l == layer:
            break

    return max_height


def get_displacement_max_height(root_ch, layer=None):
    """Get the maximum displacement height for a root channel.

    Retrieves and calculates the final maximum height value including any
    tweak adjustments from the node tree.

    Args:
        root_ch: The root channel object to get max height for.
        layer (optional): Reserved for future use. Defaults to None.

    Returns:
        float: The maximum displacement height value, including tweaks.
            Defaults to 1.0 if no height nodes are found.
    """
    mp = root_ch.id_data.mp
    tree = root_ch.id_data
    ch_index = get_channel_index(root_ch)

    max_height = 1.0

    end_max_height = tree.nodes.get(root_ch.end_max_height)
    if end_max_height:
        max_height = end_max_height.outputs[0].default_value

    end_max_height_tweak = tree.nodes.get(root_ch.end_max_height_tweak)
    if end_max_height_tweak and "Height Tweak" in end_max_height_tweak.inputs:
        max_height *= end_max_height_tweak.inputs["Height Tweak"].default_value

    return max_height


def get_layer_channel_max_height(layer, ch, ch_idx=None):
    """Calculate the maximum height for a specific layer channel.

    Computes the maximum height considering bump distance, transition bump
    settings, and intensity value. For GROUP layers, recursively evaluates
    all children.

    Args:
        layer: The layer object to calculate height for.
        ch: The channel object to calculate height for.
        ch_idx (int, optional): The channel index. If None, derives it from
            the channel object. Defaults to None.

    Returns:
        float: The maximum height value for the layer channel, accounting for
            all modifiers and settings.
    """
    if layer.type == "GROUP":

        if ch_idx is None:
            ch_idx = [i for i, c in enumerate(layer.channels) if c == ch][0]
        children = get_list_of_direct_children(layer)
        if len(children) == 0:
            return 0.0

        # Check all of its children
        base_distance = None
        for child in children:
            for i, c in enumerate(child.channels):
                if i != ch_idx:
                    continue

                h = get_layer_channel_max_height(child, c)

                if base_distance is None or h > base_distance:
                    base_distance = h

    else:
        base_distance = (
            abs(ch.normal_bump_distance)
            if ch.normal_map_type == "NORMAL_MAP"
            else abs(get_layer_channel_bump_distance(layer, ch))
        )

    if ch.enable_transition_bump:
        if ch.normal_map_type == "NORMAL_MAP" and layer.type != "GROUP":
            max_height = abs(get_transition_bump_max_distance_with_crease(ch))
        else:
            if ch.transition_bump_flip:
                max_height = (
                    abs(get_transition_bump_max_distance_with_crease(ch))
                    + base_distance * 2
                )

            else:
                max_height = (
                    abs(get_transition_bump_max_distance_with_crease(ch))
                    + base_distance
                )

    else:
        max_height = base_distance if base_distance is not None else 0.0

    # Multiply by intensity value
    max_height *= ch.intensity_value

    return max_height


def has_channel_children(layer, root_ch):
    """Check if a GROUP layer has any enabled children for a specific channel.

    Args:
        layer: The layer object to check for channel children.
        root_ch: The root channel object to check.

    Returns:
        bool: True if the layer is a GROUP and has at least one enabled child
            with the specified channel enabled, False otherwise.
    """
    mp = layer.id_data.mp

    if layer.type != "GROUP":
        return False

    ch_idx = get_channel_index(root_ch)
    children = get_list_of_direct_children(layer)

    for child in children:
        if not child.enable:
            continue
        for i, ch in enumerate(child.channels):
            if i == ch_idx and ch.enable:
                return True

    return False
