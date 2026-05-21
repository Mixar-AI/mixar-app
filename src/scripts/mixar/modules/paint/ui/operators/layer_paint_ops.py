# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Paint layer operators for Mixar layers system"""

import os
import time
import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...utils.statics import blend_type_items
from ...core.element.update_image import update_image_editor_image
from ...core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_mp_nodes
from ...core.layer.check_channels import check_start_end_root_ch_nodes
from ...core.layer.create_channels import create_new_mp_channel
from ...core.layer.layer_utils import get_uv_layers
from ...core.material.get_materials import get_all_objects_with_same_materials
from ...core.node.create_nodes import create_new_group_tree
from ...core.node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import (
    get_active_material,
    get_active_object,
    get_unique_name,
    get_user_preferences,
    is_bl_newer_than,
)
from ...utils.constants import (
    TEMP_UV,
    image_resolution_items,
    interpolation_type_items,
    normal_blend_items,
    texcoord_type_items,
)
from ..udim.udim_utils import get_tile_numbers, fill_tile, initial_pack_udim


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


from ..utils.ui_refresh import request_ui_refresh
from .layer_paint_ops_helpers import (
    draw_layer_setup_section,
    draw_image_settings_section,
    draw_paint_layer_dialog,
)


class LAYERS_OT_AddPaintLayer(Operator):
    """Add a new paint layer - Complete Mixar Paint implementation"""

    bl_idname = "layers.add_paint_layer"
    bl_label = "Add Paint Layer"
    bl_description = "Add a new paint layer with full UDIM/Atlas/HDR support"
    bl_options = {"REGISTER", "UNDO"}

    # Layer name
    name: StringProperty(default='')

    # Image properties
    width: IntProperty(name='Width', default=1024, min=1, max=16384)
    height: IntProperty(name='Height', default=1024, min=1, max=16384)
    hdr: BoolProperty(name='32 bit Float', default=False)

    interpolation: EnumProperty(
        name='Image Interpolation Type',
        description='Image interpolation type',
        items=interpolation_type_items,
        default='Linear'
    )

    texcoord_type: EnumProperty(
        name='Layer Coordinate Type',
        description='Layer Coordinate Type',
        items=texcoord_type_items,
        default='UV'
    )

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

    uv_map: StringProperty(default='')

    normal_map_type: EnumProperty(
        name='Normal Map Type',
        description='Normal map type of this layer',
        items=get_normal_map_type_items
    )

    use_udim: BoolProperty(
        name='Use UDIM Tiles',
        description='Use UDIM Tiles',
        default=False
    )

    use_image_atlas: BoolProperty(
        name='Use Image Atlas',
        description='Use Image Atlas',
        default=False
    )

    uv_map_coll: CollectionProperty(type=bpy.types.PropertyGroup)

    image_resolution: EnumProperty(
        name='Image Resolution',
        items=image_resolution_items,
        default='1024'
    )

    use_custom_resolution: BoolProperty(
        name='Custom Resolution',
        description='Use custom Resolution to adjust the width and height individually',
        default=False
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
        """Initialize paint layer properties and show dialog.

        Args:
            context: Blender context.
            event: Event that triggered the operator.

        Returns:
            set: Result from dialog or execute().
        """
        # Delayed import to avoid circular dependency
        from ..layer.helpers.layer_enum_helpers import DEFAULT_NEW_IMG_SUFFIX

        mpup = get_user_preferences()
        node = get_active_mpaint_node()
        mp = self.mp = node.node_tree.mp
        obj = get_active_object()
        mat = get_active_material()

        # Generate unique name
        name = mat.name + DEFAULT_NEW_IMG_SUFFIX
        self.name = get_unique_name(name, bpy.data.images)
        self.name = get_unique_name(self.name, mp.layers)

        # Use user preference default image size
        if mpup.default_image_resolution == 'CUSTOM':
            self.use_custom_resolution = True
            self.width = self.height = mpup.default_new_image_size
        elif mpup.default_image_resolution != 'DEFAULT':
            self.image_resolution = mpup.default_image_resolution

        # Default normal map type
        self.normal_map_type = 'BUMP_MAP'
        self.blend_type = 'MIX'

        # Get default UV map
        if obj and obj.type == 'MESH':
            uv_layers = get_uv_layers(obj)
            if uv_layers:
                self.uv_map = uv_layers[0].name

            # UV Map collections update
            self.uv_map_coll.clear()
            for uv in uv_layers:
                if not uv.name.startswith(TEMP_UV):
                    self.uv_map_coll.add().name = uv.name

        # Skip dialog if preference is set
        if mpup.skip_property_popups and not event.shift:
            return self.execute(context)

        return context.window_manager.invoke_props_dialog(self, width=320)

    def check(self, context):
        """Update properties when dialog values change.

        Syncs width/height with resolution enum and enforces image atlas size limits.

        Args:
            context: Blender context.

        Returns:
            bool: True to trigger redraw.
        """
        # Sync width/height with resolution enum
        if not self.use_custom_resolution:
            self.width = int(self.image_resolution)
            self.height = int(self.image_resolution)

        # Image atlas size limits
        if self.use_image_atlas:
            mpup = get_user_preferences()
            if self.hdr:
                max_size = mpup.hdr_image_atlas_size
            else:
                max_size = mpup.image_atlas_size
            if self.width > max_size:
                self.width = max_size
            if self.height > max_size:
                self.height = max_size

        return True

    def draw(self, context):
        """Draw the paint layer creation dialog UI.

        Args:
            context: Blender context.
        """
        draw_paint_layer_dialog(context, self.layout, self)

    def execute(self, context):
        """Create a new paint layer with image texture.

        Creates image, layer, and sets up texture paint mode.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        # Delayed import to avoid circular dependency
        from ..layer.helpers.layer_create_helpers import add_new_layer

        import time
        T = time.time()

        node = get_active_mpaint_node()
        if not node:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        group_tree = node.node_tree
        mp = group_tree.mp
        obj = get_active_object()
        mat = get_active_material()
        mpup = get_user_preferences()

        # Validate unique name
        if self.name in [img.name for img in bpy.data.images]:
            self.report({'ERROR'}, f"Image '{self.name}' already exists!")
            return {'CANCELLED'}

        if self.name in [layer.name for layer in mp.layers]:
            self.report({'ERROR'}, f"Layer '{self.name}' already exists!")
            return {'CANCELLED'}

        # Get channel index
        try:
            channel_idx = int(self.channel_idx)
        except:
            channel_idx = 0

        # Create the image
        img = None
        segment = None
        alpha = True
        color = (0, 0, 0, 0)  # Transparent black

        if self.use_udim:
            # Get all objects with same material
            objs = get_all_objects_with_same_materials(mat)
            # Get tile numbers from UV map
            tilenums = get_tile_numbers(objs, self.uv_map)

            # Create UDIM image
            img = bpy.data.images.new(
                name=self.name,
                width=self.width,
                height=self.height,
                alpha=alpha,
                float_buffer=self.hdr,
                tiled=True  # CRITICAL for UDIM
            )

            # Fill tiles
            for tilenum in tilenums:
                fill_tile(img, tilenum, color, self.width, self.height)

            initial_pack_udim(img, color)

        elif self.use_image_atlas:
            # Image atlas support (placeholder - needs full implementation)
            self.report({'WARNING'}, "Image Atlas not fully implemented yet")
            img = bpy.data.images.new(
                name=self.name,
                width=self.width,
                height=self.height,
                alpha=alpha,
                float_buffer=self.hdr
            )
            img.generated_type = 'BLANK'
            img.generated_color = color

        else:
            # Regular image
            img = bpy.data.images.new(
                name=self.name,
                width=self.width,
                height=self.height,
                alpha=alpha,
                float_buffer=self.hdr
            )
            img.generated_type = 'BLANK'
            img.generated_color = color
            if hasattr(img, 'use_alpha'):
                img.use_alpha = True

        # Set alpha mode for HDR
        if img.is_float and is_bl_newer_than(2, 80):
            img.alpha_mode = 'PREMUL'

        # Update image editor
        update_image_editor_image(context, img)

        # Halt updates during layer creation (preserve original value)
        ori_halt_update = mp.halt_update
        mp.halt_update = True

        try:
            # Create IMAGE paint layer
            layer = add_new_layer(
                group_tree=group_tree,
                layer_name=self.name,
                layer_type='IMAGE',
                channel_idx=channel_idx,
                blend_type=self.blend_type,
                normal_blend_type=self.normal_blend_type,
                normal_map_type=self.normal_map_type,
                texcoord_type=self.texcoord_type,
                uv_name=self.uv_map,
                image=img,
                segment=segment,
                interpolation=self.interpolation,
            )

            # Set as active layer
            mp.active_layer_index = len(mp.layers) - 1

            # Enable all created channels in the new layer
            # Channels are disabled by default, but should be enabled for usability
            for i in range(len(mp.channels)):
                if i < len(layer.channels):
                    layer.channels[i].enable = True

        finally:
            mp.halt_update = ori_halt_update

        # CRITICAL: Reconnect and rearrange nodes
        reconnect_mp_nodes(group_tree)
        rearrange_mp_nodes(group_tree)

        # Set up texture paint mode with the created image
        if obj and obj.type == 'MESH':
            # Switch to texture paint mode if not already
            if context.mode != 'PAINT_TEXTURE':
                try:
                    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
                except RuntimeError as e:
                    logger.warning(f"Could not switch to texture paint mode: {e}")

            # Set the created image as the active painting target
            if hasattr(context, 'tool_settings') and hasattr(context.tool_settings, 'image_paint'):
                context.tool_settings.image_paint.canvas = img
                # Also set it in the paint slots if available
                if hasattr(obj.data, 'paint_active_index') and mat.paint_active_slot < len(mat.texture_paint_images):
                    mat.texture_paint_images[mat.paint_active_slot] = img

        # Switch to Material Preview if viewport is in Wireframe or Solid mode
        # This ensures the user can see the painted texture
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                if area.spaces[0].shading.type in {'WIREFRAME', 'SOLID'}:
                    area.spaces[0].shading.type = "MATERIAL"
                break

        # Request UI refresh
        request_ui_refresh()

        # Performance logging
        logger.info(f'Layer {layer.name} created in {(time.time() - T) * 1000:.2f} ms!')

        return {"FINISHED"}


# Classes for registration
classes = (
    LAYERS_OT_AddPaintLayer,
)

# Re-exports for backward compatibility
# These functions are now defined in layer_paint_ops_helpers.py
__all__ = [
    'LAYERS_OT_AddPaintLayer',
    'classes',
    # Re-exported helper functions
    'draw_layer_setup_section',
    'draw_image_settings_section',
    'draw_paint_layer_dialog',
]
