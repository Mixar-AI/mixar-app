# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer channel operators for Mixar

This module contains operators for managing channels within individual layers,
such as enabling/disabling channels per layer.
"""

from bpy.props import IntProperty, BoolProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes
from ...core.node.node_utils import get_active_mpaint_node
from ..utils.ui_refresh import request_ui_refresh


class LAYERS_OT_ToggleLayerChannel(Operator):
    """Toggle a channel for a specific layer"""

    bl_idname = "layers.toggle_layer_channel"
    bl_label = "Toggle Layer Channel"
    bl_description = "Enable or disable a channel for this specific layer"
    bl_options = {"REGISTER", "UNDO"}

    layer_index: IntProperty(
        name="Layer Index",
        default=-1,
        options={'HIDDEN'}
    )

    channel_index: IntProperty(
        name="Channel Index",
        default=-1,
        options={'HIDDEN'}
    )

    enable: BoolProperty(
        name="Enable",
        default=True,
        description="Whether to enable or disable the channel"
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def execute(self, context):
        """Toggle the channel enable state for the specified layer.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp

        # Get layer index
        layer_idx = self.layer_index if self.layer_index >= 0 else mp.active_layer_index

        if layer_idx < 0 or layer_idx >= len(mp.layers):
            self.report({'ERROR'}, "Invalid layer index")
            return {'CANCELLED'}

        layer = mp.layers[layer_idx]

        # Get channel index
        ch_idx = self.channel_index if self.channel_index >= 0 else mp.active_channel_index

        if ch_idx < 0 or ch_idx >= len(layer.channels):
            self.report({'ERROR'}, "Invalid channel index")
            return {'CANCELLED'}

        channel = layer.channels[ch_idx]
        root_channel = mp.channels[ch_idx] if ch_idx < len(mp.channels) else None

        try:
            # Toggle the channel
            channel.enable = self.enable

            # Reconnect and rearrange nodes
            reconnect_layer_nodes(layer)
            rearrange_layer_nodes(layer)

            action = "Enabled" if self.enable else "Disabled"
            channel_name = root_channel.name if root_channel else f"Channel {ch_idx}"
            self.report({'INFO'}, f"{action} {channel_name} for layer '{layer.name}'")

            # Request UI refresh
            request_ui_refresh()

            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to toggle channel: {str(e)}")
            return {'CANCELLED'}


