# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel modifier popup operator for managing channel-level modifiers."""

import bpy
from bpy.props import IntProperty
from bpy.types import Operator

from ...core.modifier.modifier import can_be_expanded, draw_modifier_properties
from ...core.node.node_utils import get_active_mpaint_node
from ...core.subtree.get_subtree import get_mod_tree


class CHANNEL_OT_ModifiersPopup(Operator):
    """Open channel modifiers popup"""

    bl_idname = "channel.modifiers_popup"
    bl_label = "Channel Modifiers"
    bl_description = "Manage modifiers for this channel"
    bl_options = {"INTERNAL"}

    layer_index: IntProperty(default=-1)
    channel_index: IntProperty(default=-1)

    def invoke(self, context, event):
        """Show modifiers popup.

        Args:
            context: Blender context.
            event: Event that triggered the operator.

        Returns:
            set: Result from popup invocation.
        """
        return context.window_manager.invoke_popup(self, width=350)

    def draw(self, context):
        """Draw modifiers UI.

        Args:
            context: Blender context.
        """
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        node = get_active_mpaint_node()
        if not node:
            layout.label(text="No active paint node", icon='ERROR')
            return

        mp = node.node_tree.mp

        if self.layer_index < 0 or self.layer_index >= len(mp.layers):
            layout.label(text="Invalid layer index", icon='ERROR')
            return

        layer = mp.layers[self.layer_index]

        if self.channel_index < 0 or self.channel_index >= len(layer.channels):
            layout.label(text="Invalid channel index", icon='ERROR')
            return

        channel = layer.channels[self.channel_index]
        root_ch = mp.channels[self.channel_index]
        channel_type = root_ch.type

        main_col = layout.column(align=False)

        # Header with title and add menu
        header_box = main_col.box()
        header_row = header_box.row(align=True)
        header_row.scale_y = 1.4
        header_row.label(text="Modifiers", icon='MODIFIER')
        header_row.separator()

        # Add menu button
        add_row = header_row.row(align=True)
        add_row.context_pointer_set("parent", channel)
        add_row.context_pointer_set("layer", layer)
        add_row.menu("CHANNEL_MODIFIERS_MT_add_menu", text="", icon='ADD')

        # Modifier list
        if len(channel.modifiers) == 0:
            info_box = main_col.box()
            info_col = info_box.column(align=True)
            info_col.scale_y = 1.2
            info_col.label(text="No modifiers", icon='INFO')
            info_col.label(text="Click + to add a modifier")
        else:
            self._draw_modifier_list(
                context, main_col, layer, channel, root_ch, channel_type
            )

    def _draw_modifier_list(
        self, context, layout, layer, channel, root_ch, channel_type
    ):
        """Draw the list of modifiers.

        Args:
            context: Blender context.
            layout: UI layout.
            layer: The layer containing the channel.
            channel: The channel containing modifiers.
            root_ch: The root channel definition.
            channel_type: Type of channel (RGB, VALUE, NORMAL).
        """
        mod_tree = get_mod_tree(channel)
        nodes = mod_tree.nodes if mod_tree else []

        for i, modifier in enumerate(channel.modifiers):
            mod_box = layout.box()
            mod_col = mod_box.column(align=True)

            # Header row with enable, name, and controls
            header_row = mod_col.row(align=True)
            header_row.scale_y = 1.2

            # Enable toggle
            header_row.prop(modifier, "enable", text="")

            # Expand/collapse button and name
            can_expand = modifier.type in can_be_expanded
            if can_expand:
                icon = 'TRIA_DOWN' if modifier.expand_content else 'TRIA_RIGHT'
                header_row.prop(
                    modifier, "expand_content",
                    text=modifier.name, icon=icon, emboss=False
                )
            else:
                header_row.label(text=modifier.name)

            # Spacer
            header_row.separator()

            # Move up button
            ctrl_row = header_row.row(align=True)
            ctrl_row.context_pointer_set("parent", channel)
            ctrl_row.context_pointer_set("layer", layer)
            ctrl_row.context_pointer_set("modifier", modifier)

            up_op = ctrl_row.operator(
                "wm.m_move_mpaint_modifier",
                text="", icon='TRIA_UP'
            )
            up_op.direction = 'UP'

            # Move down button
            down_op = ctrl_row.operator(
                "wm.m_move_mpaint_modifier",
                text="", icon='TRIA_DOWN'
            )
            down_op.direction = 'DOWN'

            # Delete button
            ctrl_row.operator(
                "wm.m_remove_mpaint_modifier",
                text="", icon='X'
            )

            # Expanded content
            if can_expand and modifier.expand_content:
                content_col = mod_col.column(align=True)
                content_col.active = modifier.enable
                content_col.separator(factor=0.5)
                draw_modifier_properties(
                    context, channel_type, nodes, modifier, channel, content_col
                )

    def execute(self, context):
        """Close the popup.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'}.
        """
        return {"FINISHED"}


classes = (
    CHANNEL_OT_ModifiersPopup,
)
