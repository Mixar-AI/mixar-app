# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Remove channel operator for Mixar

Properly removes channels from the node graph, including:
- Layer channel nodes (source, blend, intensity, etc.)
- Root channel nodes (start_linear, end_linear, etc.)
- Modifier nodes
- Then reconnects remaining channels
"""

from bpy.props import IntProperty
from bpy.types import Operator

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.node.node_active_utils import get_active_mpaint_node
from ...core.node.node_tree_utils import remove_node
from ...core.node.check_layer_io_nodes import check_all_layer_channel_io_and_nodes
from ...core.subtree.get_subtree import get_tree
from ...core.io.mp.mp_connections import reconnect_mp_nodes
from ...core.layer.channel_io import check_all_channel_ios
from ...core.modifier.modifier_nodes import delete_modifier_nodes
from ..utils.ui_refresh import request_ui_refresh


def _remove_layer_channel_nodes(tree, ch, root_ch):
    """Remove all nodes for a layer channel.

    Args:
        tree: The layer's node tree.
        ch: The layer channel (YLayerChannel).
        root_ch: The root channel (MPaintChannel).
    """
    # Source nodes
    remove_node(tree, ch, 'source')
    remove_node(tree, ch, 'source_1')

    # Blending nodes
    remove_node(tree, ch, 'blend')
    remove_node(tree, ch, 'intensity')
    remove_node(tree, ch, 'extra_alpha')
    remove_node(tree, ch, 'disp_blend')

    # Linear processing
    remove_node(tree, ch, 'linear')
    remove_node(tree, ch, 'linear_1')

    # Displacement nodes
    remove_node(tree, ch, 'flip_y')
    remove_node(tree, ch, 'separate_color_channels')

    # Alpha nodes
    remove_node(tree, ch, 'group_alpha_multiply')

    # Normal processing
    remove_node(tree, ch, 'normal_process')
    remove_node(tree, ch, 'normal_flip')

    # Height processing
    remove_node(tree, ch, 'height_proc')
    remove_node(tree, ch, 'height_blend')
    remove_node(tree, ch, 'normal_proc')

    # Unpacking nodes
    remove_node(tree, ch, 'height_group_unpack')
    remove_node(tree, ch, 'height_alpha_group_unpack')

    # Cache nodes
    remove_node(tree, ch, 'cache_ramp')
    remove_node(tree, ch, 'cache_falloff_curve')
    remove_node(tree, ch, 'cache_brick')
    remove_node(tree, ch, 'cache_checker')
    remove_node(tree, ch, 'cache_gradient')
    remove_node(tree, ch, 'cache_magic')
    remove_node(tree, ch, 'cache_musgrave')
    remove_node(tree, ch, 'cache_noise')
    remove_node(tree, ch, 'cache_voronoi')
    remove_node(tree, ch, 'cache_wave')
    remove_node(tree, ch, 'cache_image')
    remove_node(tree, ch, 'cache_1_image')
    remove_node(tree, ch, 'cache_vcol')
    remove_node(tree, ch, 'cache_hemi')

    # Modifier nodes
    for mod in ch.modifiers:
        delete_modifier_nodes(tree, mod)


def _remove_root_channel_nodes(tree, channel):
    """Remove root channel nodes from main tree.

    Args:
        tree: The main MPaint node tree.
        channel: The root channel (MPaintChannel).
    """
    # Start/end processing nodes
    remove_node(tree, channel, 'start_linear')
    remove_node(tree, channel, 'end_linear')

    # Normal-specific nodes
    remove_node(tree, channel, 'start_bump_process')
    remove_node(tree, channel, 'start_normal_filter')
    remove_node(tree, channel, 'end_start_bump_overlay')
    remove_node(tree, channel, 'end_normal_engine_filter')
    remove_node(tree, channel, 'end_backface')
    remove_node(tree, channel, 'end_max_height')
    remove_node(tree, channel, 'end_max_height_tweak')

    # Baked nodes
    remove_node(tree, channel, 'baked')
    remove_node(tree, channel, 'baked_vcol')
    remove_node(tree, channel, 'baked_normal')
    remove_node(tree, channel, 'baked_normal_flip')
    remove_node(tree, channel, 'baked_normal_prep')
    remove_node(tree, channel, 'baked_disp')
    remove_node(tree, channel, 'baked_normal_overlay')

    # Root channel modifiers
    for mod in channel.modifiers:
        delete_modifier_nodes(tree, mod)


class CHANNELS_OT_RemoveChannel(Operator):
    """Remove a channel from the material"""

    bl_idname = "channels.remove_channel"
    bl_label = "Remove Channel"
    bl_description = "Remove the active channel from the material"
    bl_options = {"REGISTER", "UNDO"}

    channel_index: IntProperty(default=-1, options={'HIDDEN'})

    def invoke(self, context, event):
        """Show confirmation dialog before removing channel.

        Displays a confirmation dialog to the user if a valid channel is found.

        Args:
            context: Blender context.
            event: Event that triggered the operator.

        Returns:
            set: Result from confirmation dialog or execute().
        """
        # Get channel info for confirmation
        node = get_active_mpaint_node()
        if node and node.node_tree:
            mp = node.node_tree.mp
            idx = self.channel_index if self.channel_index >= 0 else mp.active_channel_index

            if idx >= 0 and idx < len(mp.channels):
                # Show confirmation dialog with custom draw
                return context.window_manager.invoke_props_dialog(self, width=350)

        return self.execute(context)

    def draw(self, context):
        """Draw the confirmation dialog UI.

        Displays channel name and detailed warning about removal consequences.

        Args:
            context: Blender context.
        """
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        node = get_active_mpaint_node()
        if node and node.node_tree:
            mp = node.node_tree.mp
            idx = self.channel_index if self.channel_index >= 0 else mp.active_channel_index

            if idx >= 0 and idx < len(mp.channels):
                channel = mp.channels[idx]
                num_layers = len(mp.layers)

                main_col = layout.column(align=False)

                # Question
                question_row = main_col.row(align=True)
                question_row.scale_y = 1.3
                question_row.label(text=f"Remove channel '{channel.name}'?", icon='ERROR')

                main_col.separator(factor=0.8)

                # Warning box with detailed info
                warn_box = main_col.box()
                warn_col = warn_box.column(align=True)
                warn_col.scale_y = 1.1

                warn_col.label(text="This action will:", icon='INFO')
                warn_col.separator(factor=0.3)
                warn_col.label(text=f"• Remove '{channel.name}' from all {num_layers} layer(s)")
                warn_col.label(text="• Delete all painted/override data for this channel")
                warn_col.label(text="• Remove all modifiers on this channel")

                main_col.separator(factor=0.5)

                # Additional warning
                alert_row = main_col.row(align=True)
                alert_row.alert = True
                alert_row.label(text="Channel data cannot be recovered after removal.", icon='CANCEL')

    def execute(self, context):
        """Remove the specified channel from the material.

        Properly removes:
        1. Channel nodes from all layer trees
        2. Root channel nodes from main tree
        3. Channel properties from collections
        4. Reconnects remaining channels

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

        # Get channel index
        idx = self.channel_index if self.channel_index >= 0 else mp.active_channel_index

        if idx < 0 or idx >= len(mp.channels):
            self.report({'ERROR'}, "Invalid channel index")
            return {'CANCELLED'}

        root_ch = mp.channels[idx]
        channel_name = root_ch.name

        try:
            # 1. Remove channel nodes from all layers
            for layer in mp.layers:
                if idx < len(layer.channels):
                    layer_ch = layer.channels[idx]
                    layer_tree = get_tree(layer)
                    if layer_tree:
                        _remove_layer_channel_nodes(layer_tree, layer_ch, root_ch)
                    layer.channels.remove(idx)
                    # Rebuild layer IOs with correct indices after channel removal
                    check_all_layer_channel_io_and_nodes(layer, layer_tree)

            # 2. Remove root channel nodes from main tree
            _remove_root_channel_nodes(tree, root_ch)

            # 3. Remove the root channel property
            mp.channels.remove(idx)

            # 4. Adjust active index
            if mp.active_channel_index >= len(mp.channels):
                mp.active_channel_index = max(0, len(mp.channels) - 1)

            # 5. Rebuild channel IOs on group node (removes stale outputs)
            check_all_channel_ios(mp, reconnect=False)

            # 6. Reconnect remaining channels to BSDF
            reconnect_mp_nodes(tree)

            self.report({'INFO'}, f"Removed channel '{channel_name}'")

            # Request UI refresh
            request_ui_refresh()

            return {'FINISHED'}

        except Exception as e:
            self.report({'ERROR'}, f"Failed to remove channel: {str(e)}")
            logger.error("Failed to remove channel: %s", e, exc_info=True)
            return {'CANCELLED'}


# Classes for registration
classes = (
    CHANNELS_OT_RemoveChannel,
)
