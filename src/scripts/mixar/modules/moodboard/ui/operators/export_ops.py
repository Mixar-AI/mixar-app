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


class MIXIE_OT_moodboard_export_images(Operator):
    """Export selected moodboard images"""

    bl_idname = "mixie.moodboard_export_images"
    bl_label = "Export Selected Images"
    bl_description = "Save selected images to disk"
    bl_options = {'REGISTER'}

    filepath: StringProperty(
        name="File Path",
        description="Export file path",
        subtype='FILE_PATH',
    )

    filter_glob: StringProperty(
        default="*.png;*.jpg;*.jpeg;*.tga;*.bmp;*.tif;*.tiff",
        options={'HIDDEN'},
    )

    def invoke(self, context, event):
        scene = context.scene
        selected_images = [
            img for img in scene.mixie_moodboard_images
            if img.selected and img.image
        ]

        if not selected_images:
            self.report({'WARNING'}, "No images selected to export")
            return {'CANCELLED'}

        # Pre-fill filename from the first selected image
        img = selected_images[0].image
        name = bpy.path.clean_name(img.name)
        if not name:
            name = "image"
        if not any(
            name.lower().endswith(ext)
            for ext in ('.png', '.jpg', '.jpeg', '.tga', '.bmp', '.tif', '.tiff')
        ):
            name += ".png"
        self.filepath = name

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        import os

        scene = context.scene
        selected_images = [
            img for img in scene.mixie_moodboard_images
            if img.selected and img.image
        ]

        if not selected_images:
            self.report({'WARNING'}, "No images selected to export")
            return {'CANCELLED'}

        # Validate the chosen path
        try:
            filepath = os.path.abspath(os.path.realpath(self.filepath))
        except (OSError, ValueError) as e:
            self.report({'ERROR'}, f"Invalid path: {e}")
            return {'CANCELLED'}

        output_dir = os.path.dirname(filepath)
        if not os.path.isdir(output_dir):
            self.report({'ERROR'}, f"Invalid directory: {output_dir}")
            return {'CANCELLED'}

        # Single image: save with the exact filename the user chose
        if len(selected_images) == 1:
            try:
                selected_images[0].image.save_render(filepath, scene=scene)
            except Exception as e:
                self.report({'ERROR'}, f"Failed to save: {e}")
                return {'CANCELLED'}
            self.report({'INFO'}, f"Exported image to {filepath}")
            return {'FINISHED'}

        # Multiple images: save to the chosen directory with original names
        count = 0
        for item in selected_images:
            img = item.image

            name = bpy.path.clean_name(img.name)
            if not name:
                name = f"image_{count}"

            if not any(
                name.lower().endswith(ext)
                for ext in ('.png', '.jpg', '.jpeg', '.tga', '.bmp', '.tif', '.tiff')
            ):
                name += ".png"

            dest = os.path.join(output_dir, name)

            # Ensure the resolved path stays within the output directory
            try:
                dest = os.path.abspath(os.path.realpath(dest))
                if not dest.startswith(output_dir):
                    self.report({'ERROR'}, f"Invalid file path: {name}")
                    continue
            except (OSError, ValueError) as e:
                self.report({'ERROR'}, f"Invalid file path for {name}: {e}")
                continue

            try:
                img.save_render(dest, scene=scene)
                count += 1
            except Exception as e:
                self.report({'ERROR'}, f"Failed to save {name}: {e}")

        self.report({'INFO'}, f"Exported {count} images to {output_dir}")
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
