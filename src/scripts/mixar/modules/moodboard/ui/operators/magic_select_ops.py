# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Segment bookkeeping operators for Magic Select results.

The tool itself lives in `magic_select_tool_ops.py`; these toggle, delete and
pre-upload the per-image segments it produces (green overlay, panel toggles).
"""

import bpy
from bpy.types import Operator
from bpy.props import IntProperty

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.scene_segment_manager import get_scene_segment_manager
from ...core.segment_overlay import recomposite_display_image
from ...core.canvas_context import redraw_moodboard_canvases


class MIXIE_OT_toggle_segment(Operator):
    """Toggle segment visibility"""
    bl_idname = "mixie.toggle_segment"
    bl_label = "Toggle Segment"
    bl_options = {'REGISTER', 'UNDO'}

    image_index: IntProperty(default=-1)
    segment_index: IntProperty(default=-1)

    def execute(self, context):
        scene = context.scene

        if self.image_index < 0 or self.image_index >= len(scene.mixie_moodboard_images):
            self.report({'ERROR'}, "Invalid image index")
            return {'CANCELLED'}

        img_item = scene.mixie_moodboard_images[self.image_index]

        if self.segment_index < 0 or self.segment_index >= len(img_item.segments):
            self.report({'ERROR'}, "Invalid segment index")
            return {'CANCELLED'}

        # Toggle the segment
        segment = img_item.segments[self.segment_index]
        segment.active = not segment.active

        # Recomposite display image
        recomposite_display_image(img_item)

        # Trigger redraw
        redraw_moodboard_canvases()

        return {'FINISHED'}


class MIXIE_OT_delete_segment(Operator):
    """Delete a segment"""
    bl_idname = "mixie.delete_segment"
    bl_label = "Delete Segment"
    bl_options = {'REGISTER', 'UNDO'}

    image_index: IntProperty(default=-1)
    segment_index: IntProperty(default=-1)

    def execute(self, context):
        scene = context.scene

        if self.image_index < 0 or self.image_index >= len(scene.mixie_moodboard_images):
            self.report({'ERROR'}, "Invalid image index")
            return {'CANCELLED'}

        img_item = scene.mixie_moodboard_images[self.image_index]

        if self.segment_index < 0 or self.segment_index >= len(img_item.segments):
            self.report({'ERROR'}, "Invalid segment index")
            return {'CANCELLED'}

        # Get the segment's mask image before removing
        segment = img_item.segments[self.segment_index]
        mask_img = segment.mask_image

        # Remove the segment from collection
        img_item.segments.remove(self.segment_index)

        # Clean up mask image
        if mask_img:
            try:
                bpy.data.images.remove(mask_img)
            except:
                pass

        # Recomposite display image
        recomposite_display_image(img_item)

        # Trigger redraw
        redraw_moodboard_canvases()

        return {'FINISHED'}


class MIXIE_OT_moodboard_upload_to_sam(Operator):
    """Upload image for AI segmentation"""
    bl_idname = "mixie.moodboard_upload_to_sam"
    bl_label = "Upload for Segmentation"
    bl_options = {'REGISTER'}

    image_index: IntProperty(
        name="Image Index",
        description="Index of image to upload",
        default=-1
    )

    def execute(self, context):
        scene = context.scene
        manager = get_scene_segment_manager()

        if self.image_index < 0:
            # Upload all images
            if hasattr(scene, 'mixie_moodboard_images'):
                count = 0
                for img_item in scene.mixie_moodboard_images:
                    if img_item.image:
                        if manager.queue_upload(img_item.image, img_item=img_item):
                            count += 1
                if count > 0:
                    self.report({'INFO'}, f"Queued {count} images for upload")
                else:
                    self.report({'INFO'}, "All images already uploaded")
        else:
            # Upload specific image
            if self.image_index >= len(scene.mixie_moodboard_images):
                self.report({'ERROR'}, "Invalid image index")
                return {'CANCELLED'}

            img_item = scene.mixie_moodboard_images[self.image_index]
            if not img_item.image:
                self.report({'ERROR'}, "No image data")
                return {'CANCELLED'}

            if manager.queue_upload(img_item.image, img_item=img_item):
                self.report({'INFO'}, f"Uploading '{img_item.image.name}'...")
            else:
                if manager.is_ready(img_item.image):
                    self.report({'INFO'}, "Image already uploaded")
                else:
                    self.report({'INFO'}, "Upload already in progress")

        return {'FINISHED'}


classes = (
    MIXIE_OT_toggle_segment,
    MIXIE_OT_delete_segment,
    MIXIE_OT_moodboard_upload_to_sam,
)
