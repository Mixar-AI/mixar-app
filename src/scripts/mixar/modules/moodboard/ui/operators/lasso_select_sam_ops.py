# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Lasso Select SAM Integration Operators

Operators for triggering SAM mask refinement after lasso selection.
"""

import tempfile
import os

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

from ...constants import LASSO_MIN_POINTS
from ...core.scene_segment_manager import get_scene_segment_manager
from ...core.segment_overlay import recomposite_display_image


def _redraw_all():
    """Trigger redraw of all MIXIE areas."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'MIXIE':
                area.tag_redraw()


def _reset_lasso_state(state):
    """Reset lasso selection state."""
    state.lasso_points.clear()
    state.lasso_loops.clear()
    state.lasso_select_has_selection = False
    state.lasso_select_pending = False
    state.active_tool = 'NONE'
    state.target_image_index = -1


def _create_segment_from_mask(scene, image_index, mask_bytes, base_name):
    """Add segment to image's segment collection and recomposite."""
    mask_temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='_mask.png', delete=False) as f:
            f.write(mask_bytes)
            mask_temp_path = f.name

        mask_img = bpy.data.images.load(mask_temp_path, check_existing=False)

        if mask_img.size[0] == 0 or mask_img.size[1] == 0:
            bpy.data.images.remove(mask_img)
            logger.error("[LassoSelectSAM] Invalid mask dimensions")
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
        logger.debug("[LassoSelectSAM] Added %s", segment_name)
        return True

    except Exception as e:
        logger.error("[LassoSelectSAM] Failed to create segment: %s", e)
        return False
    finally:
        if mask_temp_path:
            try:
                os.unlink(mask_temp_path)
            except OSError:
                pass



def _create_mask_from_polygon(width, height, points):
    """
    Create binary mask from polygon points using scanline algorithm.
    Points are normalized (0-1), mask is height x width.
    Returns numpy array with 1.0 for inside, 0.0 for outside.
    """
    import numpy as np

    # Scale points to pixel coordinates
    pixel_points = [(p[0] * width, p[1] * height) for p in points]

    mask = np.zeros((height, width), dtype=np.float32)

    # Scanline fill algorithm for efficiency
    # Get bounding box
    xs = [p[0] for p in pixel_points]
    ys = [p[1] for p in pixel_points]
    min_y = max(0, int(min(ys)))
    max_y = min(height - 1, int(max(ys)))

    for y in range(min_y, max_y + 1):
        # Find intersections with polygon edges
        intersections = []
        n = len(pixel_points)
        for i in range(n):
            p1x, p1y = pixel_points[i]
            p2x, p2y = pixel_points[(i + 1) % n]

            if p1y == p2y:
                continue

            if min(p1y, p2y) <= y < max(p1y, p2y):
                # Calculate x intersection
                x_intersect = p1x + (y - p1y) * (p2x - p1x) / (p2y - p1y)
                intersections.append(x_intersect)

        # Sort intersections and fill between pairs
        intersections.sort()
        for i in range(0, len(intersections) - 1, 2):
            x_start = max(0, int(intersections[i]))
            x_end = min(width - 1, int(intersections[i + 1]))
            mask[y, x_start:x_end + 1] = 1.0

    return mask


def _export_mask_as_png(mask_array, width, height):
    """
    Export numpy mask array as PNG bytes.
    Returns PNG bytes or None on error.
    """
    import numpy as np

    mask_temp_path = None
    mask_img = None
    try:
        # Create temporary Blender image for mask
        mask_img = bpy.data.images.new(
            name="_temp_lasso_mask",
            width=width,
            height=height,
            alpha=False
        )

        # Set pixels (grayscale mask as RGB)
        pixels = np.zeros((height, width, 4), dtype=np.float32)
        pixels[:, :, 0] = mask_array  # R
        pixels[:, :, 1] = mask_array  # G
        pixels[:, :, 2] = mask_array  # B
        pixels[:, :, 3] = 1.0  # A

        mask_img.pixels.foreach_set(pixels.flatten())

        # Save to temp file using image.save() — save_render() reads format from
        # scene render settings (ignoring image.file_format) and may save EXR/JPEG
        # instead of PNG depending on the user's render output configuration.
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            mask_temp_path = f.name

        mask_img.file_format = 'PNG'
        mask_img.filepath_raw = mask_temp_path
        mask_img.save()

        # Read bytes
        with open(mask_temp_path, 'rb') as f:
            mask_bytes = f.read()

        return mask_bytes

    except Exception as e:
        logger.error("[LassoSelectSAM] Failed to export mask: %s", e)
        return None
    finally:
        if mask_temp_path:
            try:
                os.unlink(mask_temp_path)
            except OSError:
                pass
        if mask_img is not None:
            try:
                bpy.data.images.remove(mask_img)
            except Exception:
                pass


