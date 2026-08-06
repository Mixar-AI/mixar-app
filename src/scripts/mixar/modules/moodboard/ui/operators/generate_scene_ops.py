# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Generate Scene Operators

Operators for generating 3D scenes from segmented images using Scene Generation API.
"""

import os
import tempfile
from typing import List, Optional

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.moodboard.core.media_utils import is_still_item

logger = get_logger(__name__)


def _write_temp_glb(glb_bytes: bytes, name: str) -> str:
    """Write GLB bytes to temp file and return path."""
    import datetime
    temp_dir = os.path.join(tempfile.gettempdir(), 'mixar_scenegen')
    os.makedirs(temp_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(temp_dir, f"{name}_{timestamp}.glb")
    with open(path, 'wb') as f:
        f.write(glb_bytes)
    return path


def import_glb_object(glb_bytes: bytes, pose_data: Optional[dict], object_id: int) -> List:
    """
    Import GLB bytes into Blender with pose transform.

    Uses scene_importer for proper pose transforms including:
    - Z offset running average
    - Quaternion with negated W component
    - Camera auto-adjustment

    Args:
        glb_bytes: Raw GLB file content from download API
        pose_data: Dict from API with keys:
            - quaternion: {w, x, y, z}
            - rotation_matrix: 3x3 list
            - translation: [x, y, z]
            - scale: float
        object_id: Object index from job status

    Returns:
        List of imported Blender objects (single object in list)
    """
    from ...core.scene_importer import init_scene, add_object, is_scene_initialized

    try:
        # Initialize scene on first object
        if object_id == 0 or not is_scene_initialized():
            init_scene(clear_existing=True)

        # Add object with pose transform
        imported_obj = add_object(
            glb_bytes=glb_bytes,
            pose_data=pose_data,
            object_id=object_id,
        )

        # Trigger viewport redraw
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()

        return [imported_obj] if imported_obj else []

    except Exception as e:
        logger.error("[SceneGen] Failed to import GLB: %s", e, exc_info=True)
        return []


# ============================================================================
# Legacy SAM 3D functions (kept for backwards compatibility)
# ============================================================================

def _import_glb_bytes(glb_bytes: bytes, name: str = "sam3d_model"):
    """Import GLB bytes into Blender and return imported objects."""
    try:
        temp_path = _write_temp_glb(glb_bytes, name)
        logger.debug("[SAM3D] Saved GLB to temp file")
        bpy.ops.import_scene.gltf(filepath=temp_path)
        imported_objects = list(bpy.context.selected_objects)
        logger.debug("[SAM3D] Successfully imported GLB: %s (%s objects)", name, len(imported_objects))
        return imported_objects
    except Exception as e:
        logger.error("[SAM3D] Failed to import GLB: %s", e, exc_info=True)
        return []


def _apply_transforms(obj, obj_data):
    """Apply location, scale, and rotation from scene.json data."""
    location = obj_data.get('blender_location', [0, 0, 0])
    scale_val = obj_data.get('blender_scale', [1, 1, 1])
    rotation_quat = obj_data.get('blender_rotation_quaternion', None)

    logger.debug("[SAM3D] Applying transforms to %s", obj.name)

    temp = location[1]
    location[1] = -location[2]
    location[2] = temp

    obj.location = location
    obj.scale = scale_val

    if rotation_quat and len(rotation_quat) == 4:
        obj.rotation_mode = 'QUATERNION'
        obj.rotation_quaternion = [0, 0, 0, 1]


def _import_zip_scene(zip_bytes: bytes) -> bool:
    """Extract ZIP, parse scene.json, import GLBs with positions."""
    import zipfile
    import json
    import io
    import datetime

    try:
        downloads_dir = os.path.join(os.path.expanduser("~"), "Downloads", "mixar_sam3d")
        os.makedirs(downloads_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = os.path.join(downloads_dir, f"sam3d_scene_{timestamp}.zip")
        with open(zip_path, 'wb') as f:
            f.write(zip_bytes)
        logger.debug("[SAM3D] Saved ZIP to temp file")

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            scene_data = None
            objects_data = {}
            if 'scene.json' in zf.namelist():
                scene_data = json.loads(zf.read('scene.json'))
                logger.debug("[SAM3D] Found scene.json")
                if isinstance(scene_data, list):
                    for obj_data in scene_data:
                        filename = obj_data.get('filename', '')
                        if filename:
                            objects_data[filename] = obj_data
                elif isinstance(scene_data, dict) and 'objects' in scene_data:
                    for obj_data in scene_data['objects']:
                        filename = obj_data.get('filename', '')
                        if filename:
                            objects_data[filename] = obj_data

            imported_count = 0
            for filename in zf.namelist():
                if filename.endswith('.glb'):
                    glb_bytes = zf.read(filename)
                    obj_name = filename[:-4]
                    imported_objects = _import_glb_bytes(glb_bytes, obj_name)

                    if imported_objects:
                        imported_count += 1
                        obj_data = objects_data.get(filename, {})
                        if obj_data:
                            for obj in imported_objects:
                                _apply_transforms(obj, obj_data)

            logger.debug("[SAM3D] Imported %s GLB(s) from ZIP", imported_count)
            return imported_count > 0

    except Exception as e:
        logger.error("[SAM3D] Failed to import ZIP scene: %s", e, exc_info=True)
        return False


# ============================================================================
# Operators
# ============================================================================

class MIXIE_OT_generate_scene(Operator):
    """Generate 3D scene from active segments using Scene Generation API"""
    bl_idname = "mixie.generate_scene"
    bl_label = "Generate Scene"
    bl_options = {'REGISTER'}

    def execute(self, context):
        from mixar.modules.common.utils.image_utils import image_to_png_bytes, compress_image_for_upload
        from ...core.scene_gen_manager import get_scene_gen_manager

        scene = context.scene

        # Find selected image with segments
        img_item = None
        for item in scene.mixie_moodboard_images:
            if item.selected and is_still_item(item):
                img_item = item
                break

        if not img_item:
            self.report({'ERROR'}, "No image selected")
            return {'CANCELLED'}

        if not img_item.image:
            self.report({'ERROR'}, "Selected item has no image")
            return {'CANCELLED'}

        # Check if already generating
        manager = get_scene_gen_manager()
        if manager.is_generating(img_item.image.name):
            self.report({'WARNING'}, "Generation already in progress for this image")
            return {'CANCELLED'}

        # Collect active segment masks
        mask_bytes_list = []
        for segment in img_item.segments:
            if segment.active and segment.mask_image:
                try:
                    mask_bytes = image_to_png_bytes(segment.mask_image)
                    mask_bytes_list.append(mask_bytes)
                except Exception as e:
                    logger.error("[SceneGen] Failed to convert mask: %s", e)

        if not mask_bytes_list:
            self.report({'ERROR'}, "No active segments with masks")
            return {'CANCELLED'}

        # Use compressed image if available, otherwise use original
        source_image = img_item.compressed_image if img_item.compressed_image else img_item.image
        try:
            image_bytes = compress_image_for_upload(source_image)
            logger.debug("[SceneGen] Using image: %sx%s (%s)", source_image.size[0], source_image.size[1], 'compressed' if img_item.compressed_image else 'original')
        except Exception as e:
            self.report({'ERROR'}, f"Failed to convert image: {e}")
            return {'CANCELLED'}

        num_masks = len(mask_bytes_list)
        self.report({'INFO'}, f"Generating 3D scene from {num_masks} segment(s)...")

        # Submit job via manager
        manager.submit_job(
            img_item=img_item,
            image_bytes=image_bytes,
            mask_bytes_list=mask_bytes_list,
            on_object_ready=import_glb_object,
        )

        from mixar.modules.common.job_queue.constants import FEATURE_SCENE_GEN
        from mixar.modules.common.job_queue.ui.lists.queue_uilist import mark_enqueued
        mark_enqueued(FEATURE_SCENE_GEN)

        return {'FINISHED'}


classes = (
    MIXIE_OT_generate_scene,
)
