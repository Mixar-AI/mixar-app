# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export operators for baked channels and textures.

This module provides operators to export baked channel images and mesh map
textures to disk via the file browser.
"""

import os

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy_extras.io_utils import ExportHelper

from mixar.config.logging_config import get_logger
from mixar.modules.common.analytics.export_events import capture_export

logger = get_logger(__name__)

from ....core.node.node_utils import get_active_mpaint_node
from ....utils.bake_constants import (
    EXPORT_FORMAT_EXTENSIONS,
    EXPORT_FILE_FORMAT_ITEMS,
)
from ....utils.bake_utils import sanitize_filename


def _capture_export(context, export_format, success, **extra):
    try:
        capture_export(context, export_format=export_format, success=success, extra=extra)
    except Exception:
        pass


def _save_image_to_file(image, filepath, file_format):
    """Save an image to file using Blender's render settings.

    Args:
        image: Blender image to save
        filepath: Destination file path
        file_format: File format string (PNG, OPEN_EXR, TIFF, JPEG)

    Returns:
        bool: True if successful, False otherwise
    """
    scene = bpy.context.scene
    settings = scene.render.image_settings

    # Store original settings
    ori_format = settings.file_format
    ori_color_mode = settings.color_mode
    ori_color_depth = settings.color_depth
    ori_compression = settings.compression
    ori_quality = settings.quality

    try:
        # Set format
        settings.file_format = file_format

        # Set color mode based on image and format
        if file_format == 'JPEG':
            settings.color_mode = 'RGB'
            settings.quality = 90
        else:
            settings.color_mode = 'RGBA' if image.channels == 4 else 'RGB'

        # Set color depth
        if file_format == 'OPEN_EXR':
            settings.color_depth = '32'
        elif image.is_float:
            settings.color_depth = '16'
        else:
            settings.color_depth = '8'

        # Set compression for PNG
        if file_format == 'PNG':
            settings.compression = 15

        # Save the image
        image.save_render(filepath, scene=scene)
        return True

    except Exception as e:
        logger.error("[BakeExport] Error saving image: %s", e)
        return False

    finally:
        # Restore original settings
        settings.file_format = ori_format
        settings.color_mode = ori_color_mode
        settings.color_depth = ori_color_depth
        settings.compression = ori_compression
        settings.quality = ori_quality


def _get_baked_channel_images(mp, tree):
    """Get list of baked channel images.

    Args:
        mp: MPaint property group
        tree: Node tree

    Returns:
        list: List of tuples (channel, image)
    """
    baked_channels = []
    for ch in mp.channels:
        baked_node = tree.nodes.get(ch.baked)
        if baked_node and baked_node.image:
            baked_channels.append((ch, baked_node.image))
    return baked_channels


def _get_baked_mesh_map_images():
    """Get list of baked mesh map images.

    Returns:
        list: List of baked mesh map images
    """
    baked_images = []
    for image in bpy.data.images:
        bi = image.m_bake_info
        if bi.is_baked and not bi.is_baked_channel:
            baked_images.append(image)
    return baked_images


# =============================================================================
# EXPORT SINGLE BAKED CHANNEL
# =============================================================================

class MExportBakedChannel(bpy.types.Operator, ExportHelper):
    """Export a single baked channel image to file"""

    bl_idname = "wm.m_export_baked_channel"
    bl_label = "Export Baked Channel"
    bl_description = "Export this baked channel image to a file"
    bl_options = {"REGISTER"}

    # ExportHelper properties
    filename_ext = ".png"
    filter_glob: StringProperty(
        default="*.png;*.exr;*.tiff;*.tif;*.jpg;*.jpeg",
        options={'HIDDEN'}
    )

    # Custom properties
    channel_name: StringProperty(
        name="Channel Name",
        description="Name of the channel to export",
        default=""
    )

    file_format: EnumProperty(
        name="Format",
        description="File format for export",
        items=EXPORT_FILE_FORMAT_ITEMS,
        default='PNG'
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def invoke(self, context, event):
        # Set default filename from channel name
        if self.channel_name:
            ext = EXPORT_FORMAT_EXTENSIONS.get(self.file_format, '.png')
            self.filepath = f"{self.channel_name}{ext}"

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def check(self, context):
        """Update file extension when format changes."""
        change_ext = False
        filepath = self.filepath
        new_ext = EXPORT_FORMAT_EXTENSIONS.get(self.file_format, '.png')

        if filepath:
            # Remove old extension
            for ext in EXPORT_FORMAT_EXTENSIONS.values():
                if filepath.lower().endswith(ext):
                    filepath = filepath[:-len(ext)]
                    break

            # Add new extension
            filepath = filepath + new_ext

            if filepath != self.filepath:
                self.filepath = filepath
                change_ext = True

        return change_ext

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "file_format")

    def execute(self, context):
        node = get_active_mpaint_node()
        if not node:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp
        tree = node.node_tree

        # Find the channel and its baked image
        for ch in mp.channels:
            if ch.name == self.channel_name:
                baked_node = tree.nodes.get(ch.baked)
                if baked_node and baked_node.image:
                    image = baked_node.image

                    if _save_image_to_file(image, self.filepath, self.file_format):
                        self.report({'INFO'}, f"Exported '{self.channel_name}' to {self.filepath}")
                        _capture_export(context, "BAKED_CHANNEL", True, channel_name=self.channel_name, file_format=self.file_format)
                        return {'FINISHED'}
                    else:
                        self.report({'ERROR'}, f"Failed to export '{self.channel_name}'")
                        _capture_export(context, "BAKED_CHANNEL", False, channel_name=self.channel_name, file_format=self.file_format)
                        return {'CANCELLED'}

        self.report({'ERROR'}, f"Channel '{self.channel_name}' not found or not baked")
        return {'CANCELLED'}


# =============================================================================
# EXPORT ALL BAKED CHANNELS
# =============================================================================

class MExportAllBakedChannels(bpy.types.Operator, ExportHelper):
    """Export all baked channel images to a directory"""

    bl_idname = "wm.m_export_all_baked_channels"
    bl_label = "Export All Baked Channels"
    bl_description = "Export all baked channel images to a folder"
    bl_options = {"REGISTER"}

    # Use directory selection
    filename_ext = ""
    use_filter_folder = True

    # Directory path - ExportHelper uses filepath, we'll extract directory
    filepath: StringProperty(subtype='DIR_PATH')

    file_format: EnumProperty(
        name="Format",
        description="File format for export",
        items=EXPORT_FILE_FORMAT_ITEMS,
        default='PNG'
    )

    @classmethod
    def poll(cls, context):
        node = get_active_mpaint_node()
        if not node:
            return False
        mp = node.node_tree.mp
        tree = node.node_tree
        # Check if there are any baked channels
        for ch in mp.channels:
            baked_node = tree.nodes.get(ch.baked)
            if baked_node and baked_node.image:
                return True
        return False

    def invoke(self, context, event):
        # Set to current blend file directory or home
        if bpy.data.filepath:
            self.filepath = os.path.dirname(bpy.data.filepath)
        else:
            self.filepath = os.path.expanduser("~")

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "file_format")

        # Show preview of what will be exported
        node = get_active_mpaint_node()
        if node:
            mp = node.node_tree.mp
            tree = node.node_tree
            baked = _get_baked_channel_images(mp, tree)

            if baked:
                box = layout.box()
                box.label(text=f"Will export {len(baked)} channel(s):", icon='INFO')
                col = box.column(align=True)
                col.scale_y = 0.8
                for ch, img in baked:
                    col.label(text=f"  {ch.name}")

    def execute(self, context):
        node = get_active_mpaint_node()
        if not node:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp
        tree = node.node_tree

        # Get directory from filepath
        directory = self.filepath
        if os.path.isfile(directory):
            directory = os.path.dirname(directory)

        # Ensure directory exists
        if not os.path.exists(directory):
            try:
                os.makedirs(directory)
            except OSError as e:
                self.report({'ERROR'}, f"Cannot create directory: {e}")
                _capture_export(context, "BAKED_CHANNELS_ALL", False, file_format=self.file_format, image_count=0)
                return {'CANCELLED'}

        baked_channels = _get_baked_channel_images(mp, tree)
        ext = EXPORT_FORMAT_EXTENSIONS.get(self.file_format, '.png')

        exported_count = 0
        for ch, image in baked_channels:
            # Sanitize channel name for safe filename
            clean_name = sanitize_filename(ch.name)
            filepath = os.path.join(directory, f"{clean_name}{ext}")
            if _save_image_to_file(image, filepath, self.file_format):
                exported_count += 1

        if exported_count > 0:
            self.report({'INFO'}, f"Exported {exported_count} channel(s) to {directory}")
            _capture_export(context, "BAKED_CHANNELS_ALL", True, file_format=self.file_format, image_count=exported_count)
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "No channels were exported")
            _capture_export(context, "BAKED_CHANNELS_ALL", False, file_format=self.file_format, image_count=0)
            return {'CANCELLED'}


# =============================================================================
# EXPORT SINGLE BAKED TEXTURE (MESH MAP)
# =============================================================================

class MExportBakedTexture(bpy.types.Operator, ExportHelper):
    """Export a single baked texture/mesh map image to file"""

    bl_idname = "wm.m_export_baked_texture"
    bl_label = "Export Baked Texture"
    bl_description = "Export this baked texture image to a file"
    bl_options = {"REGISTER"}

    # ExportHelper properties
    filename_ext = ".png"
    filter_glob: StringProperty(
        default="*.png;*.exr;*.tiff;*.tif;*.jpg;*.jpeg",
        options={'HIDDEN'}
    )

    # Custom properties
    image_name: StringProperty(
        name="Image Name",
        description="Name of the image to export",
        default=""
    )

    file_format: EnumProperty(
        name="Format",
        description="File format for export",
        items=EXPORT_FILE_FORMAT_ITEMS,
        default='PNG'
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def invoke(self, context, event):
        # Set default filename from image name
        if self.image_name:
            ext = EXPORT_FORMAT_EXTENSIONS.get(self.file_format, '.png')
            # Sanitize image name for safe filename
            clean_name = sanitize_filename(self.image_name)
            self.filepath = f"{clean_name}{ext}"

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def check(self, context):
        """Update file extension when format changes."""
        change_ext = False
        filepath = self.filepath
        new_ext = EXPORT_FORMAT_EXTENSIONS.get(self.file_format, '.png')

        if filepath:
            # Remove old extension
            for ext in EXPORT_FORMAT_EXTENSIONS.values():
                if filepath.lower().endswith(ext):
                    filepath = filepath[:-len(ext)]
                    break

            # Add new extension
            filepath = filepath + new_ext

            if filepath != self.filepath:
                self.filepath = filepath
                change_ext = True

        return change_ext

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "file_format")

    def execute(self, context):
        image = bpy.data.images.get(self.image_name)
        if not image:
            self.report({'ERROR'}, f"Image '{self.image_name}' not found")
            return {'CANCELLED'}

        if _save_image_to_file(image, self.filepath, self.file_format):
            self.report({'INFO'}, f"Exported '{self.image_name}' to {self.filepath}")
            _capture_export(context, "BAKED_TEXTURE", True, file_format=self.file_format)
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, f"Failed to export '{self.image_name}'")
            _capture_export(context, "BAKED_TEXTURE", False, file_format=self.file_format)
            return {'CANCELLED'}


# =============================================================================
# EXPORT ALL BAKED TEXTURES (MESH MAPS)
# =============================================================================

class MExportAllBakedTextures(bpy.types.Operator, ExportHelper):
    """Export all baked texture/mesh map images to a directory"""

    bl_idname = "wm.m_export_all_baked_textures"
    bl_label = "Export All Baked Textures"
    bl_description = "Export all baked texture images to a folder"
    bl_options = {"REGISTER"}

    # Use directory selection
    filename_ext = ""
    use_filter_folder = True

    filepath: StringProperty(subtype='DIR_PATH')

    file_format: EnumProperty(
        name="Format",
        description="File format for export",
        items=EXPORT_FILE_FORMAT_ITEMS,
        default='PNG'
    )

    @classmethod
    def poll(cls, context):
        # Check if there are any baked mesh map images
        baked_images = _get_baked_mesh_map_images()
        return len(baked_images) > 0

    def invoke(self, context, event):
        # Set to current blend file directory or home
        if bpy.data.filepath:
            self.filepath = os.path.dirname(bpy.data.filepath)
        else:
            self.filepath = os.path.expanduser("~")

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "file_format")

        # Show preview of what will be exported
        baked_images = _get_baked_mesh_map_images()
        if baked_images:
            box = layout.box()
            box.label(text=f"Will export {len(baked_images)} texture(s):", icon='INFO')
            col = box.column(align=True)
            col.scale_y = 0.8
            for img in baked_images:
                col.label(text=f"  {img.name}")

    def execute(self, context):
        # Get directory from filepath
        directory = self.filepath
        if os.path.isfile(directory):
            directory = os.path.dirname(directory)

        # Ensure directory exists
        if not os.path.exists(directory):
            try:
                os.makedirs(directory)
            except OSError as e:
                self.report({'ERROR'}, f"Cannot create directory: {e}")
                _capture_export(context, "BAKED_TEXTURES_ALL", False, file_format=self.file_format, image_count=0)
                return {'CANCELLED'}

        baked_images = _get_baked_mesh_map_images()
        ext = EXPORT_FORMAT_EXTENSIONS.get(self.file_format, '.png')

        exported_count = 0
        for image in baked_images:
            # Sanitize image name for safe filename
            clean_name = sanitize_filename(image.name)
            filepath = os.path.join(directory, f"{clean_name}{ext}")
            if _save_image_to_file(image, filepath, self.file_format):
                exported_count += 1

        if exported_count > 0:
            self.report({'INFO'}, f"Exported {exported_count} texture(s) to {directory}")
            _capture_export(context, "BAKED_TEXTURES_ALL", True, file_format=self.file_format, image_count=exported_count)
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "No textures were exported")
            _capture_export(context, "BAKED_TEXTURES_ALL", False, file_format=self.file_format, image_count=0)
            return {'CANCELLED'}


# =============================================================================
# REGISTRATION
# =============================================================================

classes = (
    MExportBakedChannel,
    MExportAllBakedChannels,
    MExportBakedTexture,
    MExportAllBakedTextures,
)
