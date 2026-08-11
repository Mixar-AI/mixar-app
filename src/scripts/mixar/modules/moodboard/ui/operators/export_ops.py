# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Export and Style Context Operators

Operators for exporting images and managing style context.
"""

import bpy
from bpy.types import Operator
from bpy.props import StringProperty

from ....common.utils.file_select_utils import file_select_guard, mark_file_select_executed
from mixar.modules.common.analytics.export_events import capture_export
from ...core.media_utils import (
    describe_moodboard_media,
    is_video_item,
    selected_exportable_media,
)


_STILL_EXPORT_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.tga', '.bmp', '.tif', '.tiff')


def _capture_moodboard_export(context, success, image_count, filepath=None):
    try:
        capture_export(context, export_format="MOODBOARD_IMAGE", success=success,
                       filepath=filepath, extra={"image_count": image_count})
    except Exception:
        pass


def _selected_media(scene):
    # Includes results owned by a selected inference node: those are never
    # `selected` themselves, so right-clicking a completed node and choosing
    # Export used to report "No media selected to export".
    return selected_exportable_media(scene)


def _default_export_name(item, fallback_index=0):
    """Keep a movie's original extension; render stills as PNG by default."""
    if is_video_item(item):
        media = describe_moodboard_media(item)
        if media["filename"]:
            return media["filename"]

    name = bpy.path.clean_name(item.image.name) or f"image_{fallback_index}"
    if not name.lower().endswith(_STILL_EXPORT_EXTENSIONS):
        name += ".png"
    return name


def _export_media_item(item, filepath, scene):
    """Export one item, copying original movie bytes without re-encoding."""
    if not is_video_item(item):
        item.image.save_render(filepath, scene=scene)
        return

    import os
    import shutil

    media = describe_moodboard_media(item)
    source = media["resolved_filepath"]
    if not media["source_available"]:
        raise FileNotFoundError(source or media["filepath"] or item.image.name)

    try:
        if os.path.samefile(source, filepath):
            return
    except (FileNotFoundError, OSError):
        pass
    shutil.copy2(source, filepath)


class MIXIE_OT_moodboard_export_images(Operator):
    """Export selected moodboard images and videos"""

    bl_idname = "mixie.moodboard_export_images"
    bl_label = "Export Selected Media"
    bl_description = "Save selected images or copy selected videos to disk"
    bl_options = {'REGISTER'}

    filepath: StringProperty(
        name="File Path",
        description="Export file path",
        subtype='FILE_PATH',
    )

    filter_glob: StringProperty(
        default=(
            "*.png;*.jpg;*.jpeg;*.tga;*.bmp;*.tif;*.tiff;"
            "*.mp4;*.mov;*.m4v;*.webm;*.mkv;*.avi"
        ),
        options={'HIDDEN'},
    )

    def invoke(self, context, event):
        scene = context.scene
        selected_media = _selected_media(scene)

        if not selected_media:
            self.report({'WARNING'}, "No media selected to export")
            return {'CANCELLED'}

        self.filepath = _default_export_name(selected_media[0])

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        import os

        scene = context.scene
        selected_media = _selected_media(scene)

        if not selected_media:
            self.report({'WARNING'}, "No media selected to export")
            return {'CANCELLED'}

        # Validate the chosen path
        try:
            filepath = os.path.abspath(os.path.realpath(self.filepath))
        except (OSError, ValueError) as e:
            self.report({'ERROR'}, f"Invalid path: {e}")
            _capture_moodboard_export(context, False, len(selected_media))
            return {'CANCELLED'}

        output_dir = os.path.dirname(filepath)
        if not os.path.isdir(output_dir):
            self.report({'ERROR'}, f"Invalid directory: {output_dir}")
            _capture_moodboard_export(context, False, len(selected_media))
            return {'CANCELLED'}

        # Single item: honor the exact destination selected by the user.
        if len(selected_media) == 1:
            try:
                _export_media_item(selected_media[0], filepath, scene)
            except Exception as e:
                self.report({'ERROR'}, f"Failed to export: {e}")
                _capture_moodboard_export(context, False, 1, filepath)
                return {'CANCELLED'}
            self.report({'INFO'}, f"Exported media to {filepath}")
            _capture_moodboard_export(context, True, 1, filepath)
            return {'FINISHED'}

        # Multiple items: export to the chosen directory with original names.
        count = 0
        for item_index, item in enumerate(selected_media):
            name = _default_export_name(item, item_index)
            dest = os.path.join(output_dir, name)

            # Ensure the resolved path stays within the output directory
            try:
                dest = os.path.abspath(os.path.realpath(dest))
                if os.path.commonpath((output_dir, dest)) != output_dir:
                    self.report({'ERROR'}, f"Invalid file path: {name}")
                    continue
            except (OSError, ValueError) as e:
                self.report({'ERROR'}, f"Invalid file path for {name}: {e}")
                continue

            try:
                _export_media_item(item, dest, scene)
                count += 1
            except Exception as e:
                self.report({'ERROR'}, f"Failed to save {name}: {e}")

        self.report({'INFO'}, f"Exported {count} media items to {output_dir}")
        _capture_moodboard_export(context, count > 0, count)
        return {'FINISHED'}


class MIXIE_OT_add_style_context_image(Operator):
    """Add an image as style context for AI generation"""

    bl_idname = "mixie.add_style_context_image"
    bl_label = "Add Style Context Image"
    bl_description = "Import an image to use as style reference for AI generation"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(
        name="File Path",
        description="Path to the image file",
        subtype='FILE_PATH'
    )

    filter_glob: StringProperty(
        default="*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.tiff;*.webp",
        options={'HIDDEN'}
    )

    def invoke(self, context, event):
        if not file_select_guard(self, context):
            return {'FINISHED'}
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        import os

        if not self.filepath:
            self.report({'WARNING'}, "No file selected")
            return {'CANCELLED'}

        # Validate and normalize the file path to prevent path traversal
        try:
            filepath = os.path.abspath(os.path.realpath(self.filepath))
        except (OSError, ValueError) as e:
            self.report({'ERROR'}, f"Invalid file path: {e}")
            return {'CANCELLED'}

        if not os.path.isfile(filepath):
            self.report({'ERROR'}, f"File not found: {filepath}")
            return {'CANCELLED'}

        try:
            img = bpy.data.images.load(filepath, check_existing=True)
            img.pack()
            img.preview_ensure()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to load image: {e}")
            return {'CANCELLED'}

        context.scene.mixie_style_context_image = img
        self.report({'INFO'}, f"Set '{img.name}' as style context")
        mark_file_select_executed(self)
        return {'FINISHED'}


class MIXIE_OT_remove_style_context_image(Operator):
    """Remove the style context image"""

    bl_idname = "mixie.remove_style_context_image"
    bl_label = "Remove Style Context Image"
    bl_description = "Remove the style context image"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene.mixie_style_context_image = None
        self.report({'INFO'}, "Removed style context image")
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_export_images,
    MIXIE_OT_add_style_context_image,
    MIXIE_OT_remove_style_context_image,
)
