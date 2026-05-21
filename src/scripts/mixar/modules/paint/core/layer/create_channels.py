# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ..node.check_nodes import check_mp_channel_nodes

def create_new_mp_channel(group_tree, name, channel_type, non_color=True, enable=False):
    """Create a new MPaint channel in the material.

    This function creates a new channel, sets up its properties, and initializes
    it in all existing layers.

    Args:
        group_tree: The node group tree to add the channel to.
        name (str): The name of the new channel.
        channel_type (str): The type of channel ('RGB', 'VALUE', or 'NORMAL').
        non_color (bool): Whether the channel uses non-color (linear) data. Default: True.
        enable (bool): Whether the channel is enabled in layers by default. Default: False.

    Returns:
        The newly created channel object.
    """
    mp = group_tree.mp

    mp.halt_reconnect = True

    channel = mp.channels.add()
    channel.name = name
    channel.original_name = name
    channel.bake_to_vcol_name = 'Baked ' + name
    channel.type = channel_type

    # Get last index
    last_index = len(mp.channels) - 1

    # Link new channel
    check_mp_channel_nodes(mp)

    for layer in mp.layers:
        # New channel is disabled in layer by default
        layer.channels[last_index].enable = enable

    if channel_type in {'RGB', 'VALUE'}:
        if non_color:
            channel.colorspace = 'LINEAR'
        else: channel.colorspace = 'SRGB'
    else:
        # NOTE: Smooth bump is no longer enabled by default at all
        #if is_bl_newer_than(2, 80):
        channel.enable_smooth_bump = False

    # Emission values can exceed 1.0 (HDR), so disable clamping
    # Matches ucupaint: self.use_clamp = 'Emission' not in self.name
    if 'Emission' in name:
        channel.use_clamp = False

    mp.halt_reconnect = False

    return channel