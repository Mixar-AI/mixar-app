# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Enable state checking functions for layers, masks, and channels.

This module provides functions to check if layers, masks, and channels
are practically enabled (considering parent states and other conditions).
"""

import re

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ..subtree.get_subtree import (
    get_list_of_direct_children,
    get_list_of_parent_ids,
)
from ...utils.common import get_channel_index
from ..layer.layer_utils import get_layer_index


def get_layer_enabled(layer):
    """Check if layer is practically enabled or not.

    A layer is considered enabled if it is enabled itself, all parent layers
    are enabled, and at least one channel is enabled.

    Args:
        layer: The layer object to check.

    Returns:
        bool: True if the layer is enabled and usable, False otherwise.
    """
    mp = layer.id_data.mp

    # Check all parents enable
    parent_enable = True
    for parent_id in get_list_of_parent_ids(layer):
        parent = mp.layers[parent_id]
        if not parent.enable:
            parent_enable = False
            break

    # Check if no channel is enabled
    channel_enabled = False
    for ch in layer.channels:
        if ch.enable:
            channel_enabled = True
            break

    return layer.enable and parent_enable and channel_enabled


def get_mask_enabled(mask, layer=None):
    """Check if mask is practically enabled or not.

    A mask is considered enabled if its parent layer is enabled, the layer has
    masks enabled, and the mask itself is enabled.

    Args:
        mask: The mask object to check.
        layer: The parent layer object. Default: None (will auto-detect from mask path).

    Returns:
        bool: True if the mask is enabled and usable, False otherwise.
    """
    if not layer:
        mp = mask.id_data.mp
        m = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", mask.path_from_id())
        layer = mp.layers[int(m.group(1))]

    return get_layer_enabled(layer) and layer.enable_masks and mask.enable


def get_channel_enabled(ch, layer=None, root_ch=None):
    """Check if channel is practically enabled or not.

    A channel is considered enabled if its parent layer is enabled, the channel
    itself is enabled, the override_type is not PASSTHROUGH, and (for GROUP/BACKGROUND
    layers) at least one child layer has the channel enabled.

    PASSTHROUGH mode means the channel is disabled for this layer and previous
    layer values should pass through unchanged.

    Args:
        ch: The channel object to check.
        layer: The parent layer object. Default: None (will auto-detect from channel path).
        root_ch: The root channel object. Default: None (will auto-detect from channel path).

    Returns:
        bool: True if the channel is enabled and usable, False otherwise.
    """
    mp = ch.id_data.mp

    if not layer or not root_ch:
        m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", ch.path_from_id())
        layer = mp.layers[int(m.group(1))]
        root_ch = mp.channels[int(m.group(2))]

    if not get_layer_enabled(layer) or not ch.enable:
        return False

    # PASSTHROUGH mode means channel is disabled for this layer
    if hasattr(ch, 'override_type') and ch.override_type == 'PASSTHROUGH':
        return False

    channel_idx = get_channel_index(root_ch)

    if layer.type in {"BACKGROUND", "GROUP"}:

        if layer.type == "BACKGROUND":
            layer_idx = get_layer_index(layer)
            lays = [
                l
                for i, l in enumerate(mp.layers)
                if i > layer_idx and l.parent_idx == layer.parent_idx
            ]
        else:
            lays = get_list_of_direct_children(layer)

        for l in lays:
            if not l.enable:
                continue
            if channel_idx >= len(l.channels):
                continue
            c = l.channels[channel_idx]

            if l.type not in {"GROUP", "BACKGROUND"} and c.enable:
                return True

            if l.type == "GROUP" and get_channel_enabled(
                l.channels[channel_idx], l, root_ch
            ):
                return True

        return False

    else:
        for pid in get_list_of_parent_ids(layer):
            parent = mp.layers[pid]
            if (
                len(parent.channels) > channel_idx
                and not parent.channels[channel_idx].enable
            ):
                return False

    return True
