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


def recomposite_display_image(img_item):
    """
    Composite all active segments onto the original image.
    Creates or updates img_item.display_image with overlays applied.
    Adds a darker green outline around segment edges.
    Uses NumPy (bundled with Blender) for fast vectorized operations.
    """
    import numpy as np

    original = img_item.image
    if not original:
        return

    width, height = original.size[0], original.size[1]
    if width == 0 or height == 0:
        return

    # Check if any segments are active
    has_active_segments = any(seg.active for seg in img_item.segments)

    if not has_active_segments:
        # No active segments - clear display image so original is shown
        if img_item.display_image:
            old_display = img_item.display_image
            img_item.display_image = None
            try:
                bpy.data.images.remove(old_display)
            except:
                pass
        return

    # Fast pixel access using foreach_get
    pixel_count = width * height * 4
    original_pixels = np.empty(pixel_count, dtype=np.float32)
    original.pixels.foreach_get(original_pixels)
    result_pixels = original_pixels.copy().reshape(height, width, 4)

    theme_green = np.array([0.2, 0.8, 0.2], dtype=np.float32)
    outline_green = np.array([0.1, 0.5, 0.1], dtype=np.float32)
    overlay_alpha = 0.5

    # Apply each active segment
    for segment in img_item.segments:
        if not segment.active or not segment.mask_image:
            continue

        mask_img = segment.mask_image
        mask_width, mask_height = mask_img.size[0], mask_img.size[1]

        if mask_width == 0 or mask_height == 0:
            continue

        # Fast mask pixel access
        mask_pixel_count = mask_width * mask_height * 4
        mask_pixels = np.empty(mask_pixel_count, dtype=np.float32)
        mask_img.pixels.foreach_get(mask_pixels)
        mask_pixels = mask_pixels.reshape(mask_height, mask_width, 4)
        mask_r = mask_pixels[:, :, 0]

        # Resize mask if needed using nearest neighbor
        if mask_width != width or mask_height != height:
            y_indices = (np.arange(height) * mask_height / height).astype(int)
            x_indices = (np.arange(width) * mask_width / width).astype(int)
            mask_r = mask_r[y_indices][:, x_indices]

        # Create binary mask
        mask_bool = mask_r > 0.5

        # Simple edge detection: shift mask and XOR to find boundaries
        edge_mask = np.zeros_like(mask_bool)
        edge_mask[1:, :] |= mask_bool[1:, :] != mask_bool[:-1, :]  # vertical edges
        edge_mask[:-1, :] |= mask_bool[1:, :] != mask_bool[:-1, :]
        edge_mask[:, 1:] |= mask_bool[:, 1:] != mask_bool[:, :-1]  # horizontal edges
        edge_mask[:, :-1] |= mask_bool[:, 1:] != mask_bool[:, :-1]
        edge_mask = edge_mask & mask_bool  # Only edges inside mask

        # Apply green overlay to interior (mask minus edges)
        interior = mask_bool & ~edge_mask
        result_pixels[interior, :3] = (
            result_pixels[interior, :3] * (1 - overlay_alpha) +
            theme_green * overlay_alpha
        )

        # Apply darker green to edges
        result_pixels[edge_mask, :3] = (
            result_pixels[edge_mask, :3] * 0.3 +
            outline_green * 0.7
        )

    # Create or update display image
    if not img_item.display_image:
        display_name = f"{original.name}_display"
        img_item.display_image = bpy.data.images.new(
            name=display_name,
            width=width,
            height=height,
            alpha=True
        )

    # Fast pixel write using foreach_set
    img_item.display_image.pixels.foreach_set(result_pixels.flatten())
    img_item.display_image.pack()


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
                    if img.selected and img.image]
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

        # Surface the Scene Gen tab's Segments to 3D mode
        from ..sidebar_ui_helpers import focus_scene_gen_segments
        focus_scene_gen_segments(context)

        # Find the selected image
        selected_idx = -1
        for i, img in enumerate(scene.mixie_moodboard_images):
            if img.selected and img.image:
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

        if manager.is_uploading(image):
            self.report({'INFO'}, "Image is uploading... Please wait")
            self._upload_pending = True
        elif not manager.is_ready(image):
            # Upload image first
            self.report({'INFO'}, "Uploading image for segmentation...")
            self._upload_pending = True

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
