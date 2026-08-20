# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mixie Chat Image Operators

Operators for image attachment handling in the chat interface.
"""

import os

import bpy
from bpy.props import CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, OperatorFileListElement
from bpy_extras.io_utils import ImportHelper

from ...constants import MAX_ATTACHMENTS_PER_MESSAGE, SUPPORTED_IMAGE_FORMATS
from ...core import (
    cleanup_loaded_file_image,
    cleanup_loaded_file_images,
    get_blend_images,
    get_image_display_name,
    validate_image_file,
)
from ...core.ui_utils import redraw_chat_areas, sync_bubble_attachment_size_deferred


class MIXIE_CHAT_OT_add_image_from_file(Operator, ImportHelper):
    """Add image attachment(s) from file — supports multi-select up to the per-message cap"""
    bl_idname = "mixie_chat.add_image_from_file"
    bl_label = "Add Image"
    bl_options = {'REGISTER'}

    # ImportHelper settings
    filter_glob: StringProperty(
        default="*.png;*.jpg;*.jpeg;*.bmp;*.tiff;*.tif",
        options={'HIDDEN'}
    )

    # Multi-file selection support
    files: CollectionProperty(type=OperatorFileListElement)
    directory: StringProperty(subtype='DIR_PATH')

    @classmethod
    def poll(cls, context):
        if context.scene is None:
            return False
        attachments = context.scene.mixie_chat_pending_attachments
        return len(attachments) < MAX_ATTACHMENTS_PER_MESSAGE

    def execute(self, context):
        scene = context.scene
        attachments = scene.mixie_chat_pending_attachments

        # Build list of files to add
        if self.files and any(f.name for f in self.files):
            filepaths = [
                os.path.join(self.directory, f.name)
                for f in self.files if f.name
            ]
        else:
            filepaths = [self.filepath]

        added = 0
        for filepath in filepaths:
            if len(attachments) >= MAX_ATTACHMENTS_PER_MESSAGE:
                self.report({'WARNING'},
                            f"Attachment limit ({MAX_ATTACHMENTS_PER_MESSAGE}) reached")
                break

            is_valid, error = validate_image_file(filepath)
            if not is_valid:
                self.report({'WARNING'}, f"Skipped {os.path.basename(filepath)}: {error}")
                continue

            # Skip duplicates
            already = False
            for att in attachments:
                if att.image_path == filepath and att.image_source == 'FILE':
                    already = True
                    break
            if already:
                continue

            attachment = attachments.add()
            attachment.image_path = filepath
            attachment.image_source = 'FILE'
            attachment.display_name = get_image_display_name(filepath, 'FILE')
            added += 1

        if added == 0:
            self.report({'WARNING'}, "No new images added")
            return {'CANCELLED'}

        redraw_chat_areas()
        sync_bubble_attachment_size_deferred(force_attachment_height=True)

        for area in context.screen.areas:
            if area.type == 'MIXIE_CHAT':
                for region in area.regions:
                    if region.type == 'TOOLS':
                        region.tag_redraw()

        self.report({'INFO'}, f"Added {added} image(s)")
        return {'FINISHED'}


class MIXIE_CHAT_OT_add_image_from_blend(Operator):
    """Add an image attachment from blend file data"""
    bl_idname = "mixie_chat.add_image_from_blend"
    bl_label = "Add from Blend"
    bl_options = {'REGISTER'}
    bl_property = "image_name"

    def get_blend_images_enum(self, context):
        """Get available images as enum items."""
        items = []
        images = get_blend_images()

        if not images:
            items.append(('NONE', "No images available", "No images in blend file"))
            return items

        for img in images:
            name = img['name']
            dims = f"{img['width']}x{img['height']}"
            desc = f"{dims} - {'Has data' if img['has_data'] else 'No data'}"
            items.append((name, name, desc))

        return items

    image_name: EnumProperty(
        name="Image",
        description="Select image from blend file",
        items=get_blend_images_enum
    )

    @classmethod
    def poll(cls, context):
        if context.scene is None:
            return False
        attachments = context.scene.mixie_chat_pending_attachments
        return len(attachments) < MAX_ATTACHMENTS_PER_MESSAGE

    def invoke(self, context, event):
        # Check if there are any images
        images = get_blend_images()
        if not images:
            self.report({'WARNING'}, "No images available in blend file")
            return {'CANCELLED'}

        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "image_name")

    def execute(self, context):
        if self.image_name == 'NONE':
            self.report({'WARNING'}, "No image selected")
            return {'CANCELLED'}

        scene = context.scene

        # Check if already added
        for att in scene.mixie_chat_pending_attachments:
            if att.image_path == self.image_name and att.image_source == 'BLEND_DATA':
                self.report({'WARNING'}, "Image already added")
                return {'CANCELLED'}

        # Verify image exists and has data
        if self.image_name not in bpy.data.images:
            self.report({'ERROR'}, "Image not found in blend file")
            return {'CANCELLED'}

        image = bpy.data.images[self.image_name]
        if not image.has_data:
            self.report({'WARNING'}, "Image has no pixel data")
            return {'CANCELLED'}

        # Add to pending attachments
        attachment = scene.mixie_chat_pending_attachments.add()
        attachment.image_path = self.image_name
        attachment.image_source = 'BLEND_DATA'
        attachment.display_name = get_image_display_name(self.image_name, 'BLEND_DATA')

        # Notify UI to refresh
        redraw_chat_areas()
        sync_bubble_attachment_size_deferred(force_attachment_height=True)

        self.report({'INFO'}, f"Added: {attachment.display_name}")
        return {'FINISHED'}


class MIXIE_CHAT_OT_remove_attachment(Operator):
    """Remove an image attachment"""
    bl_idname = "mixie_chat.remove_attachment"
    bl_label = "Remove Attachment"
    bl_options = {'REGISTER'}

    index: IntProperty(
        name="Index",
        description="Index of attachment to remove",
        default=0,
        min=0
    )

    @classmethod
    def poll(cls, context):
        if context.scene is None:
            return False
        return len(context.scene.mixie_chat_pending_attachments) > 0

    def execute(self, context):
        attachments = context.scene.mixie_chat_pending_attachments

        if self.index < 0 or self.index >= len(attachments):
            self.report({'ERROR'}, "Invalid attachment index")
            return {'CANCELLED'}

        att = attachments[self.index]
        name = att.display_name
        image_path = att.image_path
        image_source = att.image_source
        is_moodboard = getattr(att, "is_moodboard", False)

        # For moodboard-origin attachments, deselect the source image
        # FIRST. Otherwise the moodboard polling tick (~200 ms) re-adds
        # the attachment immediately and the X-click appears to do
        # nothing. Doing this before the remove() also keeps the
        # polling signature consistent.
        if is_moodboard:
            try:
                from mixar.modules.moodboard.core.chat_sync import (
                    deselect_moodboard_image_by_name,
                )
                deselect_moodboard_image_by_name(context.scene, image_path)
            except Exception as e:  # noqa: BLE001
                # Never block the remove if the moodboard module isn't
                # loaded — fall through to the standard remove path.
                # Logged at DEBUG so it's discoverable but doesn't spam
                # the console on every X-click in a no-moodboard setup.
                import logging
                logging.getLogger(__name__).debug(
                    "moodboard deselect skipped: %s", e, exc_info=True
                )

        attachments.remove(self.index)
        if image_source == 'FILE':
            cleanup_loaded_file_image(image_path)

        # Notify UI to refresh
        redraw_chat_areas()

        self.report({'INFO'}, f"Removed: {name}")
        return {'FINISHED'}


class MIXIE_CHAT_OT_clear_attachments(Operator):
    """Clear all pending attachments"""
    bl_idname = "mixie_chat.clear_attachments"
    bl_label = "Clear Attachments"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if context.scene is None:
            return False
        return len(context.scene.mixie_chat_pending_attachments) > 0

    def execute(self, context):
        paths = [
            att.image_path
            for att in context.scene.mixie_chat_pending_attachments
            if att.image_source == 'FILE' and att.image_path
        ]
        context.scene.mixie_chat_pending_attachments.clear()
        cleanup_loaded_file_images(paths)

        # Notify UI to refresh
        redraw_chat_areas()

        self.report({'INFO'}, "Cleared all attachments")
        return {'FINISHED'}


classes = (
    MIXIE_CHAT_OT_add_image_from_file,
    MIXIE_CHAT_OT_add_image_from_blend,
    MIXIE_CHAT_OT_remove_attachment,
    MIXIE_CHAT_OT_clear_attachments,
)
