# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Chat Integration Operators

Thin wrappers around ``moodboard.core.chat_sync``. Auto-sync mirrors
selected moodboard images into the chat composer; this operator is the
toolbar / ``P`` keymap force-refresh if anything ever desynchronises.
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

    # A SELECTED FRAME stands for everything inside it: selecting the frame is
    # how the user says "this set". The reverse does not hold -- selecting one
    # picture inside a frame stages that picture alone, because a click on a
    # member selects the member.
    selected_frame_ids = {
        frame.frame_id
        for frame in getattr(scene, 'mixie_moodboard_frames', ())
        if frame.selected and frame.frame_id
    }

    for i, img in enumerate(scene.mixie_moodboard_images):
        if is_video_item(img):
            continue
        if img.selected or (
            selected_frame_ids and getattr(img, 'frame_id', '') in selected_frame_ids
        ):
            image_indices.add(i)

    return image_indices


def count_selected_videos(scene) -> int:
    """Selected board videos the chat sync leaves behind."""
    return sum(
        1
        for img in getattr(scene, "mixie_moodboard_images", [])
        if getattr(img, "selected", False) and is_video_item(img)
    )


class MIXIE_OT_moodboard_send_to_chat(Operator):
    """Force the moodboard→chat sync to run immediately."""
    bl_idname = "mixie.moodboard_send_to_chat"
    bl_label = "Refresh Chat Attachments"
    bl_description = f"Refresh moodboard→chat attachment sync ({format_shortcut('P')})"
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
                force_resync,
                _reconcile_attachments,
                _collect_selected_image_names,
            )
            selected = _collect_selected_image_names(scene)
            force_resync(scene)
            _reconcile_attachments(scene, selected, animate=True)
        except Exception as e:  # noqa: BLE001 — keep the keymap functional
            self.report({'WARNING'}, f"Sync failed: {e}")
            return {'CANCELLED'}

        selected_count = sum(
            1 for att in scene.mixie_chat_pending_attachments
            if getattr(att, "is_moodboard", False)
        )
        skipped_videos = count_selected_videos(scene)
        if skipped_videos:
            # The sync silently leaves videos on the board (the chat has no
            # video content part); tell the user instead of doing nothing.
            self.report(
                {'WARNING'},
                f"Skipped {skipped_videos} video"
                f"{'s' if skipped_videos != 1 else ''}: the agent accepts "
                "still images only. Use Video Gen on the moodboard for clips",
            )
        if selected_count == 0 and not skipped_videos:
            self.report({'INFO'}, "No moodboard images selected")
        elif selected_count:
            self.report(
                {'INFO'},
                f"Synced {selected_count} moodboard image"
                f"{'s' if selected_count != 1 else ''}",
            )
        return {'FINISHED'}


class MIXIE_CHAT_OT_attach_moodboard_image(Operator):
    """Force a moodboard→chat sync — wrapper used in the chat footer so
    the tooltip reads "Attach Selected Moodboard Image" while the
    moodboard toolbar keeps the original label."""
    bl_idname = "mixie_chat.attach_moodboard_image"
    bl_label = "Attach Selected Moodboard Image"
    bl_description = (
        f"Refresh moodboard→chat attachment sync ({format_shortcut('P')})"
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
