# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Developer-only visual diagnostics for character-component masks."""

import os
import tempfile

import bpy

from ..constants import MOODBOARD_MULTI_IMAGE_GAP
from .moodboard_utils import (
    ensure_moodboard_region_visible,
    find_free_moodboard_position,
    get_moodboard_image_display_size,
)


def component_debug_enabled(scene) -> bool:
    """Return whether SAM3 mask artifacts should be exposed on the board."""
    try:
        from mixar.config.config import get_config

        config = get_config()
        if str(config.get("environment", "Prod")).lower() == "prod":
            return False
        if str(config.get("log_level", "INFO")).upper() == "DEBUG":
            return True
    except Exception:
        pass
    try:
        prefs = getattr(scene, "mixar_paint_preferences", None)
        return bool(prefs and prefs.developer_mode)
    except Exception:
        return False


def _add_mask_preview(scene, source_index, preview_image, segment_name, label):
    """Place one already-independent debug image beside its source."""
    if not component_debug_enabled(scene) or preview_image is None:
        return None
    if source_index < 0 or source_index >= len(scene.mixie_moodboard_images):
        return None

    source = scene.mixie_moodboard_images[source_index]
    preview_image.name = f"DEBUG {label} - {segment_name}"
    preview_image.pack()

    preview = scene.mixie_moodboard_images.add()
    preview.image = preview_image
    preview.scale = max(0.2, source.scale * 0.45)
    preview.selected = False
    preview.generation_prompt = f"Developer-only {label} preview"
    preview.component_role = 'DEBUG_MASK'
    preview.component_name = segment_name
    preview.z_order = max(
        (item.z_order for item in scene.mixie_moodboard_images),
        default=0,
    ) + 1

    source_width, source_height = get_moodboard_image_display_size(
        source.image, source.scale,
    )
    width, height = get_moodboard_image_display_size(
        preview.image, preview.scale,
    )
    center_x = source.position_x + source_width + MOODBOARD_MULTI_IMAGE_GAP + width / 2
    center_y = source.position_y + source_height - height / 2
    preview_index = len(scene.mixie_moodboard_images) - 1
    preview.position_x, preview.position_y = find_free_moodboard_position(
        width,
        height,
        center_x,
        center_y,
        scene=scene,
        exclude_index=preview_index,
    )
    ensure_moodboard_region_visible(
        preview.position_x, preview.position_y, width, height,
    )
    return preview


def add_sam3_mask_preview(
    scene, source_index, mask_image, segment_name, label="SAM3 Mask"
):
    """Add an independent black/white SAM3 mask beside its source in debug mode."""
    if not component_debug_enabled(scene) or mask_image is None:
        return None
    preview_image = None
    try:
        preview_image = mask_image.copy()
        return _add_mask_preview(
            scene, source_index, preview_image, segment_name, label,
        )
    except Exception:
        # Diagnostics must never turn a valid segmentation into a failure.
        if preview_image is not None:
            try:
                bpy.data.images.remove(preview_image)
            except Exception:
                pass
        return None


def add_mask_bytes_preview(scene, source_index, mask_bytes, segment_name, label):
    """Decode and place an exact encoded mask response in debug mode."""
    if not component_debug_enabled(scene) or not mask_bytes:
        return None
    temp_path = None
    image = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            handle.write(mask_bytes)
            temp_path = handle.name
        image = bpy.data.images.load(temp_path, check_existing=False)
        return _add_mask_preview(scene, source_index, image, segment_name, label)
    except Exception:
        if image is not None:
            try:
                bpy.data.images.remove(image)
            except Exception:
                pass
        return None
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
