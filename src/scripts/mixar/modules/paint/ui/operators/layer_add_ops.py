# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Basic layer addition operators for Mixar layers system"""

import time
import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatVectorProperty,
    StringProperty,
)
from bpy.types import Operator

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...utils.statics import blend_type_items
from ...core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_mp_nodes
from ...core.io.utils.bsdf_connections import commit_mp_material
from ...core.node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_unique_name,
    get_user_preferences,
)
from ...utils.constants import normal_blend_items
from ..utils.ui_refresh import request_ui_refresh


# -------------------------------------------------------------------------
# Wrapper functions with delayed imports to avoid circular imports
# -------------------------------------------------------------------------
def channel_items(self, context):
    """Wrapper for channel_items with delayed import."""
    from ..layer.helpers.layer_enum_helpers import channel_items as _impl

    return _impl(self, context)


def get_normal_map_type_items(self, context):
    """Wrapper for get_normal_map_type_items with delayed import."""
    from ..layer.helpers.layer_enum_helpers import get_normal_map_type_items as _impl

    return _impl(self, context)


class LAYERS_OT_AddFillLayer(Operator):
    """Add a new fill layer - Complete Mixar Paint implementation"""

    bl_idname = "layers.add_fill_layer"
    bl_label = "Add Fill Layer"
    bl_description = "Add a new fill layer with color and optional mask"
    bl_options = {"REGISTER", "UNDO"}

    # Layer name
    name: StringProperty(default='')

    # Fill color
    solid_color: FloatVectorProperty(
        name='Fill Color',
        size=3,
        subtype='COLOR',
        default=(0.8, 0.8, 0.8),
        min=0.0,
        max=1.0
    )

    # Channel and blend settings
    channel_idx: EnumProperty(
        name='Channel',
        description='Channel of new layer',
        items=channel_items,
    )

    blend_type: EnumProperty(
        name='Blend',
        description='Blend type',
        items=blend_type_items,
    )

    normal_blend_type: EnumProperty(
        name='Normal Blend Type',
        items=normal_blend_items,
        default='MIX'
    )

    normal_map_type: EnumProperty(
        name='Normal Map Type',
        description='Normal map type of this layer',
        items=get_normal_map_type_items
    )

    # Mask options
    add_mask: BoolProperty(
        name='Add Mask',
        description='Add mask to new layer',
        default=False
    )

    mask_type: EnumProperty(
        name='Mask Type',
        description='Mask type',
        items=(
            ('IMAGE', 'Image', '', 'IMAGE_DATA', 0),
            ('VCOL', 'Vertex Color', '', 'GROUP_VCOL', 1),
            ('COLOR_ID', 'Color ID', '', 'COLOR', 2),
            ('EDGE_DETECT', 'Edge Detect', '', 'MESH_CUBE', 3)
        ),
        default='IMAGE'
    )

    mask_color: EnumProperty(
        name='Mask Color',
        description='Mask Color',
        items=(
            ('WHITE', 'White (Full Opacity)', ''),
            ('BLACK', 'Black (Full Transparency)', ''),
        ),
        default='BLACK'
    )

    @classmethod
    def poll(cls, context):
        """Check if operator can be executed.

        Args:
            context: Blender context.

        Returns:
            bool: True if active mpaint node exists, False otherwise.
        """
        return get_active_mpaint_node()

    def invoke(self, context, event):
        """Initialize fill layer properties and show dialog.

        Args:
            context: Blender context.
            event: Event that triggered the operator.

        Returns:
            set: Result from dialog or execute().
        """
        mpup = get_user_preferences()
        node = get_active_mpaint_node()
        mp = self.mp = node.node_tree.mp
        mat = get_active_material()

        # Generate unique name
        name = "Fill Layer"
        self.name = get_unique_name(name, mp.layers)

        # Default settings
        self.normal_map_type = 'BUMP_MAP'
        self.blend_type = 'MIX'
        self.mask_color = 'BLACK'  # Black mask by default for COLOR layers

        # Skip dialog if preference is set
        if mpup.skip_property_popups and not event.shift:
            return self.execute(context)

        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        """Draw the fill layer creation dialog UI.

        Args:
            context: Blender context.
        """
        node = get_active_mpaint_node()
        mp = node.node_tree.mp

        if len(mp.channels) == 0:
            self.layout.label(text='No channel found!', icon='ERROR')
            return

        try:
            channel_idx = int(self.channel_idx)
            if channel_idx != -1:
                channel = mp.channels[channel_idx]
            else:
                channel = None
        except:
            channel = None

        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        main_col = layout.column(align=False)

        # ========== LAYER SETUP SECTION ==========
        setup_box = main_col.box()
        setup_col = setup_box.column(align=False)

        # Header
        header_row = setup_col.row(align=True)
        header_row.scale_y = 1.4
        header_row.label(text="Fill Layer Setup", icon="NODE_TEXTURE")

        setup_col.separator(factor=1.2)

        # Name
        name_row = setup_col.row(align=True)
        name_row.scale_y = 1.4
        name_split = name_row.split(factor=0.25, align=True)
        label_col = name_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Name:")
        name_split.prop(self, 'name', text='')

        setup_col.separator(factor=0.4)

        # Channel
        channel_row = setup_col.row(align=True)
        channel_row.scale_y = 1.4
        channel_split = channel_row.split(factor=0.25, align=True)
        label_col = channel_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Channel:")
        channel_split.prop(self, 'channel_idx', text='')

        setup_col.separator(factor=0.4)

        # Normal map type (if applicable)
        if channel and channel.type == 'NORMAL':
            type_row = setup_col.row(align=True)
            type_row.scale_y = 1.4
            type_split = type_row.split(factor=0.25, align=True)
            label_col = type_split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Type:")
            type_split.prop(self, 'normal_map_type', text='')
            setup_col.separator(factor=0.4)

        # Color
        color_row = setup_col.row(align=True)
        color_row.scale_y = 1.4
        color_split = color_row.split(factor=0.25, align=True)
        label_col = color_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Color:")
        color_split.prop(self, 'solid_color', text='')

        setup_col.separator(factor=0.4)

        # Blend type
        blend_row = setup_col.row(align=True)
        blend_row.scale_y = 1.4
        blend_split = blend_row.split(factor=0.25, align=True)
        label_col = blend_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Blend:")
        blend_split.prop(self, 'blend_type', text='')

        setup_col.separator(factor=0.4)

        # Normal blend (if applicable)
        if channel and channel.type == 'NORMAL':
            normal_blend_row = setup_col.row(align=True)
            normal_blend_row.scale_y = 1.4
            normal_blend_split = normal_blend_row.split(factor=0.25, align=True)
            label_col = normal_blend_split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Normal Blend:")
            normal_blend_split.prop(self, 'normal_blend_type', text='')
            setup_col.separator(factor=0.4)

        setup_col.separator(factor=0.8)

        main_col.separator(factor=0.8)

        # ========== MASK OPTIONS SECTION ==========
        mask_box = main_col.box()
        mask_col = mask_box.column(align=False)

        # Header
        mask_header = mask_col.row(align=True)
        mask_header.scale_y = 1.4
        mask_header.label(text="Mask Options", icon="MOD_MASK")

        mask_col.separator(factor=1.2)

        # Add mask checkbox
        add_mask_row = mask_col.row(align=True)
        add_mask_row.scale_y = 1.2
        add_mask_split = add_mask_row.split(factor=0.25, align=True)
        add_mask_split.label(text="")  # Empty indent
        add_mask_col = add_mask_split.column(align=True)
        add_mask_col.prop(self, 'add_mask')

        mask_col.separator(factor=0.4)

        # Mask type and color (if mask enabled)
        if self.add_mask:
            mask_type_row = mask_col.row(align=True)
            mask_type_row.scale_y = 1.4
            mask_type_split = mask_type_row.split(factor=0.25, align=True)
            label_col = mask_type_split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Mask Type:")
            mask_type_split.prop(self, 'mask_type', text='')

            mask_col.separator(factor=0.4)

            mask_color_row = mask_col.row(align=True)
            mask_color_row.scale_y = 1.4
            mask_color_split = mask_color_row.split(factor=0.25, align=True)
            label_col = mask_color_split.column(align=True)
            label_col.alignment = "RIGHT"
            label_col.label(text="Mask Color:")
            mask_color_split.prop(self, 'mask_color', text='')

            mask_col.separator(factor=0.4)

        mask_col.separator(factor=0.8)

    def execute(self, context):
        """Create a new fill layer with specified properties.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        # Delayed import to avoid circular dependency
        from ..layer.helpers.layer_create_helpers import add_new_layer

        T = time.time()

        node = get_active_mpaint_node()
        if not node:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        group_tree = node.node_tree
        mp = group_tree.mp
        obj = get_active_object()
        mat = get_active_material()

        # Validate unique name
        if self.name in [layer.name for layer in mp.layers]:
            self.report({'ERROR'}, f"Layer '{self.name}' already exists!")
            return {'CANCELLED'}

        # Get channel index
        try:
            channel_idx = int(self.channel_idx)
        except:
            channel_idx = 0

        # Halt updates during layer creation
        mp.halt_update = True

        try:
            # Create COLOR fill layer
            layer = add_new_layer(
                group_tree=group_tree,
                layer_name=self.name,
                layer_type='COLOR',
                channel_idx=channel_idx,
                blend_type=self.blend_type,
                normal_blend_type=self.normal_blend_type,
                normal_map_type=self.normal_map_type,
                texcoord_type='UV',
                solid_color=self.solid_color,
                add_mask=self.add_mask,
                mask_type=self.mask_type if self.add_mask else None,
                mask_color=self.mask_color if self.add_mask else 'BLACK',
            )

            # Set as active layer
            mp.active_layer_index = len(mp.layers) - 1

            # Enable channels based on source type
            # For SOLID_COLOR: only enable Color (RGB type) channel
            # For IMAGE/MATERIAL: enable all channels
            for i in range(len(mp.channels)):
                if i < len(layer.channels):
                    root_ch = mp.channels[i]
                    # SOLID_COLOR layers should only affect Color channel by default
                    # Users can manually enable other channels if needed
                    if layer.source_type == 'SOLID_COLOR':
                        layer.channels[i].enable = (root_ch.type == 'RGB')
                    else:
                        layer.channels[i].enable = True

        finally:
            mp.halt_update = False

        # CRITICAL: Reconnect and rearrange nodes
        reconnect_mp_nodes(group_tree)
        rearrange_mp_nodes(group_tree)

        # Request UI refresh
        request_ui_refresh()

        # Flush the depsgraph so a scripted EXEC_DEFAULT add (agent path, no UI
        # event loop) re-evaluates and renders instead of serving a stale shader.
        # relink=False: after create_material the group already drives the BSDF, so
        # repairing the link here would only ever fire when it was deliberately
        # rewired (e.g. a bake/preview) — the (re)build paths own the relink.
        commit_mp_material(node, mat, context, relink=False)

        # Performance logging
        logger.info(f'Layer {layer.name} created in {(time.time() - T) * 1000:.2f} ms!')

        return {"FINISHED"}


class LAYERS_OT_AddLayerGroup(Operator):
    """Add a new layer group"""

    bl_idname = "layers.add_layer_group"
    bl_label = "Add Layer Group"
    bl_description = "Add a new layer group to organize layers"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        """Create a new layer group.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        # Call wm.y_new_layer with type='GROUP'
        # Use INVOKE_DEFAULT to ensure invoke() is called to set the layer name
        try:
            bpy.ops.wm.m_new_layer('INVOKE_DEFAULT', type='GROUP')
        except:
            self.report({'ERROR'}, "Failed to create layer group")
            return {'CANCELLED'}

        request_ui_refresh()
        return {"FINISHED"}


