# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Chat Integration Operators

Operators for transferring selected moodboard images to Mixie Chat attachments.
"""

import bpy
from bpy.types import Operator

from ....common.utils.platform_utils import format_shortcut


def get_all_image_indices_to_send(scene):
    """
    Get all image indices that should be sent to chat.
    This includes directly selected images and images from selected groups.
    """
    image_indices = set()

    # Get selected group indices
    selected_group_indices = set()
    for i, group in enumerate(scene.mixie_moodboard_groups):
        if group.selected:
            selected_group_indices.add(i)

    # Get group indices from selected images (group cohesion)
    for img in scene.mixie_moodboard_images:
        if img.selected and img.group_index >= 0:
            selected_group_indices.add(img.group_index)

    # Collect images
    for i, img in enumerate(scene.mixie_moodboard_images):
        if img.selected:
            image_indices.add(i)
        elif img.group_index in selected_group_indices:
            # Image belongs to a group being sent
            image_indices.add(i)

    return image_indices


class MIXIE_OT_moodboard_send_to_chat(Operator):
    """Add selected moodboard images to Mixie Chat pending attachments"""
    bl_idname = "mixie.moodboard_send_to_chat"
    bl_label = "Send to Mixie Chat"
    bl_description = f"Add selected moodboard images to Mixie Chat pending attachments ({format_shortcut('P')})"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        """Check if operator can run."""
        if context.scene is None:
            return False

        scene = context.scene

        # Check if any moodboard images are selected (directly or via groups)
        if not hasattr(scene, 'mixie_moodboard_images'):
            return False

        # Check for directly selected images or selected groups
        has_selection = any(img.selected for img in scene.mixie_moodboard_images)
        has_group_selection = (
            hasattr(scene, 'mixie_moodboard_groups') and
            any(group.selected for group in scene.mixie_moodboard_groups)
        )

        if not has_selection and not has_group_selection:
            return False

        # Check if space_mixie_chat module is available
        if not hasattr(scene, 'mixie_chat_pending_attachments'):
            return False

        # Import MAX_ATTACHMENTS_PER_MESSAGE to check limit
        try:
            from ....space_mixie_chat.constants import MAX_ATTACHMENTS_PER_MESSAGE
            current_count = len(scene.mixie_chat_pending_attachments)
            if current_count >= MAX_ATTACHMENTS_PER_MESSAGE:
                return False
        except ImportError:
            return False

        return True

    def execute(self, context):
        """Transfer selected moodboard images to chat pending attachments."""
        scene = context.scene

        # Import required constants and utilities
        try:
            from ....space_mixie_chat.constants import MAX_ATTACHMENTS_PER_MESSAGE
            from ....space_mixie_chat.core import get_image_display_name
            from ....space_mixie_chat.core.ui_utils import redraw_chat_areas
        except ImportError:
            self.report({'ERROR'}, "Mixie Chat module not available")
            return {'CANCELLED'}

        # Get all image indices to send (including from groups)
        image_indices = get_all_image_indices_to_send(scene)

        # Collect images with valid image data
        selected_images = []
        for i in image_indices:
            moodboard_img = scene.mixie_moodboard_images[i]

            # Validate image data
            if moodboard_img.image is None:
                continue

            if not moodboard_img.image.has_data:
                continue

            selected_images.append(moodboard_img)

        # Check if we have any valid selected images
        if not selected_images:
            self.report({'WARNING'}, "No valid images selected")
            return {'CANCELLED'}

        # Calculate available slots
        current_count = len(scene.mixie_chat_pending_attachments)
        available_slots = MAX_ATTACHMENTS_PER_MESSAGE - current_count

        if available_slots <= 0:
            self.report(
                {'WARNING'},
                f"Already at maximum attachments ({MAX_ATTACHMENTS_PER_MESSAGE})",
            )
            return {'CANCELLED'}

        # Check for duplicates and add images
        added_count = 0
        duplicate_count = 0

        for moodboard_img in selected_images:
            # Stop if we've filled all available slots
            if added_count >= available_slots:
                break

            image_name = moodboard_img.image.name

            # Check if this image is already attached
            is_duplicate = False
            for att in scene.mixie_chat_pending_attachments:
                if att.image_source == 'BLEND_DATA' and att.image_path == image_name:
                    is_duplicate = True
                    duplicate_count += 1
                    break

            if is_duplicate:
                continue

            # Add to pending attachments
            attachment = scene.mixie_chat_pending_attachments.add()
            attachment.image_path = image_name
            attachment.image_source = 'BLEND_DATA'
            attachment.display_name = get_image_display_name(image_name, 'BLEND_DATA')
            added_count += 1

        redraw_chat_areas()

        # Report results
        if added_count == 0:
            if duplicate_count > 0:
                self.report({'WARNING'}, "Selected images already in chat attachments")
            else:
                self.report({'WARNING'}, "No images could be added")
            return {'CANCELLED'}

        # Build success message
        message_parts = [f"Added {added_count} image{'s' if added_count != 1 else ''}"]

        # Add information about skipped images
        skipped_count = len(selected_images) - added_count - duplicate_count
        if duplicate_count > 0 or skipped_count > 0:
            skip_reasons = []
            if duplicate_count > 0:
                skip_reasons.append(f"{duplicate_count} already attached")
            if skipped_count > 0:
                skip_reasons.append(f"{skipped_count} invalid")
            message_parts.append(f"skipped {', '.join(skip_reasons)}")

        # Add limit warning if applicable
        if added_count < len(selected_images):
            remaining = len(selected_images) - added_count - duplicate_count
            if remaining > 0:
                message_parts.append(
                    f"limit reached (max {MAX_ATTACHMENTS_PER_MESSAGE})"
                )

        message = ", ".join(message_parts)

        # Use INFO for partial success, no need for WARNING
        report_type = 'INFO'
        self.report({report_type}, message)

        return {'FINISHED'}


class MIXIE_CHAT_OT_attach_moodboard_image(Operator):
    """Attach selected moodboard image(s) to Mixie Chat — wrapper used in the chat footer
    so the tooltip reads "Attach Selected Moodboard Image" while the moodboard toolbar
    keeps the original "Send to Mixie Chat" label."""
    bl_idname = "mixie_chat.attach_moodboard_image"
    bl_label = "Attach Selected Moodboard Image"
    bl_description = f"Attach selected moodboard image(s) to Mixie Chat ({format_shortcut('P')})"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return MIXIE_OT_moodboard_send_to_chat.poll(context)

    def execute(self, context):
        return bpy.ops.mixie.moodboard_send_to_chat()


classes = (
    MIXIE_OT_moodboard_send_to_chat,
    MIXIE_CHAT_OT_attach_moodboard_image,
)
