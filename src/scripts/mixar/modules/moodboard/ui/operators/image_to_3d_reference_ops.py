# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Image to 3D Reference Operators

Operators for managing input/reference images and refreshing model lists
in the Image to 3D workflow.
"""

import os

import bpy
from bpy.types import Operator

from ....common.utils.file_select_utils import file_select_guard, mark_file_select_executed
from ...core.image_lifecycle import remove_image_safely


class MIXIE_OT_image_to_3d_upload_image(Operator):
    """Upload an image file for sidebar Image to 3D tab"""

    bl_idname = "mixie.image_to_3d_upload_image"
    bl_label = "Upload Image"
    bl_description = "Select an image file for 3D model generation"
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Path to the input image file",
        subtype="FILE_PATH",
    )

    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.tiff;*.webp", options={"HIDDEN"}
    )

    def invoke(self, context, event):
        if not file_select_guard(self, context):
            return {"FINISHED"}
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.filepath:
            self.report({"WARNING"}, "No file selected")
            return {"CANCELLED"}

        try:
            filepath = os.path.abspath(os.path.realpath(self.filepath))
        except (OSError, ValueError) as e:
            self.report({"ERROR"}, f"Invalid file path: {e}")
            return {"CANCELLED"}

        if not os.path.isfile(filepath):
            self.report({"ERROR"}, f"File not found: {filepath}")
            return {"CANCELLED"}

        # Validate it's an image file
        valid_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tga', '.tiff', '.tif', '.webp'}
        file_ext = os.path.splitext(filepath)[1].lower()

        if file_ext not in valid_extensions:
            self.report({"ERROR"}, f"Invalid image format: {file_ext}")
            return {"CANCELLED"}

        # Load the image and set as reference_image
        try:
            image = bpy.data.images.load(filepath, check_existing=True)
        except Exception as e:
            self.report({"ERROR"}, f"Failed to load image: {e}")
            return {"CANCELLED"}

        # Set the image in sidebar tab properties
        scene = context.scene
        if hasattr(scene, 'mixie_moodboard_sidebar'):
            sidebar = scene.mixie_moodboard_sidebar
            if hasattr(sidebar, 'tab_image_to_3d'):
                sidebar.tab_image_to_3d.reference_image = image
                # Switch to uploaded-image mode so the info card is visible
                sidebar.tab_image_to_3d.use_selected_image = False
                self.report({"INFO"}, f"Set '{image.name}' as input image")
                mark_file_select_executed(self)
                return {"FINISHED"}

        self.report({"ERROR"}, "Sidebar properties not found")
        return {"CANCELLED"}


class MIXIE_OT_image_to_3d_remove_image(Operator):
    """Remove the input image from Image to 3D tab"""

    bl_idname = "mixie.image_to_3d_remove_image"
    bl_label = "Remove Image"
    bl_description = "Remove the input image"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
        if hasattr(scene, 'mixie_moodboard_sidebar'):
            sidebar = scene.mixie_moodboard_sidebar
            if hasattr(sidebar, 'tab_image_to_3d'):
                tab = sidebar.tab_image_to_3d
                old_img = getattr(tab, 'reference_image', None)
                tab.reference_image = None
                remove_image_safely(old_img)
                self.report({"INFO"}, "Input image removed")
                return {"FINISHED"}

        self.report({"ERROR"}, "Sidebar properties not found")
        return {"CANCELLED"}


class MIXIE_OT_image_to_3d_pick_image(Operator):
    """Pick an input image for 3D generation"""

    bl_idname = "mixie.image_to_3d_pick_image"
    bl_label = "Pick Image"
    bl_description = "Select an input image file for 3D model generation"
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Path to the input image file",
        subtype="FILE_PATH",
    )

    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.tiff;*.webp", options={"HIDDEN"}
    )

    def invoke(self, context, event):
        if not file_select_guard(self, context):
            return {"FINISHED"}
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.filepath:
            self.report({"WARNING"}, "No file selected")
            return {"CANCELLED"}

        try:
            filepath = os.path.abspath(os.path.realpath(self.filepath))
        except (OSError, ValueError) as e:
            self.report({"ERROR"}, f"Invalid file path: {e}")
            return {"CANCELLED"}

        if not os.path.isfile(filepath):
            self.report({"ERROR"}, f"File not found: {filepath}")
            return {"CANCELLED"}

        try:
            img = bpy.data.images.load(filepath, check_existing=True)
            img.pack()
        except Exception as e:
            self.report({"ERROR"}, f"Failed to load image: {e}")
            return {"CANCELLED"}

        scene = context.scene
        # Set on sidebar tab property for visual feedback in the panel
        if hasattr(scene, 'mixie_moodboard_sidebar'):
            sidebar = scene.mixie_moodboard_sidebar
            if hasattr(sidebar, 'tab_image_to_3d'):
                sidebar.tab_image_to_3d.reference_image = img
                # Switch to uploaded-image mode so the info card is visible
                sidebar.tab_image_to_3d.use_selected_image = False
        # Also set the global scene property for legacy/popup contexts
        scene.mixie_image_to_3d_image = img
        self.report({"INFO"}, f"Selected '{img.name}' as input image")
        mark_file_select_executed(self)
        return {"FINISHED"}


class MIXIE_OT_image_to_3d_refresh_models(Operator):
    """Refresh the list of available 3D generation models"""

    bl_idname = "mixie.image_to_3d_refresh_models"
    bl_label = "Refresh Models"
    bl_description = "Refresh the list of available 3D generation models from the server"
    bl_options = {"REGISTER"}

    def execute(self, context):
        try:
            from mixar.bootstrap.generation_catalog_cache import (
                refresh_generation_catalog_cache,
            )

            refresh_generation_catalog_cache()
        except Exception:
            pass
        try:
            from mixar.bootstrap.model_3d_cache import refresh_models_cache

            refresh_models_cache()
            self.report({"INFO"}, "Refreshing models list...")
        except ImportError:
            self.report({"ERROR"}, "Model cache module not available")
            return {"CANCELLED"}
        return {"FINISHED"}


classes = (
    MIXIE_OT_image_to_3d_upload_image,
    MIXIE_OT_image_to_3d_remove_image,
    MIXIE_OT_image_to_3d_pick_image,
    MIXIE_OT_image_to_3d_refresh_models,
)


def register():
    """Register operator classes"""
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)


def unregister():
    """Unregister operator classes"""
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
