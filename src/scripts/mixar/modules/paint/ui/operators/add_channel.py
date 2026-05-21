# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Add channel operators for Mixar"""

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.layer.create_channels import create_new_mp_channel
from ...core.node.node_utils import get_active_mpaint_node
from ..utils.ui_refresh import request_ui_refresh
from ...core.io.connections.layer_connections import reconnect_mp_nodes
from ...core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ...core.layer.channel_io import check_all_channel_ios
from ...core.io.utils.bsdf_connections import (
    connect_channel_to_bsdf,
    setup_bsdf_companion_socket,
    needs_strength_setting,
)
from ...utils.blender_commons import get_active_material
from ...core.layer_handlers import get_handler


class CHANNELS_OT_AddChannel(Operator):
    """Add a new channel to the material"""

    bl_idname = "channels.add_channel"
    bl_label = "Add Channel"
    bl_description = "Add a new channel to the material"
    bl_options = {"REGISTER", "UNDO"}

    channel_type: EnumProperty(
        name="Channel Type",
        items=[
            ("VALUE", "Value", "Single value channel (Metallic, Roughness, etc)"),
            ("RGB", "RGB", "Color channel"),
            ("NORMAL", "Normal", "Normal map channel"),
        ],
        default="VALUE",
    )

    channel_name: bpy.props.StringProperty(
        name="Channel Name",
        default="New Channel",
    )

    non_color: bpy.props.BoolProperty(
        name="Non-Color Data",
        description="Treat as non-color data (linear colorspace)",
        default=True,
    )

    enable: bpy.props.BoolProperty(
        name="Enable for All Layers",
        description="Enable this channel for all existing layers",
        default=False,
    )

    connect_to_bsdf: bpy.props.BoolProperty(
        name="Connect to BSDF",
        description="Automatically connect channel to Principled BSDF socket if matching",
        default=True,
    )

    set_strength_to_one: bpy.props.BoolProperty(
        name="Set Strength to 1",
        description="Set companion socket (Emission Strength/Subsurface Weight) to 1.0 in Blender 4.0+",
        default=True,
    )

    def invoke(self, context, event):
        """Initialize operator properties and show dialog.

        Sets default channel name based on selected type and displays the
        property dialog to the user.

        Args:
            context: Blender context.
            event: Event that triggered the operator.

        Returns:
            set: Operator return status {'RUNNING_MODAL'}.
        """
        # Set default name based on type
        if self.channel_type == "VALUE":
            self.channel_name = "Value"
        elif self.channel_type == "RGB":
            self.channel_name = "Color"
        elif self.channel_type == "NORMAL":
            self.channel_name = "Normal"

        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        """Draw the operator dialog UI.

        Creates a custom UI layout for channel creation with channel setup
        options including type, name, color space, and layer enable settings.

        Args:
            context: Blender context.
        """
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=False)

        # ========== CHANNEL SETUP SECTION ==========
        setup_box = main_col.box()
        setup_col = setup_box.column(align=False)

        # Header
        header_row = setup_col.row(align=True)
        header_row.scale_y = 1.4
        header_row.label(text="Channel Setup", icon="NODE")

        setup_col.separator(factor=1.2)

        # Channel type
        type_row = setup_col.row(align=True)
        type_row.scale_y = 1.4
        type_split = type_row.split(factor=0.25, align=True)
        label_col = type_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Type:")
        type_split.prop(self, "channel_type", text="")

        setup_col.separator(factor=0.4)

        # Channel name
        name_row = setup_col.row(align=True)
        name_row.scale_y = 1.4
        name_split = name_row.split(factor=0.25, align=True)
        label_col = name_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Name:")
        name_split.prop(self, "channel_name", text="")

        setup_col.separator(factor=0.4)

        # Non-color data checkbox (for RGB and VALUE types)
        if self.channel_type in {"RGB", "VALUE"}:
            noncolor_row = setup_col.row(align=True)
            noncolor_row.scale_y = 1.2
            noncolor_split = noncolor_row.split(factor=0.25, align=True)
            noncolor_split.label(text="")
            checkbox_col = noncolor_split.column(align=True)
            checkbox_col.prop(self, "non_color")

            setup_col.separator(factor=0.4)

        # Enable for all layers checkbox
        enable_row = setup_col.row(align=True)
        enable_row.scale_y = 1.2
        enable_split = enable_row.split(factor=0.25, align=True)
        enable_split.label(text="")
        checkbox_col = enable_split.column(align=True)
        checkbox_col.prop(self, "enable")

        setup_col.separator(factor=0.4)

        # Connect to BSDF checkbox
        bsdf_row = setup_col.row(align=True)
        bsdf_row.scale_y = 1.2
        bsdf_split = bsdf_row.split(factor=0.25, align=True)
        bsdf_split.label(text="")
        checkbox_col = bsdf_split.column(align=True)
        checkbox_col.prop(self, "connect_to_bsdf")

        # Set Strength to 1 checkbox (only for Emission/Subsurface in Blender 4.0+)
        if needs_strength_setting(self.channel_name):
            setup_col.separator(factor=0.4)
            strength_row = setup_col.row(align=True)
            strength_row.scale_y = 1.2
            strength_split = strength_row.split(factor=0.25, align=True)
            strength_split.label(text="")
            checkbox_col = strength_split.column(align=True)
            checkbox_col.prop(self, "set_strength_to_one")

        setup_col.separator(factor=0.8)

    def execute(self, context):
        """Create a new channel in the material.

        Creates a new channel with specified type and properties, updates
        the active channel index, and requests UI refresh.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        tree = node.node_tree
        mp = tree.mp

        # Create new channel
        try:
            # Halt reconnect during channel creation
            mp.halt_reconnect = True

            channel = create_new_mp_channel(
                tree,
                self.channel_name,
                self.channel_type,
                non_color=self.non_color,
                enable=self.enable
            )

            # Set active channel index
            ch_index = len(mp.channels) - 1
            mp.active_channel_index = ch_index

            mp.halt_reconnect = False

            # CRITICAL: Create channel I/O sockets on the group node first
            # This must happen BEFORE reconnect_mp_nodes() which expects them to exist
            # Pass mp (property group) and reconnect=False since we call reconnect_mp_nodes manually
            check_all_channel_ios(mp, reconnect=False)

            # Reconnect and rearrange to set up all nodes properly
            reconnect_mp_nodes(tree)
            rearrange_mp_nodes(tree)

            # Apply handler defaults to existing layers for the new channel
            _apply_handler_defaults_to_layers(mp, channel, ch_index)

            # Connect channel to BSDF if enabled
            if self.connect_to_bsdf:
                mat = get_active_material()
                if mat:
                    target_socket = connect_channel_to_bsdf(mat, node, channel)
                    # Set companion socket (e.g., Emission Strength, Sheen Weight) to 1.0
                    if target_socket and self.set_strength_to_one:
                        setup_bsdf_companion_socket(mat, target_socket)

            self.report({'INFO'}, f"Added channel '{channel.name}'")

            # Request UI refresh
            request_ui_refresh()

            return {'FINISHED'}

        except Exception as e:
            mp.halt_reconnect = False
            self.report({'ERROR'}, f"Failed to add channel: {str(e)}")
            logger.error("Failed to add channel: %s", e, exc_info=True)
            return {'CANCELLED'}


class CHANNELS_OT_AddChannelQuick(Operator):
    """Quickly add a preconfigured channel with one click"""

    bl_idname = "channels.add_channel_quick"
    bl_label = "Add Channel"
    bl_description = "Add a preconfigured channel"
    bl_options = {"REGISTER", "UNDO"}

    channel_name: bpy.props.StringProperty(name="Channel Name", default="")
    channel_type: EnumProperty(
        name="Channel Type",
        items=[
            ("VALUE", "Value", "Single value channel"),
            ("RGB", "RGB", "Color channel"),
            ("NORMAL", "Normal", "Normal map channel"),
        ],
        default="VALUE",
    )
    non_color: bpy.props.BoolProperty(name="Non-Color Data", default=True)
    enable: bpy.props.BoolProperty(name="Enable for All Layers", default=False)
    connect_to_bsdf: bpy.props.BoolProperty(name="Connect to BSDF", default=True)
    set_strength_to_one: bpy.props.BoolProperty(name="Set Strength to 1", default=True)

    def execute(self, context):
        """Create a new channel with preconfigured settings.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        tree = node.node_tree
        mp = tree.mp

        # Check if channel already exists
        for ch in mp.channels:
            if ch.name == self.channel_name:
                self.report({'WARNING'}, f"Channel '{self.channel_name}' already exists")
                return {'CANCELLED'}

        # Create new channel
        try:
            # Halt reconnect during channel creation
            mp.halt_reconnect = True

            channel = create_new_mp_channel(
                tree,
                self.channel_name,
                self.channel_type,
                non_color=self.non_color,
                enable=self.enable
            )

            # Set active channel index
            ch_index = len(mp.channels) - 1
            mp.active_channel_index = ch_index

            mp.halt_reconnect = False

            # CRITICAL: Create channel I/O sockets on the group node first
            # This must happen BEFORE reconnect_mp_nodes() which expects them to exist
            # Pass mp (property group) and reconnect=False since we call reconnect_mp_nodes manually
            check_all_channel_ios(mp, reconnect=False)

            # Reconnect and rearrange to set up all nodes properly
            reconnect_mp_nodes(tree)
            rearrange_mp_nodes(tree)

            # Apply handler defaults to existing layers for the new channel
            _apply_handler_defaults_to_layers(mp, channel, ch_index)

            # Connect channel to BSDF if enabled
            if self.connect_to_bsdf:
                mat = get_active_material()
                if mat:
                    target_socket = connect_channel_to_bsdf(mat, node, channel)
                    # Set companion socket (e.g., Emission Strength, Sheen Weight) to 1.0
                    if target_socket and self.set_strength_to_one:
                        setup_bsdf_companion_socket(mat, target_socket)

            self.report({'INFO'}, f"Added channel '{channel.name}'")

            # Request UI refresh
            request_ui_refresh()

            return {'FINISHED'}

        except Exception as e:
            mp.halt_reconnect = False
            self.report({'ERROR'}, f"Failed to add channel: {str(e)}")
            logger.error("Failed to add channel: %s", e, exc_info=True)
            return {'CANCELLED'}


def _apply_handler_defaults_to_layers(mp, root_ch, ch_index):
    """Apply handler-specific defaults to all existing layers for a new channel.

    When a new channel is added, existing layers get a new YLayerChannel entry
    but with generic defaults. This applies handler-specific defaults (e.g.,
    override_type, override_value) so channels behave correctly without manual setup.

    Args:
        mp: Root MPaint property group.
        root_ch: The newly created root channel.
        ch_index: Index of the new channel in mp.channels.
    """
    for layer in mp.layers:
        if ch_index >= len(layer.channels):
            continue
        layer_ch = layer.channels[ch_index]
        handler = get_handler(layer.type)
        if handler:
            handler.setup_channel_defaults(layer_ch, root_ch)


# Classes for registration
classes = (
    CHANNELS_OT_AddChannel,
    CHANNELS_OT_AddChannelQuick,
)