class LAYERS_OT_DisableLayerChannel(Operator):
    """Disable a channel for a specific layer"""

    bl_idname = "layers.disable_layer_channel"
    bl_label = "Disable Channel for Layer"
    bl_description = "Disable this channel for the current layer only"
    bl_options = {"REGISTER", "UNDO"}

    layer_index: IntProperty(
        name="Layer Index",
        default=-1,
        options={'HIDDEN'}
    )

    channel_index: IntProperty(
        name="Channel Index",
        default=-1,
        options={'HIDDEN'}
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def execute(self, context):
        """Disable the channel for the specified layer.

        Args:
            context: Blender context.

        Returns:
            set: Result from LAYERS_OT_ToggleLayerChannel.
        """
        # Delegate to toggle operator
        return bpy.ops.layers.toggle_layer_channel(
            layer_index=self.layer_index,
            channel_index=self.channel_index,
            enable=False
        )


class LAYERS_OT_EnableLayerChannel(Operator):
    """Enable a channel for a specific layer"""

    bl_idname = "layers.enable_layer_channel"
    bl_label = "Enable Channel for Layer"
    bl_description = "Enable this channel for the current layer only"
    bl_options = {"REGISTER", "UNDO"}

    layer_index: IntProperty(
        name="Layer Index",
        default=-1,
        options={'HIDDEN'}
    )

    channel_index: IntProperty(
        name="Channel Index",
        default=-1,
        options={'HIDDEN'}
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def execute(self, context):
        """Enable the channel for the specified layer.

        Args:
            context: Blender context.

        Returns:
            set: Result from LAYERS_OT_ToggleLayerChannel.
        """
        # Delegate to toggle operator
        return bpy.ops.layers.toggle_layer_channel(
            layer_index=self.layer_index,
            channel_index=self.channel_index,
            enable=True
        )


# Need to import bpy for the delegate operators
import bpy


class CHANNEL_OT_ToggleCustomOverride(Operator):
    """Toggle custom value override for a channel"""

    bl_idname = "channel.toggle_custom_override"
    bl_label = "Toggle Custom Override"
    bl_description = "Toggle between brush mode and custom value override"
    bl_options = {"REGISTER", "UNDO"}

    channel_index: IntProperty(
        name="Channel Index",
        default=-1,
        options={'HIDDEN'}
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def execute(self, context):
        """Toggle the custom override state for the specified channel.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp

        # Get active layer
        layer_idx = mp.active_layer_index
        if layer_idx < 0 or layer_idx >= len(mp.layers):
            self.report({'ERROR'}, "No active layer")
            return {'CANCELLED'}

        layer = mp.layers[layer_idx]

        # Get channel
        ch_idx = self.channel_index
        if ch_idx < 0 or ch_idx >= len(layer.channels):
            self.report({'ERROR'}, "Invalid channel index")
            return {'CANCELLED'}

        channel = layer.channels[ch_idx]
        root_channel = mp.channels[ch_idx] if ch_idx < len(mp.channels) else None

        try:
            # Get current override_type
            # Valid values: 'LAYER', 'PASSTHROUGH', 'OVERRIDE', 'IMAGE'
            current_type = getattr(channel, 'override_type', 'LAYER')
            is_custom = current_type == 'OVERRIDE'

            if is_custom:
                # Turn off custom - back to default (brush/layer mode)
                channel.override_type = 'LAYER'
                action = "Disabled"
            else:
                # Turn on custom override
                channel.override_type = 'OVERRIDE'
                action = "Enabled"

                # For VALUE channels, set override_value to current brush luminance
                if root_channel and root_channel.type == 'VALUE':
                    luminance = self._get_brush_luminance(context)
                    if hasattr(channel, 'override_value'):
                        channel.override_value = luminance

            channel_name = root_channel.name if root_channel else f"Channel {ch_idx}"
            self.report({'INFO'}, f"{action} custom override for {channel_name}")

            # Request UI refresh
            request_ui_refresh()

            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to toggle custom override: {str(e)}")
            return {'CANCELLED'}

    def _get_brush_luminance(self, context):
        """Calculate luminance from current brush color."""
        if not context.tool_settings or not context.tool_settings.image_paint:
            return 1.0
        settings = context.tool_settings.image_paint
        brush = settings.brush
        if not brush:
            return 1.0
        ups = settings.unified_paint_settings
        color = ups.color if ups.use_unified_color else brush.color
        luminance = 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]
        return max(0.0, min(1.0, luminance))


class CHANNEL_OT_ToggleImageOverride(Operator):
    """Toggle image override for a channel"""

    bl_idname = "channel.toggle_image_override"
    bl_label = "Toggle Image Override"
    bl_description = "Toggle between layer mode and image override"
    bl_options = {"REGISTER", "UNDO"}

    channel_index: IntProperty(
        name="Channel Index",
        default=-1,
        options={'HIDDEN'}
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def execute(self, context):
        """Toggle the image override state for the specified channel.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp

        # Get active layer
        layer_idx = mp.active_layer_index
        if layer_idx < 0 or layer_idx >= len(mp.layers):
            self.report({'ERROR'}, "No active layer")
            return {'CANCELLED'}

        layer = mp.layers[layer_idx]

        # Get channel
        ch_idx = self.channel_index
        if ch_idx < 0 or ch_idx >= len(layer.channels):
            self.report({'ERROR'}, "Invalid channel index")
            return {'CANCELLED'}

        channel = layer.channels[ch_idx]
        root_channel = mp.channels[ch_idx] if ch_idx < len(mp.channels) else None

        # Preserve expand_blend_settings state before changes
        saved_expand_blend = getattr(channel, 'expand_blend_settings', False)

        try:
            # Get current override_type
            current_type = getattr(channel, 'override_type', 'LAYER')
            is_image = current_type == 'IMAGE'

            if is_image:
                # Turn off image - for fill layers with VALUE/NORMAL, use OVERRIDE mode
                # so the slider continues to work
                if layer.type == 'COLOR' and root_channel:
                    if root_channel.type in {'NORMAL', 'VALUE'}:
                        # Normal and VALUE use OVERRIDE mode for color picker/slider
                        channel.override_type = 'OVERRIDE'
                    else:
                        channel.override_type = 'LAYER'
                else:
                    channel.override_type = 'LAYER'
                # For Normal channel, keep override enabled for color picker to work
                if root_channel and root_channel.type == 'NORMAL':
                    if hasattr(channel, 'override'):
                        channel.override = True  # Keep enabled for bump color
                action = "Disabled"
            else:
                # Turn on image override
                channel.override_type = 'IMAGE'
                # For Normal channel, also enable override flag
                if root_channel and root_channel.type == 'NORMAL':
                    if hasattr(channel, 'override'):
                        channel.override = True
                action = "Enabled"

            channel_name = root_channel.name if root_channel else f"Channel {ch_idx}"
            self.report({'INFO'}, f"{action} image override for {channel_name}")

            # Request UI refresh
            request_ui_refresh()

            # Restore expand_blend_settings state after changes
            if hasattr(channel, 'expand_blend_settings'):
                channel.expand_blend_settings = saved_expand_blend

            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to toggle image override: {str(e)}")
            return {'CANCELLED'}


class CHANNEL_OT_ActivateOverrideFromLuminance(Operator):
    """Activate override for a VALUE channel and set value from brush luminance"""

    bl_idname = "channel.activate_override_from_luminance"
    bl_label = "Activate Override from Luminance"
    bl_description = "Activate custom override and set value to current brush luminance"
    bl_options = {"REGISTER", "UNDO"}

    channel_index: IntProperty(
        name="Channel Index",
        default=-1,
        options={'HIDDEN'}
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def execute(self, context):
        """Activate override and set value from brush luminance.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp

        # Get active layer
        layer_idx = mp.active_layer_index
        if layer_idx < 0 or layer_idx >= len(mp.layers):
            self.report({'ERROR'}, "No active layer")
            return {'CANCELLED'}

        layer = mp.layers[layer_idx]

        # Get channel
        ch_idx = self.channel_index
        if ch_idx < 0 or ch_idx >= len(layer.channels):
            self.report({'ERROR'}, "Invalid channel index")
            return {'CANCELLED'}

        channel = layer.channels[ch_idx]
        root_channel = mp.channels[ch_idx] if ch_idx < len(mp.channels) else None

        try:
            # Get luminance from brush color
            luminance = self._get_brush_luminance(context)

            # Activate override
            channel.override_type = 'OVERRIDE'

            # Set override value to luminance
            if hasattr(channel, 'override_value'):
                channel.override_value = luminance

            channel_name = root_channel.name if root_channel else f"Channel {ch_idx}"
            self.report({'INFO'}, f"Activated override for {channel_name} with value {luminance:.2f}")

            # Request UI refresh
            request_ui_refresh()

            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to activate override: {str(e)}")
            return {'CANCELLED'}

    def _get_brush_luminance(self, context):
        """Calculate luminance from current brush color.

        Args:
            context: Blender context.

        Returns:
            float: Luminance value (0.0 to 1.0).
        """
        if not context.tool_settings or not context.tool_settings.image_paint:
            return 1.0

        settings = context.tool_settings.image_paint
        brush = settings.brush
        if not brush:
            return 1.0

        ups = settings.unified_paint_settings
        color = ups.color if ups.use_unified_color else brush.color

        # Standard luminance formula (ITU-R BT.709)
        luminance = 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]
        return max(0.0, min(1.0, luminance))


class CHANNEL_OT_ToggleNormalImageOverride(Operator):
    """Toggle image override for Normal channel's normal map source (override_1)"""

    bl_idname = "channel.toggle_normal_image_override"
    bl_label = "Toggle Normal Map Image Override"
    bl_description = "Toggle between default color and image override for normal map source"
    bl_options = {"REGISTER", "UNDO"}

    channel_index: IntProperty(
        name="Channel Index",
        default=-1,
        options={'HIDDEN'}
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def execute(self, context):
        """Toggle the normal map image override state (override_1).

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp

        # Get active layer
        layer_idx = mp.active_layer_index
        if layer_idx < 0 or layer_idx >= len(mp.layers):
            self.report({'ERROR'}, "No active layer")
            return {'CANCELLED'}

        layer = mp.layers[layer_idx]

        # Get channel
        ch_idx = self.channel_index
        if ch_idx < 0 or ch_idx >= len(layer.channels):
            self.report({'ERROR'}, "Invalid channel index")
            return {'CANCELLED'}

        channel = layer.channels[ch_idx]
        root_channel = mp.channels[ch_idx] if ch_idx < len(mp.channels) else None

        # Verify this is a Normal channel
        if not root_channel or root_channel.type != 'NORMAL':
            self.report({'ERROR'}, "This operator is only for Normal channels")
            return {'CANCELLED'}

        # Preserve expand_blend_settings state before changes
        saved_expand_blend = getattr(channel, 'expand_blend_settings', False)

        try:
            # Get current override_1_type (normal map source type)
            current_type = getattr(channel, 'override_1_type', 'DEFAULT')
            is_image = current_type == 'IMAGE'

            if is_image:
                # Turn off image - revert to DEFAULT mode
                channel.override_1_type = 'DEFAULT'
                if hasattr(channel, 'override_1'):
                    channel.override_1 = False
                action = "Disabled"
            else:
                # Turn on image override
                channel.override_1_type = 'IMAGE'
                if hasattr(channel, 'override_1'):
                    channel.override_1 = True
                action = "Enabled"

            self.report({'INFO'}, f"{action} normal map image override")

            # Request UI refresh
            request_ui_refresh()

            # Restore expand_blend_settings state after changes
            if hasattr(channel, 'expand_blend_settings'):
                channel.expand_blend_settings = saved_expand_blend

            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to toggle normal map image override: {str(e)}")
            return {'CANCELLED'}


# Classes for registration
classes = (
    LAYERS_OT_ToggleLayerChannel,
    LAYERS_OT_DisableLayerChannel,
    LAYERS_OT_EnableLayerChannel,
    CHANNEL_OT_ToggleCustomOverride,
    CHANNEL_OT_ToggleImageOverride,
    CHANNEL_OT_ToggleNormalImageOverride,
    CHANNEL_OT_ActivateOverrideFromLuminance,
)
