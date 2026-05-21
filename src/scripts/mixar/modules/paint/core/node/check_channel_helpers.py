# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Helper functions for channel blend node operations.

This module contains utility functions for validating and managing
height pack and spread alpha nodes.
"""

from ..layer.get_channels import get_channel_enabled
from ..node.node_utils import remove_node


def is_valid_to_remove_bump_nodes(layer, ch):
    """
    Check if it's valid to remove bump nodes for a given layer and channel.

    Parameters:
        layer: Layer object to check.
        ch: Channel object to check.

    Returns:
        True if bump nodes can be removed, False otherwise.
    """

    if layer.type == "COLOR" and (
        (ch.enable_transition_bump and ch.enable)
        or len(layer.masks) == 0
        or ch.transition_bump_chain == 0
    ):
        return True

    return False


def check_create_height_pack(layer, tree, height_root_ch, height_ch):
    """
    Check and manage height pack/unpack nodes for a channel.

    Parameters:
        layer: Layer object containing the channel.
        tree: Node tree to check for height pack nodes.
        height_root_ch: Root height channel.
        height_ch: Height channel to check.

    Returns:
        True if nodes were removed and reconnection is needed, False otherwise.
    """

    channel_enabled = get_channel_enabled(height_ch, layer, height_root_ch)
    need_reconnect = False
    if remove_node(tree, height_ch, "height_group_unpack"):
        need_reconnect = True
    if remove_node(tree, height_ch, "height_alpha_group_unpack"):
        need_reconnect = True

    return need_reconnect


def check_create_spread_alpha(layer, tree, root_ch, ch):
    """
    Check and manage spread alpha nodes for a channel.

    Parameters:
        layer: Layer object containing the channel.
        tree: Node tree to check for spread alpha nodes.
        root_ch: Root channel object.
        ch: Channel to check.

    Returns:
        True if nodes were removed and reconnection is needed, False otherwise.
    """

    channel_enabled = get_channel_enabled(ch, layer, root_ch)
    need_reconnect = False

    if remove_node(tree, ch, "spread_alpha"):
        need_reconnect = True

    return need_reconnect
