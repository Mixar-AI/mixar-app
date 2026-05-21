# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Invoke logic for merge layer operator"""

from ....core.layer.get_entities import any_dirty_images_inside_layer
from ....core.layer.layer_utils import get_root_height_channel
from ....core.node.get_nodes import get_layer_source
from ....core.subtree.get_subtree import get_lower_neighbor, get_upper_neighbor
from ....utils.common import get_channel_index


def validate_merge_layer(operator, mp, layer, direction):
    """
    Validate that merge operation can proceed.

    Args:
        operator: The operator instance to store results on
        mp: The material paint data
        layer: The active layer to merge
        direction: "UP" or "DOWN" for merge direction

    Returns:
        str: Error message if validation fails, empty string if valid
    """
    error_message = ""

    # Check for enabled channels
    enabled_chs = [ch for ch in layer.channels if ch.enable]
    if not any(enabled_chs):
        return "Need at least one layer channel enabled!"

    # Get neighbor based on direction
    if direction == "UP":
        neighbor_idx, neighbor_layer = get_upper_neighbor(layer)
    else:  # DOWN
        neighbor_idx, neighbor_layer = get_lower_neighbor(layer)

    # Store neighbor info on operator
    operator.neighbor_idx = neighbor_idx
    operator.neighbor_layer = neighbor_layer

    if not neighbor_layer:
        return "No neighbor found!"

    if not neighbor_layer.enable or not layer.enable:
        return "Both layer should be enabled!"

    if neighbor_layer.parent_idx != layer.parent_idx:
        return "Cannot merge with layer with different parent!"

    if neighbor_layer.type == "GROUP" or layer.type == "GROUP":
        return "Merge doesn't works with layer group!"

    return error_message


def validate_height_channels(operator, mp, layer, neighbor_layer):
    """
    Validate height channel compatibility between layers.

    Args:
        operator: The operator instance to store results on
        mp: The material paint data
        layer: The active layer
        neighbor_layer: The neighbor layer to merge with

    Returns:
        str: Error message if validation fails, empty string if valid
    """
    height_root_ch = get_root_height_channel(mp)
    operator.height_root_ch = height_root_ch

    if height_root_ch and neighbor_layer:
        height_ch_idx = get_channel_index(height_root_ch)
        operator.height_ch_idx = height_ch_idx
        height_ch = layer.channels[height_ch_idx]
        operator.height_ch = height_ch
        neighbor_height_ch = neighbor_layer.channels[height_ch_idx]
        operator.neighbor_height_ch = neighbor_height_ch

        if (
            layer.channels[height_ch_idx].enable
            and neighbor_layer.channels[height_ch_idx].enable
        ):
            if height_ch.normal_map_type != neighbor_height_ch.normal_map_type:
                return "These two layers has different normal map type!"
    else:
        operator.height_ch = None
        operator.neighbor_height_ch = None

    return ""


def validate_layer_source(layer):
    """
    Validate that the layer has a valid source.

    Args:
        layer: The layer to validate

    Returns:
        tuple: (source, error_message) - source object and error string
    """
    source = get_layer_source(layer)

    if layer.type == "IMAGE":
        if not source.image:
            return source, "This layer has no image!"

    return source, ""


def set_default_channel_index(operator, layer, neighbor_layer):
    """
    Set the default channel index for the merge operation.

    Args:
        operator: The operator instance
        layer: The active layer
        neighbor_layer: The neighbor layer
    """
    for i, c in enumerate(layer.channels):
        nc = neighbor_layer.channels[i]
        if c.enable and nc.enable:
            operator.channel_idx = str(i)
            break


def check_dirty_images(layer, neighbor_layer):
    """
    Check if there are any unsaved images in either layer.

    Args:
        layer: The active layer
        neighbor_layer: The neighbor layer

    Returns:
        bool: True if there are unsaved images
    """
    return any_dirty_images_inside_layer(neighbor_layer) or any_dirty_images_inside_layer(layer)
