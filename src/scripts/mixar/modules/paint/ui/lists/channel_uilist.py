# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UIList for displaying paint channels in the Texture Sets panel."""

import bpy
from bpy.types import UIList

from ...core.node.node_utils import get_active_mpaint_node
from ...core.lib.lib import channel_custom_icon_dict
from ...core.lib.lib_operations import get_icon


class CHANNELS_UL_channel_list(UIList):
    """UIList for displaying paint channels.

    Displays each channel with:
    - Type icon (VALUE, RGB, NORMAL) - uses custom icons matching ucupaint
    - Editable channel name
    - Default value or link status indicator
    """

    bl_idname = "CHANNELS_UL_channel_list"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        """Draw a single channel item.

        Args:
            context: Blender context.
            layout: UI layout to draw into.
            data: The MPaint collection owner.
            item: The MPaintChannel item to draw.
            icon: Default icon.
            active_data: Active data reference.
            active_propname: Active property name.
            index: Index of the item in the collection.
        """
        channel = item  # MPaintChannel

        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)

            # Channel type icon - try custom icons first, fallback to standard
            icon_name = channel_custom_icon_dict.get(channel.type, 'rgb_channel')
            icon_value = get_icon(icon_name)

            if icon_value:
                row.prop(channel, "name", text="", emboss=False, icon_value=icon_value)
            else:
                # Fallback to standard Blender icons
                fallback_icons = {
                    'VALUE': 'SHADING_TEXTURE',
                    'RGB': 'COLOR',
                    'NORMAL': 'NORMALS_FACE'
                }
                fallback_icon = fallback_icons.get(channel.type, 'DOT')
                row.prop(channel, "name", text="", emboss=False, icon=fallback_icon)

            # Default value or link status
            self._draw_value_or_link(row, context, channel)

        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            icon_name = channel_custom_icon_dict.get(channel.type, 'rgb_channel')
            icon_value = get_icon(icon_name)
            if icon_value:
                layout.label(text="", icon_value=icon_value)
            else:
                fallback_icons = {'VALUE': 'SHADING_TEXTURE', 'RGB': 'COLOR', 'NORMAL': 'NORMALS_FACE'}
                layout.label(text="", icon=fallback_icons.get(channel.type, 'DOT'))

    def _draw_value_or_link(self, layout, context, channel):
        """Draw default value picker or link status indicator.

        Args:
            layout: UI layout to draw into.
            context: Blender context.
            channel: MPaintChannel item.
        """
        node = get_active_mpaint_node()
        if not node:
            return

        io_index = channel.io_index
        if io_index < 0 or io_index >= len(node.inputs):
            return

        inp = node.inputs[io_index]

        # For RGB channels, create an inner row for alignment
        if channel.type == 'RGB':
            row = layout.row(align=True)
        else:
            row = layout

        # If linked, show link icon
        if len(inp.links) > 0:
            row.label(text="", icon='LINKED')
        else:
            # Show value picker based on type
            sub = row.row(align=True)
            sub.scale_x = 0.6
            if channel.type == 'VALUE':
                sub.prop(inp, 'default_value', text="")
            elif channel.type == 'RGB':
                sub.prop(inp, 'default_value', text="", icon='COLOR')
            # NORMAL channels don't show a default value

        # For RGB with alpha enabled, show alpha input too
        if channel.type == 'RGB' and hasattr(channel, 'enable_alpha') and channel.enable_alpha:
            alpha_index = io_index + 1
            if alpha_index < len(node.inputs):
                alpha_inp = node.inputs[alpha_index]
                if len(alpha_inp.links) > 0:
                    row.label(text="", icon='LINKED')
                else:
                    sub = row.row(align=True)
                    sub.scale_x = 0.4
                    sub.prop(alpha_inp, 'default_value', text="")

    def filter_items(self, context, data, propname):
        """Filter and order items in the list.

        Args:
            context: Blender context.
            data: Data containing the collection.
            propname: Name of the collection property.

        Returns:
            Tuple of (filter_flags, filter_neworder) lists.
        """
        channels = getattr(data, propname)
        filter_flags = [self.bitflag_filter_item] * len(channels)
        filter_neworder = []

        return filter_flags, filter_neworder


# Classes for registration
classes = (
    CHANNELS_UL_channel_list,
)
