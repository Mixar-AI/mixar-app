# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Magic Select Tool Operators

Operators for AI-powered object selection using Scene Segment (SAM3) service.
Click on an image to segment objects - segments are stored per-image
and overlayed with a green highlight. Toggle segments on/off in the panel.
"""

import tempfile
import os

import bpy
from bpy.types import Operator
from bpy.props import IntProperty

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.moodboard_utils import (
    mouse_to_image_coords,
)
from ...core.scene_segment_manager import get_scene_segment_manager
from ...core.segment_overlay import recomposite_display_image
from ...core.media_utils import is_still_item


class MIXIE_OT_moodboard_magic_select_tool(Operator):
    """Activate Magic Select - click on image to segment object with AI"""
    bl_idname = "mixie.moodboard_magic_select_tool"
    bl_label = "Magic Select Tool"
    bl_description = "Activate Magic Select - click on image to segment object with AI"
    bl_options = {'REGISTER', 'BLOCKING'}

    # Store context for async callbacks
    _target_image_index: int = -1
    _upload_pending: bool = False

    @classmethod
    def poll(cls, context):
        if not hasattr(context.scene, 'mixie_moodboard_images'):
            return False
        selected = [i for i, img in enumerate(context.scene.mixie_moodboard_images)
                    if img.selected and is_still_item(img)]
        return len(selected) == 1

    def modal(self, context, event):
        scene = context.scene
        state = scene.mixie_edit_tool_state

        # Handle ESC to cancel
        if event.type == 'ESC':
            self._cleanup_state(state, context)
            return {'CANCELLED'}

        # Don't process clicks while upload or segmentation is pending
        if self._upload_pending or state.magic_select_pending:
            return {'PASS_THROUGH'}

        # Handle left mouse click
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            # Get normalized image coordinates
            img_rel = mouse_to_image_coords(context, event, state.target_image_index)
            if img_rel is None:
                # Click outside image - deactivate tool like ESC
                self._cleanup_state(state, context)
                return {'CANCELLED'}

            click_x, click_y = img_rel

            # Perform segmentation (image is already uploaded)
            self._perform_segmentation(context, state, click_x, click_y)
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def _perform_segmentation(self, context, state, click_x, click_y, _retry=False):
        """Perform Scene Segment (SAM3) segmentation at the clicked point."""
        scene = context.scene
        img_item = scene.mixie_moodboard_images[self._target_image_index]

        # Mark as pending
        state.magic_select_pending = True
        self.report({'INFO'}, "Segmenting...")

        # API uses y=0 at top, Blender View2D uses y=0 at bottom
        api_y = 1.0 - click_y

        # Scene Segment API uses label: 1=include, 0=exclude
        points = [{"x": click_x, "y": api_y, "label": 1}]

        manager = get_scene_segment_manager()

        def on_complete(success: bool, mask_bytes, message: str):
            """Handle segmentation completion (called on main thread by manager)."""
            if success and mask_bytes:
                self._create_segment(context, state, mask_bytes)
            else:
                error_msg = message or "Unknown error"
                if error_msg == "expired" and not _retry:
                    logger.debug("[MagicSelect] Job expired, re-uploading and retrying...")
                    try:
                        self._upload_and_retry(context, state, click_x, click_y)
                    except Exception as e:
                        state.magic_select_pending = False
                        logger.warning("[MagicSelect] Re-upload failed: %s", e)
                    return
                state.magic_select_pending = False
                if "402" in error_msg or "credit" in error_msg.lower():
                    self.report({'ERROR'}, "Insufficient credits for segmentation")
                elif "no object" in error_msg.lower() or "empty" in error_msg.lower():
                    self.report({'WARNING'}, "No object detected. Try clicking elsewhere.")
                else:
                    self.report({'ERROR'}, f"Segmentation failed: {error_msg}")
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == 'MIXIE':
                            area.tag_redraw()

        manager.request_segmentation(
            image=img_item.image,
            points=points,
            on_complete=on_complete,
        )

    def _upload_and_retry(self, context, state, click_x, click_y):
        """Re-upload image and retry segmentation after expiry."""
        scene = context.scene
        img_item = scene.mixie_moodboard_images[self._target_image_index]
        manager = get_scene_segment_manager()

        def on_upload_complete(success, message):
            if success:
                self._perform_segmentation(context, state, click_x, click_y, _retry=True)
            else:
                state.magic_select_pending = False
                self.report({'ERROR'}, f"Re-upload failed: {message}")
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == 'MIXIE':
                            area.tag_redraw()

        manager.queue_upload(img_item.image, img_item=img_item,
                             on_complete=on_upload_complete)

    def _create_segment(self, context, state, mask_bytes):
        """Add segment to image's segment collection and recomposite."""
        scene = bpy.context.scene

        mask_temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix='_mask.png', delete=False) as f:
                f.write(mask_bytes)
                mask_temp_path = f.name

            # Load mask as Blender image
            mask_img = bpy.data.images.load(mask_temp_path, check_existing=False)

            if mask_img.size[0] == 0 or mask_img.size[1] == 0:
                state.magic_select_pending = False
                logger.error("[SceneSegment] Invalid mask dimensions")
                bpy.data.images.remove(mask_img)
                return

            # Get the target image item
            img_item = scene.mixie_moodboard_images[self._target_image_index]

            # Determine next segment index
            next_index = len(img_item.segments) + 1
            segment_name = f"Segment {next_index}"

            # Rename mask image
            mask_img.name = f"{img_item.image.name}_{segment_name}_mask"
            mask_img.pack()

            # Add to segments collection
            segment = img_item.segments.add()
            segment.mask_image = mask_img
            segment.active = True
            segment.index = next_index
            segment.name = segment_name

            # Recomposite display image with all active segments
            recomposite_display_image(img_item)
            from ...core.component_debug import add_sam3_mask_preview

            add_sam3_mask_preview(
                scene, self._target_image_index, mask_img, segment_name,
            )

            state.magic_select_pending = False
            logger.debug("[SceneSegment] Added %s to image", segment_name)

            # Trigger redraw
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'MIXIE':
                        area.tag_redraw()

        except Exception as e:
            state.magic_select_pending = False
            logger.error("[SceneSegment] Failed to create segment: %s", e, exc_info=True)

            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'MIXIE':
                        area.tag_redraw()
        finally:
            if mask_temp_path:
                try:
                    os.unlink(mask_temp_path)
                except OSError:
                    pass

    def _cleanup_state(self, state, context):
        """Clean up tool state."""
        state.active_tool = 'NONE'
        state.target_image_index = -1
        state.magic_select_pending = False
        self._upload_pending = False
        if context.area:
            context.area.tag_redraw()

    def invoke(self, context, event):
        scene = context.scene
        state = scene.mixie_edit_tool_state

        # Surface the segments panel (Character Parts / Scene Gen fallback)
        from ..sidebar_ui_helpers import focus_segments_panel
        focus_segments_panel(context)

        # Find the selected image
        selected_idx = -1
        for i, img in enumerate(scene.mixie_moodboard_images):
            if img.selected and is_still_item(img):
                selected_idx = i
                break

        if selected_idx < 0:
            self.report({'WARNING'}, "No image selected")
            return {'CANCELLED'}

        img_item = scene.mixie_moodboard_images[selected_idx]
        image = img_item.image

        # Initialize state
        state.active_tool = 'MAGIC_SELECT'
        state.target_image_index = selected_idx
        state.magic_select_pending = False
        self._target_image_index = selected_idx
        self._upload_pending = False

        # Check if image needs to be uploaded
        manager = get_scene_segment_manager()

        def on_upload_complete(success, message):
            self._upload_pending = False
            if success:
                self.report({'INFO'}, "Ready! Click on image to segment.")
            else:
                self.report({'ERROR'}, f"Upload failed: {message}")
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'MIXIE':
                        area.tag_redraw()

        if manager.is_uploading(image):
            self.report({'INFO'}, "Waiting for image upload...")
            self._upload_pending = True
            # Join the existing upload. Without registering a waiter this
            # modal remained pending forever even after the upload completed.
            manager.queue_upload(
                image, img_item=img_item, on_complete=on_upload_complete,
            )
        elif not manager.is_ready(image):
            self.report({'INFO'}, "Uploading image for segmentation...")
            self._upload_pending = True
            manager.queue_upload(image, img_item=img_item, on_complete=on_upload_complete)
        else:
            self.report({'INFO'}, "Click on image to segment object. ESC to cancel.")

        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}


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
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'MIXIE':
                    area.tag_redraw()

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
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'MIXIE':
                    area.tag_redraw()

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
    MIXIE_OT_moodboard_magic_select_tool,
    MIXIE_OT_toggle_segment,
    MIXIE_OT_delete_segment,
    MIXIE_OT_moodboard_upload_to_sam,
)
