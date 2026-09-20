# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Chat Integration Operators

Explicitly attach the current moodboard selection through the same additive
sync as automatic selection. The toolbar and P binding can reattach a removed
reference without toggling its board selection; existing references stay put.
"""

from bpy.types import Operator

from ....common.utils.platform_utils import format_shortcut
from ...core.media_utils import is_video_item


def get_all_image_indices_to_send(scene):
    """
    Get all image indices that should be sent to chat.
    This includes directly selected images and images from selected groups.

    Kept as a public helper because other moodboard ops (image-to-3D,
    lookdev, etc.) call it to know which images the user has staged.
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
        if img.selected and not is_video_item(img):
            image_indices.add(i)
        elif img.group_index in selected_group_indices and not is_video_item(img):
            # Image belongs to a group being sent
            image_indices.add(i)

    return image_indices


class MIXIE_OT_moodboard_send_to_chat(Operator):
    """Add selected moodboard references without replacing staged references."""
    bl_idname = "mixie.moodboard_send_to_chat"
    bl_label = "Attach Selected to Chat"
    bl_description = f"Add selected images to chat references ({format_shortcut('P')})"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        scene = context.scene
        if scene is None:
            return False
        if not hasattr(scene, 'mixie_moodboard_images'):
            return False
        if not hasattr(scene, 'mixie_chat_pending_attachments'):
            return False
        return True

    def execute(self, context):
        scene = context.scene
        try:
            from mixar.modules.moodboard.core.chat_sync import (
                consume_selection,
                _reconcile_attachments,
                _collect_selected_image_names,
            )
            before = len(scene.mixie_chat_pending_attachments)
            selected = _collect_selected_image_names(scene)
            _reconcile_attachments(scene, selected, animate=True)
            consume_selection(scene)
        except Exception as e:  # noqa: BLE001 — keep the keymap functional
            self.report({'WARNING'}, f"Sync failed: {e}")
            return {'CANCELLED'}

        added = len(scene.mixie_chat_pending_attachments) - before
        if not selected:
            self.report({'INFO'}, "No moodboard images selected")
        elif added:
            self.report(
                {'INFO'},
                f"Attached {added} reference{'s' if added != 1 else ''}",
            )
        else:
            self.report({'INFO'}, "No new references attached")
        return {'FINISHED'}


class MIXIE_CHAT_OT_attach_moodboard_image(Operator):
    """Force a moodboard→chat sync — wrapper used in the chat footer so
    the tooltip reads "Attach Selected Moodboard Image" while the
    moodboard toolbar keeps the original label."""
    bl_idname = "mixie_chat.attach_moodboard_image"
    bl_label = "Attach Selected Moodboard Image"
    bl_description = (
        f"Add selected images to chat references ({format_shortcut('P')})"
    )
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return MIXIE_OT_moodboard_send_to_chat.poll(context)

    def execute(self, context):
        import bpy
        return bpy.ops.mixie.moodboard_send_to_chat()


classes = (
    MIXIE_OT_moodboard_send_to_chat,
    MIXIE_CHAT_OT_attach_moodboard_image,
)
