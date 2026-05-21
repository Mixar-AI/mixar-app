# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Brush texture operators for Mixar.

This module contains operators for loading and clearing brush textures
used in texture painting. Handles both local and linked (asset library)
brushes safely - linked brushes are read-only so a local copy is created.
"""

import bpy
from bpy_extras.io_utils import ImportHelper

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...other.base_operator import OpenImage
from ...vcol.brush_utils import activate_local_brush


def get_or_create_local_brush(source_brush):
    """Get or create a local writable brush based on a linked source brush.

    Creates "Mixar Generated Brush" with asset_mark() so it can be
    activated via bpy.ops.brush.asset_activate (the only reliable way
    to switch brushes from linked brushes in Blender 5.0).

    Args:
        source_brush: The linked brush to base the local copy on.

    Returns:
        A local, writable brush, or None on failure.
    """
    local_name = "Mixar Generated Brush"
    local_brush = bpy.data.brushes.get(local_name)
    if local_brush and not local_brush.library:
        return local_brush

    local_brush = bpy.data.brushes.new(local_name, mode='TEXTURE_PAINT')
    local_brush.blend = source_brush.blend
    local_brush.size = source_brush.size
    local_brush.strength = source_brush.strength
    local_brush.use_fake_user = True
    try:
        local_brush.asset_mark()
    except Exception as e:
        logger.warning("[BrushTexOps] Could not mark as asset: %s", e)
    logger.debug("[BrushTexOps] Created local brush '%s'", local_name)
    return local_brush


def _get_writable_brush(settings):
    """Get a writable brush from the current paint settings.

    If the active brush is local, returns it directly.
    If linked (read-only), creates a local brush with asset_mark().

    Args:
        settings: The ImagePaint tool settings.

    Returns:
        Tuple of (brush, needs_activate).
        brush: The writable brush, or None.
        needs_activate: True if caller should call activate_local_brush
            after setting textures (linked brush was replaced).
    """
    brush = settings.brush
    if not brush:
        return None, False

    if not brush.library:
        return brush, False

    logger.debug("[BrushTexOps] Brush '%s' is linked (read-only)", brush.name)
    local_brush = get_or_create_local_brush(brush)
    if not local_brush:
        return None, False

    return local_brush, True


def _dedup_loaded_image(new_img):
    """Deduplicate a newly loaded image against existing images.

    If an image with the same filepath already exists, returns the existing
    one and removes the duplicate. Uses a list snapshot of the images
    collection to avoid modifying it during iteration.

    Args:
        new_img: The newly loaded bpy.types.Image.

    Returns:
        The deduplicated bpy.types.Image (existing or new).
    """
    existing_images = list(bpy.data.images)
    for old_img in existing_images:
        if old_img.filepath == new_img.filepath and old_img != new_img:
            bpy.data.images.remove(new_img)
            return old_img
    return new_img


class MOpenImageToBrushTexture(bpy.types.Operator, ImportHelper, OpenImage):
    """Open Image to Set as Brush Texture"""
    bl_idname = "wm.m_open_image_to_brush_texture"
    bl_label = "Open Image for Brush Texture"
    bl_description = "Load an image file to use as the brush texture"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not hasattr(context, 'tool_settings'):
            return False
        settings = context.tool_settings.image_paint
        return settings is not None and settings.brush is not None

    def invoke(self, context, event):
        return self.running_fileselect_modal(context, event)

    def execute(self, context):
        loaded_images = self.get_loaded_images()

        if len(loaded_images) == 0 or loaded_images[0] is None:
            self.report({'ERROR'}, "No image selected!")
            return {'CANCELLED'}

        image = _dedup_loaded_image(loaded_images[0])

        # Set relative path
        if self.relative:
            try:
                image.filepath = bpy.path.relpath(image.filepath)
            except Exception:
                pass

        settings = context.tool_settings.image_paint

        brush, needs_activate = _get_writable_brush(settings)
        if not brush:
            self.report({'ERROR'}, "No active brush found")
            return {'CANCELLED'}

        # Ensure sRGB colorspace for color painting
        if image.colorspace_settings.name == 'Non-Color':
            image.colorspace_settings.name = 'sRGB'

        # Create texture with image
        tex_name = f"Brush_{image.name}"
        tex = bpy.data.textures.get(tex_name)
        if not tex:
            tex = bpy.data.textures.new(tex_name, type='IMAGE')
        tex.image = image

        # Clear any orphaned texture (texture with no image)
        if brush.texture and not brush.texture.image:
            brush.texture = None

        if brush.texture:
            brush.texture.image = image
            if brush.texture_slot:
                brush.texture_slot.map_mode = 'VIEW_PLANE'
        else:
            brush.texture = tex
            if brush.texture and brush.texture_slot:
                brush.texture_slot.map_mode = 'VIEW_PLANE'

        if needs_activate:
            activate_local_brush(brush.name)

        self.report({'INFO'}, f"Set brush texture to '{image.name}'")
        return {'FINISHED'}


class MClearBrushTexture(bpy.types.Operator):
    """Clear the brush texture image"""
    bl_idname = "wm.m_clear_brush_texture"
    bl_label = "Clear Brush Texture"
    bl_description = "Remove the brush texture, returning to solid color mode"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not hasattr(context, 'tool_settings'):
            return False
        settings = context.tool_settings.image_paint
        return settings is not None and settings.brush is not None

    def execute(self, context):
        brush = context.tool_settings.image_paint.brush
        if not brush or not brush.texture:
            return {'FINISHED'}

        if brush.library:
            self.report({'WARNING'}, "Cannot modify linked brush texture")
            return {'CANCELLED'}

        brush.texture = None
        self.report({'INFO'}, "Cleared brush texture")
        return {'FINISHED'}


class MOpenImageToMaskTexture(bpy.types.Operator, ImportHelper, OpenImage):
    """Open Image to Set as Brush Mask Texture"""
    bl_idname = "wm.m_open_image_to_mask_texture"
    bl_label = "Open Image for Mask Texture"
    bl_description = "Load an image file to use as the brush mask texture"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not hasattr(context, 'tool_settings'):
            return False
        settings = context.tool_settings.image_paint
        return settings is not None and settings.brush is not None

    def invoke(self, context, event):
        return self.running_fileselect_modal(context, event)

    def execute(self, context):
        loaded_images = self.get_loaded_images()

        if len(loaded_images) == 0 or loaded_images[0] is None:
            self.report({'ERROR'}, "No image selected!")
            return {'CANCELLED'}

        image = _dedup_loaded_image(loaded_images[0])

        # Set relative path
        if self.relative:
            try:
                image.filepath = bpy.path.relpath(image.filepath)
            except Exception:
                pass

        settings = context.tool_settings.image_paint

        brush, needs_activate = _get_writable_brush(settings)
        if not brush:
            self.report({'ERROR'}, "No active brush found")
            return {'CANCELLED'}

        # Use Non-Color for mask textures (grayscale masks)
        if image.colorspace_settings.name != 'Non-Color':
            image.colorspace_settings.name = 'Non-Color'

        # Create texture with image
        tex_name = f"Mask_{image.name}"
        tex = bpy.data.textures.get(tex_name)
        if not tex:
            tex = bpy.data.textures.new(tex_name, type='IMAGE')
        tex.image = image

        # Clear any orphaned mask texture
        if brush.mask_texture and not brush.mask_texture.image:
            brush.mask_texture = None

        if brush.mask_texture:
            brush.mask_texture.image = image
            if brush.mask_texture_slot:
                brush.mask_texture_slot.mask_map_mode = 'VIEW_PLANE'
        else:
            brush.mask_texture = tex
            if brush.mask_texture_slot:
                brush.mask_texture_slot.mask_map_mode = 'VIEW_PLANE'

        if needs_activate:
            activate_local_brush(brush.name)

        self.report({'INFO'}, f"Set mask texture to '{image.name}'")
        return {'FINISHED'}


class MClearMaskTexture(bpy.types.Operator):
    """Clear the brush mask texture image"""
    bl_idname = "wm.m_clear_mask_texture"
    bl_label = "Clear Mask Texture"
    bl_description = "Remove the brush mask texture"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not hasattr(context, 'tool_settings'):
            return False
        settings = context.tool_settings.image_paint
        return settings is not None and settings.brush is not None

    def execute(self, context):
        brush = context.tool_settings.image_paint.brush
        if not brush or not brush.mask_texture:
            return {'FINISHED'}

        if brush.library:
            self.report({'WARNING'}, "Cannot modify linked brush mask texture")
            return {'CANCELLED'}

        brush.mask_texture = None
        self.report({'INFO'}, "Cleared mask texture")
        return {'FINISHED'}


# Classes for registration
classes = (
    MOpenImageToBrushTexture,
    MClearBrushTexture,
    MOpenImageToMaskTexture,
    MClearMaskTexture,
)
