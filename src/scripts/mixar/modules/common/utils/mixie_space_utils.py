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
except (AttributeError, TypeError, KeyError):
    # AttributeError covers the standalone pytest suite: mock_bpy installs a
    # plain `type("Panel", (), {})` with no bl_rna, so this import — which
    # every moodboard/queue UI module pulls in transitively — raised at
    # collection time and interrupted the whole run.
    MIXIE_SPACE_AVAILABLE = False


def show_generation_error(scene, prefix, message, generating_attr, error_attr):
    """Schedule error display on the main thread (safe to call from background threads).

    The error is raised as a viewport notification (bottom-left toast lane),
    like every other alert — not as a popup menu under the cursor.

    Args:
        scene: The Blender scene.
        prefix: Feature name for the notification title (e.g. "Image Gen").
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
        except Exception:
            pass
        push_error_notification(f"{prefix} failed", message)
        return None

    bpy.app.timers.register(_show, first_interval=0)


def push_error_notification(title, message):
    """Raise a sticky error toast in the viewport notification lane."""
    try:
        from mixar.modules.common.notifications import get_notification_store
        get_notification_store().push(
            "error", title, body=message, priority="high",
        )
    except Exception as e:  # noqa: BLE001 — the log line above still records it
        logger.debug("error notification failed: %s", e)


def count_selected_moodboard_images(scene):
    """Return the number of selected stills, including selected node results."""
    from mixar.modules.moodboard.core.media_utils import selected_reference_stills

    return len(selected_reference_stills(scene))


def get_first_selected_moodboard_image(scene):
    """Return the first selected still datablock, including node results."""
    from mixar.modules.moodboard.core.media_utils import first_selected_reference_still

    return first_selected_reference_still(scene)


def get_selected_moodboard_items(scene):
    """Return counts of selected moodboard items.

    Returns:
        Tuple of (images, textboxes, frames).
    """
    images = (
        sum(1 for img in scene.mixie_moodboard_images if img.selected)
        if hasattr(scene, 'mixie_moodboard_images') else 0
    )
    textboxes = (
        sum(1 for tb in scene.mixie_moodboard_textboxes if tb.selected)
        if hasattr(scene, 'mixie_moodboard_textboxes') else 0
    )
    frames = (
        sum(1 for frame in scene.mixie_moodboard_frames if frame.selected)
        if hasattr(scene, 'mixie_moodboard_frames') else 0
    )
    return (images, textboxes, frames)


def redraw_mixie_areas() -> None:
    """Tag all MIXIE areas for redraw. Safe to call from timer callbacks."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'MIXIE':
                    area.tag_redraw()
    except Exception as e:
        logger.debug("redraw_mixie_areas error: %s", e)
