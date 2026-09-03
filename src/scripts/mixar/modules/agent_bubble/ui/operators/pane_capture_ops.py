"""Reference-image operators for the agent island's category panes.

Two small operators the island's C++ panes bind:

- ``mixar.pane_capture_viewport`` — screenshot the 3D viewport (the same
  ``render.opengl(view_context=True)`` capture the chat attachment flow uses,
  see ``space_mixie_chat/ui/operators/screenshot_ops.py``) and attach the
  still as the ACTIVE pane's reference:

  * Media / Image  -> ``tab_imagegen.reference_images`` (the exact add the
    moodboard's ``mixie.imagegen_upload_reference`` performs: packed image,
    boarded unselected, mirrored into the tab's reference collection).
  * Media / Video  -> boarded as a SELECTED moodboard item — Video Gen's
    references ARE the selected board media
    (``get_selected_moodboard_media_inputs``).
  * Gaussian Splat -> ``tab_world_labs.reference_image`` with
    ``use_selected_image`` switched off so the capture is what submits.

- ``mixar.pane_video_upload_reference`` — file picker that imports stills
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
    original_filepath = scene.render.filepath
    original_x = scene.render.resolution_x
    original_y = scene.render.resolution_y
    try:
        scene.render.filepath = path
        scene.render.resolution_x = region.width
        scene.render.resolution_y = region.height
        with context.temp_override(window=window, area=area, region=region):
            bpy.ops.render.opengl(write_still=True, view_context=True)
    finally:
        scene.render.filepath = original_filepath
        scene.render.resolution_x = original_x
        scene.render.resolution_y = original_y

    return path if os.path.exists(path) else None


def _attach_to_imagegen(scene, img, filepath):
    """The exact reference-add mixie.imagegen_upload_reference performs."""
    from mixar.modules.moodboard.core.moodboard_utils import (
        place_new_moodboard_item,
    )

    tab = scene.mixie_moodboard_sidebar.tab_imagegen

    mb_item = scene.mixie_moodboard_images.add()
    mb_item.image = img
    mb_item.scale = 1.0
    place_new_moodboard_item(scene, mb_item)
    mb_item.selected = False

    ref_item = tab.reference_images.add()
    ref_item.image = img
    ref_item.moodboard_index = len(scene.mixie_moodboard_images) - 1
    ref_item.display_name = img.name
    if img.size[0] > 0 and img.size[1] > 0:
        ref_item.display_resolution = f"{img.size[0]} x {img.size[1]}"
    else:
        ref_item.display_resolution = "Unknown"
    ref_item.display_path = filepath
    if hasattr(tab, "use_reference_images"):
        tab.use_reference_images = True


def _attach_to_board_selected(scene, filepath):
    """Board the file as a SELECTED item (Video Gen's reference source)."""
    from mixar.modules.moodboard.core.media_import import (
        load_media_file_to_board,
    )

    item = load_media_file_to_board(scene, filepath)
    if item is not None:
        item.selected = True
    return item


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
        media_kind = getattr(wm, "mixar_bubble_media_kind", 'IMAGE')

        try:
            path = _capture_viewport_to_file(context)
        except Exception as exc:  # noqa: BLE001
            logger.error("Viewport capture failed: %r", exc)
            self.report({'ERROR'}, f"Viewport capture failed: {exc}")
            return {'CANCELLED'}
        if path is None:
            self.report({'WARNING'}, "No 3D viewport found to capture")
            return {'CANCELLED'}

        sidebar = getattr(scene, "mixie_moodboard_sidebar", None)
        if sidebar is None:
            self.report({'WARNING'}, "Moodboard sidebar properties unavailable")
            return {'CANCELLED'}

        try:
            if tab == 'MEDIA' and media_kind == 'VIDEO':
                if _attach_to_board_selected(scene, path) is None:
                    raise RuntimeError("could not board the capture")
            else:
                img = bpy.data.images.load(path, check_existing=False)
                img.name = "Viewport Capture"
                img.pack()
                if tab == 'SPLAT':
                    wl = sidebar.tab_world_labs
                    wl.reference_image = img
                    if hasattr(wl, "use_selected_image"):
                        wl.use_selected_image = False
                else:
                    # MEDIA / IMAGE (and any future pane defaults here).
                    _attach_to_imagegen(scene, img, path)
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not attach viewport capture: %r", exc)
            self.report({'ERROR'}, f"Could not attach capture: {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, "Viewport captured as reference")
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type == 'AGENT_BUBBLE':
                    area.tag_redraw()
        return {'FINISHED'}


class MIXAR_OT_pane_video_upload_reference(Operator):
    """Upload reference stills for video generation (boarded as selected)"""

    bl_idname = "mixar.pane_video_upload_reference"
    bl_label = "Upload Video References"
    bl_description = (
        "Import image files onto the moodboard as selected references for "
        "video generation"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    directory: bpy.props.StringProperty(subtype='DIR_PATH')
    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.tiff;*.webp",
        options={'HIDDEN'},
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        scene = context.scene
        added = 0
        for file_elem in self.files:
            filepath = os.path.join(self.directory, file_elem.name)
            try:
                filepath = os.path.abspath(os.path.realpath(filepath))
            except (OSError, ValueError):
                continue
            if not os.path.isfile(filepath):
                continue
            try:
                if _attach_to_board_selected(scene, filepath) is not None:
                    added += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("Video reference import failed: %r", exc)
        if added == 0:
            self.report({'WARNING'}, "No reference images added")
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