def _get_upload_dimensions(img_item):
    """
    Return the (width, height) of the image as uploaded to the backend.

    The backend receives a possibly-resized (compressed) version of the image.
    The mask must match these dimensions so the backend can apply it correctly.
    If a compressed image is available it represents the uploaded size; otherwise
    the original image dimensions are used (image was small enough to skip resize).
    """
    try:
        if (img_item.compressed_image and
                len(img_item.compressed_image.size) >= 2 and
                img_item.compressed_image.size[0] > 0):
            return img_item.compressed_image.size[0], img_item.compressed_image.size[1]
    except Exception:
        pass
    return img_item.image.size[0], img_item.image.size[1]


def _build_lasso_mask(img_item, points):
    """
    Create and export the lasso mask at the correct dimensions for the backend.

    The mask must have the same width/height as the image that was uploaded to
    the scene-segment API, which may differ from the original image when it was
    resized during compression.  Using mismatched dimensions causes the backend
    to ignore the mask and segment the entire scene (issue #506).

    Args:
        img_item: MixieMoodboardImageItem with image and optional compressed_image
        points: List of (x, y) normalized lasso polygon points

    Returns:
        PNG bytes for the mask, or None on error.
    """
    width, height = _get_upload_dimensions(img_item)
    mask_array = _create_mask_from_polygon(width, height, points)
    return _export_mask_as_png(mask_array, width, height)


class MIXIE_OT_lasso_select_sam(Operator):
    """Refine lasso selection using SAM"""
    bl_idname = "mixie.lasso_select_sam"
    bl_label = "Refine Selection"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if not hasattr(context.scene, 'mixie_edit_tool_state'):
            return False
        state = context.scene.mixie_edit_tool_state
        return (state.lasso_select_has_selection and
                not state.lasso_select_pending and
                state.target_image_index >= 0 and
                (
                    len(state.lasso_loops) > 0
                    or len(state.lasso_points) >= LASSO_MIN_POINTS
                ))

    def execute(self, context):
        scene = context.scene
        state = scene.mixie_edit_tool_state

        if state.target_image_index < 0:
            self.report({'ERROR'}, "No target image")
            return {'CANCELLED'}

        if state.target_image_index >= len(scene.mixie_moodboard_images):
            self.report({'ERROR'}, "Invalid image index")
            _reset_lasso_state(state)
            return {'CANCELLED'}

        img_item = scene.mixie_moodboard_images[state.target_image_index]
        if not img_item.image:
            self.report({'ERROR'}, "Invalid image")
            _reset_lasso_state(state)
            return {'CANCELLED'}

        # Read all completed loops. Keep the single-loop fallback for files
        # created before multi-loop capture was introduced.
        loops = [
            [(point.x, point.y) for point in loop.points]
            for loop in state.lasso_loops
            if len(loop.points) >= LASSO_MIN_POINTS
        ]
        if not loops and len(state.lasso_points) >= LASSO_MIN_POINTS:
            loops = [[(p.x, p.y) for p in state.lasso_points]]
        if not loops:
            self.report({'ERROR'}, "No valid lasso loops")
            _reset_lasso_state(state)
            return {'CANCELLED'}

        manager = get_scene_segment_manager()

        # Check if image is uploaded
        if not manager.is_ready(img_item.image):
            if manager.is_uploading(img_item.image):
                self.report({'INFO'}, "Image is uploading, please wait...")
                return {'CANCELLED'}

            # Queue upload first — capture lasso points before the async callback
            state.lasso_select_pending = True
            self.report({'INFO'}, "Uploading image for refinement...")

            target_idx = state.target_image_index
            # Capture loops now so the closure has stable copies.
            captured_loops = [list(loop) for loop in loops]

            def on_upload_complete(success, message):
                if success:
                    # Re-fetch img_item inside callback in case the collection
                    # changed while the upload was in flight.
                    current_img_item = scene.mixie_moodboard_images[target_idx]
                    mask_bytes = [
                        _build_lasso_mask(current_img_item, loop)
                        for loop in captured_loops
                    ]
                    if all(mask_bytes):
                        _perform_mask_segmentations(scene, target_idx, mask_bytes)
                    else:
                        _reset_lasso_state(state)
                        logger.error("[LassoSelectSAM] Failed to create mask after upload")
                else:
                    _reset_lasso_state(state)
                    logger.error("[LassoSelectSAM] Upload failed: %s", message)
                _redraw_all()

            manager.queue_upload(img_item.image, img_item=img_item,
                                 on_complete=on_upload_complete)
            _redraw_all()
            return {'FINISHED'}

        # Image already uploaded — create mask at the correct (compressed) dimensions
        # so it matches what the backend has stored for this job.
        mask_bytes = [_build_lasso_mask(img_item, loop) for loop in loops]
        if not all(mask_bytes):
            self.report({'ERROR'}, "Failed to create one or more lasso masks")
            _reset_lasso_state(state)
            return {'CANCELLED'}

        # Image ready, process loops sequentially. Each completed SAM3 result
        # is inserted immediately, so a long batch remains visibly progressive.
        _perform_mask_segmentations(scene, state.target_image_index, mask_bytes)
        return {'FINISHED'}


