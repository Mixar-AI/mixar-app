# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Capture the live 3D viewport as a moodboard still.

Higgsfield's prerender sends the OpenGL view into image-edit. Mixar already
has moodboard-selected stills as the gen-tab reference, so the capture lands
on the board (selected, others deselected) and existing "Use Selected
Moodboard Image" paths pick it up. No new job type.
"""

from __future__ import annotations

import os
import tempfile
import uuid


def find_view3d_context(context):
    """Return ``(window, area, window_region, space)`` for a 3D viewport."""
    current_area = getattr(context, "area", None)
    current_window = getattr(context, "window", None)
    if current_area is not None and current_area.type == "VIEW_3D":
        region = next(
            (item for item in current_area.regions if item.type == "WINDOW"),
            None,
        )
        if region is not None:
            return current_window, current_area, region, current_area.spaces.active

    best = None
    best_size = -1
    windows = getattr(getattr(context, "window_manager", None), "windows", ())
    for window in windows:
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", ()):
            if area.type != "VIEW_3D":
                continue
            region = next(
                (item for item in area.regions if item.type == "WINDOW"),
                None,
            )
            size = getattr(area, "width", 0) * getattr(area, "height", 0)
            if region is not None and size > best_size:
                best = (window, area, region, area.spaces.active)
                best_size = size
    return best


def select_only_moodboard_item(scene, item) -> None:
    """Deselect every moodboard still/movie, then select *item*."""
    for other in getattr(scene, "mixie_moodboard_images", ()):
        other.selected = other is item
    if hasattr(item, "selected"):
        item.selected = True


def capture_viewport_to_board(context, *, display_name: str = "Viewport"):
    """OpenGL-capture the 3D view, pack it, and place it on the moodboard.

    Returns the new moodboard item. Raises ``RuntimeError`` when no 3D view
    is available or the capture produces no still.
    """
    import bpy

    from .media_import import add_packed_image_to_board, pack_still_image

    scene = context.scene
    target = find_view3d_context(context)
    if target is None:
        raise RuntimeError("No 3D viewport is available")
    window, area, region, space = target
    render = scene.render
    image_settings = render.image_settings
    old = {
        "filepath": render.filepath,
        "percentage": render.resolution_percentage,
        "media_type": getattr(image_settings, "media_type", None),
        "format": image_settings.file_format,
        "color_mode": image_settings.color_mode,
    }
    temp_dir = bpy.app.tempdir or tempfile.gettempdir()
    path = os.path.join(temp_dir, f"mixar_viewport_{uuid.uuid4().hex}.png")
    try:
        render.filepath = path
        longest_edge = max(render.resolution_x, render.resolution_y, 1)
        render.resolution_percentage = min(100, max(1, round(128000 / longest_edge)))
        if old["media_type"] is not None:
            image_settings.media_type = "IMAGE"
        image_settings.file_format = "PNG"
        image_settings.color_mode = "RGB"
        with context.temp_override(
            window=window,
            area=area,
            region=region,
            space_data=space,
            scene=scene,
        ):
            result = bpy.ops.render.opengl(write_still=True, view_context=True)
        if "FINISHED" not in result or not os.path.isfile(path):
            raise RuntimeError("Viewport capture did not produce an image")
        image = pack_still_image(path, display_name=display_name)
    finally:
        render.filepath = old["filepath"]
        render.resolution_percentage = old["percentage"]
        if old["media_type"] is not None:
            image_settings.media_type = old["media_type"]
        image_settings.file_format = old["format"]
        image_settings.color_mode = old["color_mode"]
        try:
            os.remove(path)
        except OSError:
            pass

    item = add_packed_image_to_board(scene, image, selected=True)
    select_only_moodboard_item(scene, item)
    return item
