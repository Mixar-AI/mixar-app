# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Move channel operator for Mixar"""

from bpy.props import EnumProperty, IntProperty
from bpy.types import Operator

from ...core.node.node_utils import get_active_mpaint_node
from ..utils.ui_refresh import request_ui_refresh


class CHANNELS_OT_MoveChannel(Operator):
    """Move channel up or down in the list"""

    bl_idname = "channels.move_channel"
    bl_label = "Move Channel"
    bl_description = "Move channel up or down"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        items=[
            ("UP", "Up", "Move up"),
            ("DOWN", "Down", "Move down"),
        ]
    )

    channel_index: IntProperty(default=-1, options={'HIDDEN'})

    def execute(self, context):
        """Move channel up or down in the channel list.

        Moves the channel in both the root channels list and in all layer
        channels, then updates the active channel index.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure or out of bounds.
        """
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        tree = node.node_tree
        mp = tree.mp

        # Get channel index
        idx = self.channel_index if self.channel_index >= 0 else mp.active_channel_index

        if idx < 0 or idx >= len(mp.channels):
            self.report({'ERROR'}, "Invalid channel index")
            return {'CANCELLED'}

        # Calculate new index
        if self.direction == 'UP':
            new_idx = idx - 1
        else:
            new_idx = idx + 1

        # Check bounds
        if new_idx < 0 or new_idx >= len(mp.channels):
            return {'CANCELLED'}

        try:
            # Move root channel
            mp.channels.move(idx, new_idx)

            # Move channel in all layers
            for layer in mp.layers:
                layer.channels.move(idx, new_idx)

            # Update active index
            mp.active_channel_index = new_idx

            # Request UI refresh
            request_ui_refresh()

            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to move channel: {str(e)}")
            return {'CANCELLED'}


# Classes for registration
classes = (
    CHANNELS_OT_MoveChannel,
)
