# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel override image operators for Mixar.

This module contains operators for loading images to override individual
layer channels, with intelligent colorspace detection for normal maps.
"""

import os
import re

import bpy
from bpy_extras.io_utils import ImportHelper

from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes
from ....core.node.create_nodes import check_new_node
from ....core.node.node_utils import get_active_mpaint_node
from ....core.subtree.get_subtree import get_tree
from ....utils.blender_commons import get_noncolor_name
from ...other.base_operator import OpenImage
from ...utils.ui_refresh import request_ui_refresh
from .channel_image_utils import get_existing_images, is_normal_map_filename


class MOpenImageToOverrideChannel(bpy.types.Operator, ImportHelper, OpenImage):
    """Open Image to Override Channel"""
    bl_idname = "wm.m_open_image_to_override_layer_channel"
    bl_label = "Open Image to Override Channel"
    bl_description = "Load an image file to override this channel's value"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def invoke(self, context, event):
        # Store channel reference from context
        if hasattr(context, 'parent'):
            self.ch = context.parent
        elif hasattr(context, 'channel'):
            self.ch = context.channel
        else:
            self.report({'ERROR'}, "No channel context found")
            return {'CANCELLED'}
        return self.running_fileselect_modal(context, event)

    def execute(self, context):
        ch = self.ch

        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        loaded_images = self.get_loaded_images()

        if len(loaded_images) == 0 or loaded_images[0] is None:
            self.report({'ERROR'}, "No image selected!")
            return {'CANCELLED'}

        # Check for existing images with same filepath
        images = []
        for new_img in loaded_images:
            old_image_found = False
            for old_img in bpy.data.images:
                if old_img.filepath == new_img.filepath:
                    images.append(old_img)
                    old_image_found = True
                    break
            if not old_image_found:
                images.append(new_img)

        # Remove duplicate loaded images
        for img in loaded_images:
            if img not in images:
                bpy.data.images.remove(img)

        # Get layer and root channel from path
        mp = node.node_tree.mp
        match = re.match(r'mp\.layers\[(\d+)\]\.channels\[(\d+)\]', ch.path_from_id())
        if not match:
            self.report({'ERROR'}, "Could not determine layer/channel from path")
            return {'CANCELLED'}

        layer_idx = int(match.group(1))
        ch_idx = int(match.group(2))

        layer = mp.layers[layer_idx]
        root_ch = mp.channels[ch_idx] if ch_idx < len(mp.channels) else None
        tree = get_tree(layer)

        if not root_ch:
            self.report({'ERROR'}, "Root channel not found")
            return {'CANCELLED'}

        # Preserve expand_blend_settings state before node operations
        # This prevents the UI from collapsing when uploading an image
        saved_expand_blend = getattr(ch, 'expand_blend_settings', False)

        image = images[0] if images else None

        if not image:
            self.report({'ERROR'}, "No image loaded")
            return {'CANCELLED'}

        # Set relative path
        if self.relative:
            try:
                image.filepath = bpy.path.relpath(image.filepath)
            except Exception:
                pass


        # For RGB (Color) channel behavior depends on layer type and override mode
        if root_ch.type == 'RGB':
            # Fill layers (COLOR type) should use image as channel source
            if layer.type != 'COLOR':
                # Paint layers - check if IMAGE override is explicitly enabled
                # If override_type is already IMAGE, user wants to override channel with image
                # Otherwise, set brush texture for painting
                override_type = getattr(ch, 'override_type', 'LAYER')
                if override_type != 'IMAGE':
                    self._set_brush_texture(context, image)
                    self.report({'INFO'}, f"Loaded image '{image.name}' as brush texture")
                    return {'FINISHED'}
            # Fill layers and Paint layers with IMAGE mode fall through to standard handling

        # For other channels, set channel override

        # Enable channel if disabled
        if not ch.enable:
            ch.enable = True

        # Enable override
        if hasattr(ch, 'override') and not ch.override:
            ch.override = True

        # Set colorspace based on channel type
        if not image.is_dirty:
            # Get filename for normal map detection
            img_name = os.path.splitext(os.path.basename(image.filepath))[0]

            # For non-color channels (metallic, roughness, normal, etc.)
            if root_ch.colorspace == 'LINEAR' or root_ch.type == 'NORMAL':
                image.colorspace_settings.name = get_noncolor_name()
            # Check if it looks like a normal map based on filename
            elif is_normal_map_filename(img_name):
                image.colorspace_settings.name = get_noncolor_name()

        # Set override type to IMAGE
        if hasattr(ch, 'override_type'):
            ch.override_type = 'IMAGE'

        # Create or update image source node
        source_node = None
        if ch.source:
            source_node = tree.nodes.get(ch.source)

        if not source_node or source_node.type != 'TEX_IMAGE':
            # Create new image texture node
            source_label = root_ch.name + ' Override : IMAGE'
            source_node, _ = check_new_node(tree, ch, 'source', 'ShaderNodeTexImage', source_label, True)

        if source_node:
            source_node.image = image
            if root_ch.type == 'NORMAL':
                source_node.interpolation = 'Cubic'

        # NOTE: Do NOT set active_edit here - this would cause the Texture Slot
        # in Texture Paint mode to load this channel's image instead of the layer image.
        # Channel override images are separate from the main paintable layer image.

        # Reconnect and rearrange nodes
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        # Request UI refresh to ensure image properties are shown
        request_ui_refresh()

        # Restore expand_blend_settings state after node operations
        if hasattr(ch, 'expand_blend_settings'):
            ch.expand_blend_settings = saved_expand_blend

        self.report({'INFO'}, f"Loaded image '{image.name}' to {root_ch.name} channel")

        return {'FINISHED'}

    def _set_brush_texture(self, context, image):
        """Set the loaded image as the brush texture for color painting.

        Args:
            context: Blender context
            image: The loaded image to use as brush texture
        """
        from ...vcol.brush_utils import activate_local_brush

        settings = context.tool_settings.image_paint
        brush = settings.brush

        if not brush:
            self.report({'WARNING'}, "No active brush found")
            return

        # Ensure sRGB colorspace for color painting
        if image.colorspace_settings.name == 'Non-Color':
            image.colorspace_settings.name = 'sRGB'

        # Create texture with image
        tex_name = f"Brush_{image.name}"
        tex = bpy.data.textures.get(tex_name)
        if not tex:
            tex = bpy.data.textures.new(tex_name, type='IMAGE')
        tex.image = image

        # If brush already has texture, just update the image
        if brush.texture:
            brush.texture.image = image
            if brush.texture_slot:
                brush.texture_slot.map_mode = 'VIEW_PLANE'
            return

        # Try direct assignment (works for local/non-linked brushes)
        if not brush.library:
            brush.texture = tex
            if brush.texture and brush.texture_slot:
                brush.texture_slot.map_mode = 'VIEW_PLANE'
            return

        # Linked brush - create/reuse a local brush with texture
        local_brush_name = "Mixar Texture Paint"
        local_brush = bpy.data.brushes.get(local_brush_name)

        if not local_brush:
            # Create new local brush for texture painting
            local_brush = bpy.data.brushes.new(local_brush_name, mode='TEXTURE_PAINT')
            local_brush.blend = brush.blend
            local_brush.size = brush.size
            local_brush.strength = brush.strength
            local_brush.use_fake_user = True
            # Mark as asset so it can be activated via asset system
            local_brush.asset_mark()

        # Set texture on local brush
        local_brush.texture = tex
        if local_brush.texture_slot:
            local_brush.texture_slot.map_mode = 'VIEW_PLANE'

        # Activate the local brush
        if activate_local_brush(local_brush_name):
            self.report({'INFO'}, f"Activated '{local_brush_name}' brush with texture")
        else:
            # Fallback: inform user to manually select the brush
            self.report({'INFO'}, f"Texture ready on '{local_brush_name}' brush. Select it from brush list.")


class MOpenImageToOverride1Channel(bpy.types.Operator, ImportHelper, OpenImage):
    """Open Image to Override 1 Channel (for Normal maps)"""
    bl_idname = "wm.m_open_image_to_override_1_layer_channel"
    bl_label = "Open Image to Override Normal"
    bl_description = "Load a normal map image to override this channel"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def invoke(self, context, event):
        if hasattr(context, 'parent'):
            self.ch = context.parent
        elif hasattr(context, 'channel'):
            self.ch = context.channel
        else:
            self.report({'ERROR'}, "No channel context found")
            return {'CANCELLED'}
        return self.running_fileselect_modal(context, event)

    def execute(self, context):
        ch = self.ch

        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        loaded_images = self.get_loaded_images()

        if len(loaded_images) == 0 or loaded_images[0] is None:
            self.report({'ERROR'}, "No image selected!")
            return {'CANCELLED'}

        image = loaded_images[0]

        # Get layer from path
        mp = node.node_tree.mp
        match = re.match(r'mp\.layers\[(\d+)\]\.channels\[(\d+)\]', ch.path_from_id())
        if not match:
            self.report({'ERROR'}, "Could not determine layer/channel from path")
            return {'CANCELLED'}

        layer_idx = int(match.group(1))
        ch_idx = int(match.group(2))

        layer = mp.layers[layer_idx]
        root_ch = mp.channels[ch_idx] if ch_idx < len(mp.channels) else None
        tree = get_tree(layer)

        if not root_ch or root_ch.type != 'NORMAL':
            self.report({'ERROR'}, "This operator is only for Normal channels")
            return {'CANCELLED'}

        # Preserve expand_blend_settings state before node operations
        # This prevents the UI from collapsing when uploading an image
        saved_expand_blend = getattr(ch, 'expand_blend_settings', False)

        # Enable override_1 for normal
        if hasattr(ch, 'override_1') and not ch.override_1:
            ch.override_1 = True

        # Set relative path
        if self.relative:
            try:
                image.filepath = bpy.path.relpath(image.filepath)
            except Exception:
                pass

        # Normal maps should always be non-color
        if not image.is_dirty:
            image.colorspace_settings.name = get_noncolor_name()

        # Create source_1 node to hold the image
        source_label = root_ch.name + ' Override 1 : IMAGE'
        image_node, dirty = check_new_node(tree, ch, 'source_1', 'ShaderNodeTexImage', source_label, True)

        if image_node:
            image_node.image = image
            # Cubic interpolation for better normal map quality
            image_node.interpolation = 'Cubic'

        # Update override type
        if hasattr(ch, 'override_1_type'):
            ch.override_1_type = 'IMAGE'

        # Reconnect and rearrange nodes
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        # Request UI refresh to ensure image properties are shown
        request_ui_refresh()

        # Restore expand_blend_settings state after node operations
        if hasattr(ch, 'expand_blend_settings'):
            ch.expand_blend_settings = saved_expand_blend

        self.report({'INFO'}, f"Loaded normal map '{image.name}'")

        return {'FINISHED'}


class MSelectExistingImage(bpy.types.Operator):
    """Select an existing image from the blend file"""
    bl_idname = "wm.m_select_existing_image_for_channel"
    bl_label = "Select Existing Image"
    bl_description = "Select an image already loaded in the blend file"
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = "image_name"

    image_name: bpy.props.EnumProperty(
        name="Image",
        description="Select an existing image",
        items=get_existing_images
    )

    channel_path: bpy.props.StringProperty(
        name="Channel Path",
        description="Path to the channel property",
        options={'HIDDEN'}
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def invoke(self, context, event):
        # Store channel path for retrieval in execute
        if hasattr(context, 'channel') and context.channel:
            self.channel_path = context.channel.path_from_id()
        else:
            self.report({'ERROR'}, "No channel context found")
            return {'CANCELLED'}
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if self.image_name == 'NONE':
            self.report({'WARNING'}, "No images available in blend file")
            return {'CANCELLED'}

        # Retrieve channel from stored path
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp
        try:
            ch = mp.path_resolve(self.channel_path.replace('mp.', ''))
        except (ValueError, AttributeError):
            self.report({'ERROR'}, "Could not resolve channel path")
            return {'CANCELLED'}
        image = bpy.data.images.get(self.image_name)

        if not image:
            self.report({'ERROR'}, f"Image '{self.image_name}' not found")
            return {'CANCELLED'}

        # Get layer and root channel from stored path
        match = re.match(r'mp\.layers\[(\d+)\]\.channels\[(\d+)\]', self.channel_path)
        if not match:
            self.report({'ERROR'}, "Could not determine layer/channel from path")
            return {'CANCELLED'}

        layer_idx = int(match.group(1))
        ch_idx = int(match.group(2))

        layer = mp.layers[layer_idx]
        root_ch = mp.channels[ch_idx] if ch_idx < len(mp.channels) else None
        tree = get_tree(layer)

        if not root_ch:
            self.report({'ERROR'}, "Root channel not found")
            return {'CANCELLED'}

        # Preserve expand_blend_settings state before node operations
        saved_expand_blend = getattr(ch, 'expand_blend_settings', False)

        # Enable channel if disabled
        if not ch.enable:
            ch.enable = True

        # Set colorspace based on channel type
        if root_ch.colorspace == 'LINEAR' or root_ch.type == 'NORMAL':
            if image.colorspace_settings.name != get_noncolor_name():
                image.colorspace_settings.name = get_noncolor_name()

        # Set override type to IMAGE
        if hasattr(ch, 'override_type'):
            ch.override_type = 'IMAGE'

        # Create or update image source node
        source_node = None
        if ch.source:
            source_node = tree.nodes.get(ch.source)

        if not source_node or source_node.type != 'TEX_IMAGE':
            # Create new image texture node
            source_label = root_ch.name + ' Override : IMAGE'
            source_node, _ = check_new_node(tree, ch, 'source', 'ShaderNodeTexImage', source_label, True)

        if source_node:
            source_node.image = image
            if root_ch.type == 'NORMAL':
                source_node.interpolation = 'Cubic'

        # Reconnect and rearrange nodes
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        # Request UI refresh to ensure image properties are shown
        request_ui_refresh()

        # Restore expand_blend_settings state after node operations
        if hasattr(ch, 'expand_blend_settings'):
            ch.expand_blend_settings = saved_expand_blend

        self.report({'INFO'}, f"Selected image '{image.name}' for {root_ch.name} channel")

        return {'FINISHED'}


class MClearChannelImage(bpy.types.Operator):
    """Clear the image from channel override"""
    bl_idname = "wm.m_clear_channel_image"
    bl_label = "Clear Channel Image"
    bl_description = "Remove the image and revert to default channel behavior"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def execute(self, context):
        # Get channel from context
        ch = getattr(context, 'channel', None)
        layer = getattr(context, 'layer', None)

        if not ch:
            self.report({'ERROR'}, "No channel context found")
            return {'CANCELLED'}

        if not layer:
            self.report({'ERROR'}, "No layer context found")
            return {'CANCELLED'}

        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp
        tree = get_tree(layer)

        # Get root channel index from path
        match = re.match(r'mp\.layers\[(\d+)\]\.channels\[(\d+)\]', ch.path_from_id())
        if not match:
            self.report({'ERROR'}, "Could not determine channel from path")
            return {'CANCELLED'}

        ch_idx = int(match.group(2))
        root_ch = mp.channels[ch_idx] if ch_idx < len(mp.channels) else None

        if not root_ch:
            self.report({'ERROR'}, "Root channel not found")
            return {'CANCELLED'}

        # Preserve expand_blend_settings state before node operations
        saved_expand_blend = getattr(ch, 'expand_blend_settings', False)

        # Clear the image from the source node
        if ch.source:
            source_node = tree.nodes.get(ch.source)
            if source_node and source_node.bl_idname == 'ShaderNodeTexImage':
                source_node.image = None

        # Reset override type based on channel and layer type
        if hasattr(ch, 'override_type'):
            # For Fill layers (COLOR type), revert to appropriate default
            if layer.type == 'COLOR':
                if root_ch.type == 'RGB':
                    ch.override_type = 'LAYER'
                elif root_ch.type == 'VALUE':
                    ch.override_type = 'OVERRIDE'
                elif root_ch.type == 'NORMAL':
                    ch.override_type = 'IMAGE'  # Normal stays IMAGE but without image
                else:
                    ch.override_type = 'LAYER'
            else:
                # For Paint layers (IMAGE type), revert to LAYER (brush mode)
                if root_ch.type == 'RGB' and root_ch.name.lower() == 'color':
                    ch.override_type = 'LAYER'
                else:
                    ch.override_type = 'OVERRIDE'

        # Reconnect and rearrange nodes
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        # Request UI refresh
        request_ui_refresh()

        # Restore expand_blend_settings state after node operations
        if hasattr(ch, 'expand_blend_settings'):
            ch.expand_blend_settings = saved_expand_blend

        self.report({'INFO'}, f"Cleared image from {root_ch.name} channel")

        return {'FINISHED'}


class MSelectExistingImageNormal(bpy.types.Operator):
    """Select an existing image for Normal map override (source_1)"""
    bl_idname = "wm.m_select_existing_normal_image_for_channel"
    bl_label = "Select Existing Normal Map"
    bl_description = "Select a normal map image already loaded in the blend file"
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = "image_name"

    image_name: bpy.props.EnumProperty(
        name="Image",
        description="Select an existing image",
        items=get_existing_images
    )

    channel_path: bpy.props.StringProperty(
        name="Channel Path",
        description="Path to the channel property",
        options={'HIDDEN'}
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def invoke(self, context, event):
        # Store channel path for retrieval in execute
        if hasattr(context, 'channel') and context.channel:
            self.channel_path = context.channel.path_from_id()
        elif hasattr(context, 'parent') and context.parent:
            self.channel_path = context.parent.path_from_id()
        else:
            self.report({'ERROR'}, "No channel context found")
            return {'CANCELLED'}
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if self.image_name == 'NONE':
            self.report({'WARNING'}, "No images available in blend file")
            return {'CANCELLED'}

        # Retrieve channel from stored path
        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp
        try:
            ch = mp.path_resolve(self.channel_path.replace('mp.', ''))
        except (ValueError, AttributeError):
            self.report({'ERROR'}, "Could not resolve channel path")
            return {'CANCELLED'}

        image = bpy.data.images.get(self.image_name)

        if not image:
            self.report({'ERROR'}, f"Image '{self.image_name}' not found")
            return {'CANCELLED'}

        # Get layer and root channel from stored path
        match = re.match(r'mp\.layers\[(\d+)\]\.channels\[(\d+)\]', self.channel_path)
        if not match:
            self.report({'ERROR'}, "Could not determine layer/channel from path")
            return {'CANCELLED'}

        layer_idx = int(match.group(1))
        ch_idx = int(match.group(2))

        layer = mp.layers[layer_idx]
        root_ch = mp.channels[ch_idx] if ch_idx < len(mp.channels) else None
        tree = get_tree(layer)

        if not root_ch or root_ch.type != 'NORMAL':
            self.report({'ERROR'}, "This operator is only for Normal channels")
            return {'CANCELLED'}

        # Preserve expand_blend_settings state before node operations
        saved_expand_blend = getattr(ch, 'expand_blend_settings', False)

        # Normal maps should always be non-color
        if image.colorspace_settings.name != get_noncolor_name():
            image.colorspace_settings.name = get_noncolor_name()

        # Enable override_1 for normal
        if hasattr(ch, 'override_1') and not ch.override_1:
            ch.override_1 = True

        # Set override_1_type to IMAGE
        if hasattr(ch, 'override_1_type'):
            ch.override_1_type = 'IMAGE'

        # Create or update source_1 node for normal map
        source_node = None
        if ch.source_1:
            source_node = tree.nodes.get(ch.source_1)

        if not source_node or source_node.type != 'TEX_IMAGE':
            # Create new image texture node
            source_label = root_ch.name + ' Override 1 : IMAGE'
            source_node, _ = check_new_node(tree, ch, 'source_1', 'ShaderNodeTexImage', source_label, True)

        if source_node:
            source_node.image = image
            # Cubic interpolation for better normal map quality
            source_node.interpolation = 'Cubic'

        # Reconnect and rearrange nodes
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        # Request UI refresh
        request_ui_refresh()

        # Restore expand_blend_settings state after node operations
        if hasattr(ch, 'expand_blend_settings'):
            ch.expand_blend_settings = saved_expand_blend

        self.report({'INFO'}, f"Selected normal map '{image.name}'")

        return {'FINISHED'}


class MClearNormalChannelImage(bpy.types.Operator):
    """Clear the normal map image from channel override (source_1)"""
    bl_idname = "wm.m_clear_normal_channel_image"
    bl_label = "Clear Normal Map Image"
    bl_description = "Remove the normal map image and revert to default color"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def execute(self, context):
        # Get channel from context
        ch = getattr(context, 'channel', None)
        layer = getattr(context, 'layer', None)

        if not ch:
            self.report({'ERROR'}, "No channel context found")
            return {'CANCELLED'}

        if not layer:
            self.report({'ERROR'}, "No layer context found")
            return {'CANCELLED'}

        node = get_active_mpaint_node()
        if not node or not node.node_tree:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp
        tree = get_tree(layer)

        # Get root channel index from path
        match = re.match(r'mp\.layers\[(\d+)\]\.channels\[(\d+)\]', ch.path_from_id())
        if not match:
            self.report({'ERROR'}, "Could not determine channel from path")
            return {'CANCELLED'}

        ch_idx = int(match.group(2))
        root_ch = mp.channels[ch_idx] if ch_idx < len(mp.channels) else None

        if not root_ch or root_ch.type != 'NORMAL':
            self.report({'ERROR'}, "This operator is only for Normal channels")
            return {'CANCELLED'}

        # Preserve expand_blend_settings state before node operations
        saved_expand_blend = getattr(ch, 'expand_blend_settings', False)

        # Clear the image from the source_1 node (normal map source)
        if ch.source_1:
            source_node = tree.nodes.get(ch.source_1)
            if source_node and source_node.bl_idname == 'ShaderNodeTexImage':
                source_node.image = None

        # Reset override_1_type to DEFAULT
        if hasattr(ch, 'override_1_type'):
            ch.override_1_type = 'DEFAULT'
        if hasattr(ch, 'override_1'):
            ch.override_1 = False

        # Reconnect and rearrange nodes
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        # Request UI refresh
        request_ui_refresh()

        # Restore expand_blend_settings state after node operations
        if hasattr(ch, 'expand_blend_settings'):
            ch.expand_blend_settings = saved_expand_blend

        self.report({'INFO'}, "Cleared normal map image")

        return {'FINISHED'}


# Classes for registration
classes = (
    MOpenImageToOverrideChannel,
    MOpenImageToOverride1Channel,
    MSelectExistingImage,
    MSelectExistingImageNormal,
    MClearChannelImage,
    MClearNormalChannelImage,
)
