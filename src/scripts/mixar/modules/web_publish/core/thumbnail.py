# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Best-effort share-card thumbnail (main thread).

A viewport render (``render.opengl``) of a VIEW_3D area showing the published
scene, from its WINDOW region. A thumbnail never fails or delays a publish:
it is SKIPPED while a window resize is in progress (a viewport render inside
the OS resize callback kills the app on macOS — see CLAUDE.md), while
another render holds the render coordinator, or when no window shows the
scene. Render settings are restored in ``finally``.
"""

from __future__ import annotations

import os
from typing import Optional

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.web_publish.constants import (
    THUMBNAIL_RENDER_OWNER,
    THUMBNAIL_RESOLUTION,
)

_logger = get_logger(__name__)

_IMAGE_KEYS = ("media_type", "file_format", "color_mode", "color_depth")


def _view3d_target(scene):
    """``(window, area, region)`` of a VIEW_3D showing ``scene``, or None."""
    wm = bpy.context.window_manager
    for window in getattr(wm, "windows", ()) or ():
        if window.scene != scene or window.screen is None:
            continue
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for region in area.regions:
                if region.type == 'WINDOW':
                    return window, area, region
    return None


def can_render_now() -> bool:
    wm = bpy.context.window_manager
    if getattr(wm, "mixar_window_resizing", False):
        return False
    try:
        from mixar.modules.common.render_coordinator import core as render_coordinator

        return not render_coordinator.busy()
    except Exception:  # noqa: BLE001 — coordinator unavailable: be conservative
        return False


def render_thumbnail(scene, filepath: str) -> Optional[str]:
    """Render the thumbnail to ``filepath``; None when skipped or failed."""
    if not can_render_now():
        _logger.info("web_publish thumbnail skipped (window resizing or render busy)")
        return None
    target = _view3d_target(scene)
    if target is None:
        _logger.info("web_publish thumbnail skipped (no 3D viewport shows the scene)")
        return None
    from mixar.modules.common.render_coordinator import core as render_coordinator

    window, area, region = target
    render = scene.render
    image = render.image_settings
    saved = {name: getattr(render, name) for name in
             ("resolution_x", "resolution_y", "resolution_percentage", "filepath",
              "use_file_extension")}
    saved_image = {key: getattr(image, key) for key in _IMAGE_KEYS if hasattr(image, key)}
    try:
        with render_coordinator.reserve(THUMBNAIL_RENDER_OWNER):
            render.resolution_x, render.resolution_y = THUMBNAIL_RESOLUTION
            render.resolution_percentage = 100
            render.filepath = filepath
            render.use_file_extension = False
            if hasattr(image, "media_type"):
                image.media_type = 'IMAGE'  # file_format is filtered by media type
            image.file_format = 'PNG'
            with bpy.context.temp_override(window=window, area=area, region=region,
                                           scene=scene):
                bpy.ops.render.opengl(write_still=True, view_context=True)
    except Exception as exc:  # noqa: BLE001 — thumbnails are best-effort
        _logger.warning("web_publish thumbnail render failed: %s", exc)
        return None
    finally:
        _restore(render, saved, image, saved_image)
    if os.path.isfile(filepath) and os.path.getsize(filepath) > 0:
        return filepath
    return None


def _restore(render, saved: dict, image, saved_image: dict) -> None:
    for name, value in saved.items():
        try:
            setattr(render, name, value)
        except (AttributeError, RuntimeError, TypeError):
            pass
    # Blender filters file_format by media_type: restore in _IMAGE_KEYS order.
    for key in _IMAGE_KEYS:
        if key in saved_image:
            try:
                setattr(image, key, saved_image[key])
            except (AttributeError, RuntimeError, TypeError):
                pass
