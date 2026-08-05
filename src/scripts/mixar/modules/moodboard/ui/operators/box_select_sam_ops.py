# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Box Select SAM Integration Operators

Operators for triggering SAM box segmentation after box selection.
"""

import tempfile
import os

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.scene_segment_manager import get_scene_segment_manager
from ...core.segment_overlay import recomposite_display_image


def _redraw_all():
    """Trigger redraw of all MIXIE areas."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()


def _reset_box_state(state):
    """Reset box selection state."""
    state.box_start_x = 0.0
    state.box_start_y = 0.0
    state.box_end_x = 1.0
    state.box_end_y = 1.0
    state.box_select_has_selection = False
    state.box_select_pending = False
    state.active_tool = 'NONE'
    state.target_image_index = -1


def _create_segment_from_mask(image_index, mask_bytes, base_name):
    """Add segment to image's segment collection and recomposite."""
    scene = bpy.context.scene

    mask_temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='_mask.png', delete=False) as f:
            f.write(mask_bytes)
            mask_temp_path = f.name

        mask_img = bpy.data.images.load(mask_temp_path, check_existing=False)

        if mask_img.size[0] == 0 or mask_img.size[1] == 0:
            bpy.data.images.remove(mask_img)
            logger.error("[BoxSelectSAM] Invalid mask dimensions")
            return False

        img_item = scene.mixie_moodboard_images[image_index]
        next_index = len(img_item.segments) + 1
        segment_name = f"{base_name} {next_index}"

        mask_img.name = f"{img_item.image.name}_{segment_name}_mask"
        mask_img.pack()

        segment = img_item.segments.add()
        segment.mask_image = mask_img
        segment.active = True
        segment.index = next_index
        segment.name = segment_name

        recomposite_display_image(img_item)
        from ...core.component_debug import add_sam3_mask_preview

        add_sam3_mask_preview(scene, image_index, mask_img, segment_name)
        logger.debug("[BoxSelectSAM] Added %s", segment_name)
        return True

    except Exception as e:
        logger.error("[BoxSelectSAM] Failed to create segment: %s", e)
        return False
    finally:
        if mask_temp_path:
            try:
                os.unlink(mask_temp_path)
            except OSError:
                pass


class MIXIE_OT_box_select_sam(Operator):
    """Identify and select objects within box using SAM"""
    bl_idname = "mixie.box_select_sam"
    bl_label = "Identify and Select"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if not hasattr(context.scene, 'mixie_edit_tool_state'):
            return False
        state = context.scene.mixie_edit_tool_state
        # Must have valid box selection and not already processing
        return (state.box_select_has_selection and
                not state.box_select_pending and
                state.target_image_index >= 0)

    def execute(self, context):
        scene = context.scene
        state = scene.mixie_edit_tool_state

        if state.target_image_index < 0:
            self.report({'ERROR'}, "No target image")
            return {'CANCELLED'}

        if state.target_image_index >= len(scene.mixie_moodboard_images):
            self.report({'ERROR'}, "Invalid image index")
            _reset_box_state(state)
            return {'CANCELLED'}

        img_item = scene.mixie_moodboard_images[state.target_image_index]
        if not img_item.image:
            self.report({'ERROR'}, "Invalid image")
            _reset_box_state(state)
            return {'CANCELLED'}

        manager = get_scene_segment_manager()

        # Check if image is uploaded
        if not manager.is_ready(img_item.image):
            # Queue upload first
            state.box_select_pending = True
            if manager.is_uploading(img_item.image):
                self.report({'INFO'}, "Waiting for image upload...")
            else:
                self.report({'INFO'}, "Uploading image for segmentation...")

            target_idx = state.target_image_index
            x1 = min(state.box_start_x, state.box_end_x)
            y1 = min(state.box_start_y, state.box_end_y)
            x2 = max(state.box_start_x, state.box_end_x)
            y2 = max(state.box_start_y, state.box_end_y)

            def on_upload_complete(success, message):
                if success:
                    _perform_box_segmentation(target_idx, x1, y1, x2, y2)
                else:
                    state.box_select_pending = False
                    logger.error("[BoxSelectSAM] Upload failed: %s", message)
                _redraw_all()

            manager.queue_upload(img_item.image, img_item=img_item,
                                 on_complete=on_upload_complete)
            _redraw_all()
            return {'FINISHED'}

        # Image ready, perform segmentation directly
        _perform_box_segmentation_from_state(context, state, img_item)
        return {'FINISHED'}


def _perform_box_segmentation_from_state(context, state, img_item):
    """Extract box coords from state and perform segmentation."""
    x1 = min(state.box_start_x, state.box_end_x)
    y1 = min(state.box_start_y, state.box_end_y)
    x2 = max(state.box_start_x, state.box_end_x)
    y2 = max(state.box_start_y, state.box_end_y)
    target_idx = state.target_image_index

    _perform_box_segmentation(target_idx, x1, y1, x2, y2)


def _perform_box_segmentation(target_idx, x1, y1, x2, y2, _retry=False):
    """Request box segmentation from SAM API."""
    scene = bpy.context.scene
    state = scene.mixie_edit_tool_state

    state.box_select_pending = True

    # API uses y=0 at top, Blender uses y=0 at bottom
    # Invert Y coordinates for API
    api_y1 = 1.0 - y2  # Top becomes bottom
    api_y2 = 1.0 - y1  # Bottom becomes top

    box = {
        "x_min": x1,
        "y_min": api_y1,
        "x_max": x2,
        "y_max": api_y2
    }

    def on_complete(success: bool, mask_bytes, message: str):
        if success and mask_bytes:
            _create_segment_from_mask(target_idx, mask_bytes, "Box Segment")
        else:
            error_msg = message or "Unknown error"
            if error_msg == "expired" and not _retry:
                logger.error("[BoxSelectSAM] Job expired, re-uploading and retrying...")
                _upload_and_retry_box(target_idx, x1, y1, x2, y2)
                return
            elif "402" in error_msg or "credit" in error_msg.lower():
                logger.error("[BoxSelectSAM] Insufficient credits for segmentation")
            elif "no object" in error_msg.lower() or "empty" in error_msg.lower():
                logger.warning("[BoxSelectSAM] No object detected in box region")
            else:
                logger.error("[BoxSelectSAM] Segmentation failed: %s", error_msg)

        # Reset state
        _reset_box_state(state)
        _redraw_all()

    img_item = scene.mixie_moodboard_images[target_idx]
    manager = get_scene_segment_manager()
    manager.request_box_segmentation(
        image=img_item.image,
        box=box,
        on_complete=on_complete
    )

    _redraw_all()


def _upload_and_retry_box(target_idx, x1, y1, x2, y2):
    """Re-upload image and retry box segmentation after expiry."""
    scene = bpy.context.scene
    img_item = scene.mixie_moodboard_images[target_idx]
    manager = get_scene_segment_manager()

    def on_upload_complete(success, message):
        if success:
            _perform_box_segmentation(target_idx, x1, y1, x2, y2, _retry=True)
        else:
            logger.warning("[BoxSelectSAM] Re-upload failed: %s", message)
            state = scene.mixie_edit_tool_state
            _reset_box_state(state)
            _redraw_all()

    manager.queue_upload(img_item.image, img_item=img_item,
                         on_complete=on_upload_complete)


classes = (
    MIXIE_OT_box_select_sam,
)
