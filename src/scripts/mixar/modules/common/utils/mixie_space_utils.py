# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared utilities for MIXIE space type detection and moodboard helpers."""

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


# Cached module-level check for MIXIE space type availability.
# Used by all moodboard UI files to guard class registration and poll methods.
try:
    MIXIE_SPACE_AVAILABLE = 'MIXIE' in [
        item.identifier
        for item in bpy.types.Panel.bl_rna.properties['bl_space_type'].enum_items
    ]
except (TypeError, KeyError):
    MIXIE_SPACE_AVAILABLE = False


def show_generation_error(scene, prefix, message, generating_attr, error_attr):
    """Schedule error display on the main thread (safe to call from background threads).

    Args:
        scene: The Blender scene.
        prefix: Feature name for the popup title (e.g. "Image Gen").
        message: Error message to display.
        generating_attr: Scene bool property to set False
            (e.g. "mixie_imagegen_is_generating").
        error_attr: Scene string property to store the message.
    """
    logger.error("[%s] %s", prefix, message)

    def _show():
        try:
            if hasattr(scene, generating_attr):
                setattr(scene, generating_attr, False)
            if hasattr(scene, error_attr):
                setattr(scene, error_attr, message)

            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'MIXIE':
                        area.tag_redraw()

            def draw_error(self_inner, context):
                self_inner.layout.label(text=message)

            bpy.context.window_manager.popup_menu(
                draw_error, title=f"{prefix} Error", icon='ERROR'
            )
        except Exception:
            pass
        return None

    bpy.app.timers.register(_show, first_interval=0)


def count_selected_moodboard_images(scene):
    """Return the number of selected images on the moodboard."""
    if not hasattr(scene, 'mixie_moodboard_images'):
        return 0
    return sum(1 for img in scene.mixie_moodboard_images if img.selected)


def get_first_selected_moodboard_image(scene):
    """Return the first selected moodboard image datablock, or None."""
    if hasattr(scene, 'mixie_moodboard_images'):
        for item in scene.mixie_moodboard_images:
            if item.selected and item.image:
                return item.image
    return None


def get_selected_moodboard_items(scene):
    """Return counts of selected moodboard items.

    Returns:
        Tuple of (images, textboxes, groups).
    """
    images = (
        sum(1 for img in scene.mixie_moodboard_images if img.selected)
        if hasattr(scene, 'mixie_moodboard_images') else 0
    )
    textboxes = (
        sum(1 for tb in scene.mixie_moodboard_textboxes if tb.selected)
        if hasattr(scene, 'mixie_moodboard_textboxes') else 0
    )
    groups = (
        sum(1 for grp in scene.mixie_moodboard_groups if grp.selected)
        if hasattr(scene, 'mixie_moodboard_groups') else 0
    )
    return (images, textboxes, groups)


def redraw_mixie_areas() -> None:
    """Tag all MIXIE areas for redraw. Safe to call from timer callbacks."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'MIXIE':
                    area.tag_redraw()
    except Exception as e:
        logger.debug("redraw_mixie_areas error: %s", e)
