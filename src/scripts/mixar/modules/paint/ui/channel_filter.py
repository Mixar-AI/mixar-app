# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel filter utilities for Mixar paint UI.

This module provides dynamic enum items callback for channel filter dropdown,
used in the Substance 3D Painter-style layer panel.
"""

from ..core.node.node_utils import get_active_mpaint_node


def get_channel_filter_items(self, context):
    """Dynamic enum items callback for channel filter dropdown.

    Generates enum items based on available channels in the active Mixar node.
    Used in the Substance 3D Painter-style layer panel for selecting which
    channel's blend mode and opacity to display inline.

    Args:
        self: Property owner (MixarUIState).
        context: Blender context.

    Returns:
        list: List of (identifier, name, description, icon, index) tuples.
    """
    items = []

    # Get active Mixar node to access channels
    node = get_active_mpaint_node()
    if node and node.node_tree and hasattr(node.node_tree, 'mp'):
        mp = node.node_tree.mp
        for i, channel in enumerate(mp.channels):
            # Use channel index as identifier for easy lookup
            identifier = str(i)
            name = channel.name
            description = f"Show {channel.name} blend mode and opacity"

            # Icon based on channel type/name
            icon_map = {
                'Color': 'COLOR',
                'Metallic': 'SHADING_SOLID',
                'Roughness': 'MATSPHERE',
                'Normal': 'NORMALS_FACE',
                'Height': 'MOD_DISPLACE',
                'Transmission': 'MATERIAL',
                'Emission': 'LIGHT',
                'Alpha': 'IMAGE_ALPHA',
                'Displacement': 'MOD_DISPLACE',
            }
            icon = icon_map.get(channel.name, 'TEXTURE')

            items.append((identifier, name, description, icon, i))

    # Fallback if no channels available
    if not items:
        items.append(('0', 'Base Color', 'No channels available', 'COLOR', 0))

    return items