class LAYERS_OT_AddAdvancedLayer(Operator):
    """Add advanced layer types"""

    bl_idname = "layers.add_advanced_layer"
    bl_label = "Add Advanced Layer"
    bl_description = "Add advanced layer type"
    bl_options = {"INTERNAL"}

    layer_type: EnumProperty(
        name="Type",
        items=[
            ('VCOL', 'Vertex Color', 'Vertex color layer'),
            ('HEMI', 'Fake Lighting', 'Hemisphere/fake lighting'),
            ('AO', 'Ambient Occlusion', 'Ambient occlusion layer'),
            ('EDGE_DETECT', 'Edge Detect', 'Edge detection layer'),
        ],
        default='VCOL'
    )

    def execute(self, context):
        """Create a new advanced layer type.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        # Call wm.y_new_layer with the selected advanced type
        # Use INVOKE_DEFAULT to ensure invoke() is called to set the layer name
        try:
            bpy.ops.wm.m_new_layer('INVOKE_DEFAULT', type=self.layer_type)
        except:
            self.report({'ERROR'}, f"Failed to create {self.layer_type} layer")
            return {'CANCELLED'}

        request_ui_refresh()
        return {"FINISHED"}


# Classes for registration
classes = (
    LAYERS_OT_AddFillLayer,
    LAYERS_OT_AddLayerGroup,
    LAYERS_OT_AddAdvancedLayer,
)