def _perform_mask_segmentations(scene, target_idx, masks, index=0, _retry=False):
    """Refine loops one at a time and add each returned mask immediately."""
    state = scene.mixie_edit_tool_state

    if index >= len(masks):
        _reset_lasso_state(state)
        _redraw_all()
        return

    def on_complete(success: bool, refined_mask_bytes, message: str):
        if success and refined_mask_bytes:
            _create_segment_from_mask(
                scene, target_idx, refined_mask_bytes, "Lasso Segment"
            )
            # Continue only after the current result is visible on the board.
            _perform_mask_segmentations(scene, target_idx, masks, index + 1)
            return

        error_msg = message or "Unknown error"
        if error_msg == "expired" and not _retry:
            logger.error("[LassoSelectSAM] Job expired, re-uploading and retrying...")
            _upload_and_retry_lasso(scene, target_idx, masks, index)
            return
        elif "402" in error_msg or "credit" in error_msg.lower():
            logger.error("[LassoSelectSAM] Insufficient credits for segmentation")
        elif "no object" in error_msg.lower() or "empty" in error_msg.lower():
            logger.warning("[LassoSelectSAM] No object detected in lasso region")
        else:
            logger.error("[LassoSelectSAM] Refinement failed: %s", error_msg)

        # A failed loop should not prevent later loops from appearing.
        _perform_mask_segmentations(scene, target_idx, masks, index + 1)

    img_item = scene.mixie_moodboard_images[target_idx]
    manager = get_scene_segment_manager()
    state.lasso_select_pending = True
    manager.request_mask_segmentation(
        image=img_item.image,
        mask_bytes=masks[index],
        on_complete=on_complete
    )

    _redraw_all()


def _upload_and_retry_lasso(scene, target_idx, masks, index):
    """Re-upload image and retry lasso segmentation after expiry."""
    state = scene.mixie_edit_tool_state
    img_item = scene.mixie_moodboard_images[target_idx]
    manager = get_scene_segment_manager()

    def on_upload_complete(success, message):
        if success:
            _perform_mask_segmentations(
                scene, target_idx, masks, index=index, _retry=True
            )
        else:
            logger.debug("[LassoSelectSAM] Re-upload failed: %s", message)
            _reset_lasso_state(state)
            _redraw_all()

    manager.queue_upload(img_item.image, img_item=img_item,
                         on_complete=on_upload_complete)


classes = (
    MIXIE_OT_lasso_select_sam,
)
