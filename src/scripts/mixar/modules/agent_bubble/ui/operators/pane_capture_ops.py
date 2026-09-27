# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Reference-image operators for the agent island's category panes.

Two small operators the island's C++ panes bind:

- ``mixar.pane_capture_viewport`` — screenshot the 3D viewport (the same
  ``render.opengl(view_context=True)`` capture the chat attachment flow uses,
  see ``space_mixie_chat/ui/operators/screenshot_ops.py``) and attach the
  still as the ACTIVE pane's reference through the routing table in
  ``agent_bubble/core/pane_references.py`` (shared with clipboard paste).

- ``mixar.pane_video_upload_reference`` — file picker that imports images and videos
  onto the moodboard AS SELECTED, feeding Video Gen's native selection-based
  reference flow. (The moodboard Video Gen tab has no upload property — its
  references are the board selection, so "upload a reference" for video
  means "board it selected".)

Runs entirely on the main thread; the capture must be dispatched from a
window whose screen may lack a 3D viewport (the bubble), so the viewport is
resolved across ALL windows and the OpenGL render runs under a
``temp_override`` of that window/area/region.
"""

import glob
import logging
import os
import time

import bpy
from bpy.types import Operator

from mixar.modules.agent_bubble.core.pane_references import (
    PANE_TABS,
    attach_file_to_pane,
    attach_to_board_selected,
    redraw_bubbles,
)

logger = logging.getLogger(__name__)

_CAPTURE_BASENAME = "mixar_pane_capture"


def _find_view3d():
    """(window, area, region) of the first 3D viewport across all windows."""
    wm = bpy.context.window_manager
    for window in wm.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for region in area.regions:
                if region.type == 'WINDOW':
                    return window, area, region
    return None, None, None


def _capture_viewport_to_file(context):
    """OpenGL-render the 3D viewport to a PNG; returns the path or None."""
    from mixar.modules.space_mixie_chat.core.image_utils import (
        get_mixar_screenshots_dir,
    )

    window, area, region = _find_view3d()
    if window is None:
        return None

    screenshots_dir = get_mixar_screenshots_dir()
    timestamp = int(time.time() * 1000)
    path = os.path.join(
        screenshots_dir, f"{_CAPTURE_BASENAME}_{os.getpid()}_{timestamp}.png"
    )

    # Keep only the last few captures from this session.
    old = sorted(
        glob.glob(
            os.path.join(screenshots_dir, f"{_CAPTURE_BASENAME}_{os.getpid()}_*.png")
        )
    )
    for old_file in old[:-5]:
        try:
            os.remove(old_file)
        except OSError:
            pass

    scene = window.scene
    render = scene.render
    settings = render.image_settings
    original_filepath = render.filepath
    original_x = render.resolution_x
    original_y = render.resolution_y
    original_percentage = render.resolution_percentage
    original_format = settings.file_format
    original_media = getattr(settings, "media_type", None)
    try:
        render.filepath = path
        render.resolution_x = region.width
        render.resolution_y = region.height
        # Anything but 100% and the capture is not the size of the region the
        # user is looking at.
        render.resolution_percentage = 100
        # media_type BEFORE file_format: on Blender 5 a scene whose output is
        # FFMPEG rejects PNG outright, so this died on any scene that had been
        # through Director's guide render or that the user simply configured
        # for video. Both sibling capture paths (scribble_mark/core/freeze.py,
        # director/core/capture.py) document the same ordering; this one was
        # written without it.
        if original_media is not None:
            settings.media_type = "IMAGE"
        settings.file_format = "PNG"
        with context.temp_override(window=window, area=area, region=region):
            bpy.ops.render.opengl(write_still=True, view_context=True)
    finally:
        render.filepath = original_filepath
        render.resolution_x = original_x
        render.resolution_y = original_y
        render.resolution_percentage = original_percentage
        if original_media is not None:
            settings.media_type = original_media
        settings.file_format = original_format

    return path if os.path.exists(path) else None


class MIXAR_OT_pane_capture_viewport(Operator):
    """Capture the 3D viewport and attach it as the pane's reference image"""

    bl_idname = "mixar.pane_capture_viewport"
    bl_label = "Capture Viewport"
    bl_description = (
        "Screenshot the 3D viewport and attach it as a reference image for "
        "the current generation tab"
    )
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        scene = context.scene
        wm = context.window_manager
        tab = getattr(wm, "mixar_bubble_tab", 'AGENT')

        try:
            path = _capture_viewport_to_file(context)
        except Exception as exc:  # noqa: BLE001
            logger.error("Viewport capture failed: %r", exc)
            self.report({'ERROR'}, f"Viewport capture failed: {exc}")
            return {'CANCELLED'}
        if path is None:
            self.report({'WARNING'}, "No 3D viewport found to capture")
            return {'CANCELLED'}

        # Only the Image, Video and Splat panes bind this; any other caller
        # keeps the historical Image default.
        pane = tab if tab in PANE_TABS else 'IMAGE'
        try:
            attach_file_to_pane(scene, pane, path, "Viewport Capture")
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not attach viewport capture: %r", exc)
            self.report({'ERROR'}, f"Could not attach capture: {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, "Viewport captured as reference")
        redraw_bubbles(wm)
        return {'FINISHED'}


class MIXAR_OT_pane_video_upload_reference(Operator):
    """Upload image and video references for video generation"""

    bl_idname = "mixar.pane_video_upload_reference"
    bl_label = "Upload Video References"
    bl_description = (
        "Import image and video files onto the moodboard as selected references for "
        "video generation"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    directory: bpy.props.StringProperty(subtype='DIR_PATH')
    filter_glob: bpy.props.StringProperty(
        default=";".join(f"*{ext}" for ext in sorted(
            set(bpy.path.extensions_image) | set(bpy.path.extensions_movie))),
        options={'HIDDEN'},
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        scene = context.scene
        added = 0
        paths = [os.path.join(self.directory, file.name) for file in self.files if file.name]
        for filepath in paths or [self.filepath]:
            try:
                filepath = os.path.abspath(os.path.realpath(filepath))
            except (OSError, ValueError):
                continue
            if not os.path.isfile(filepath):
                continue
            try:
                if attach_to_board_selected(scene, filepath) is not None:
                    added += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("Video reference import failed: %r", exc)
        if added == 0:
            self.report({'WARNING'}, "No valid image or video references added")
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            f"Added {added} selected reference{'s' if added != 1 else ''}",
        )
        return {'FINISHED'}


classes = (
    MIXAR_OT_pane_capture_viewport,
    MIXAR_OT_pane_video_upload_reference,
)
