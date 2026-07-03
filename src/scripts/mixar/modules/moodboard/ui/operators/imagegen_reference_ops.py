# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Image Gen Reference Operators

Operators for managing reference images, style images, and model refresh
for AI image generation.
"""

import os

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.file_select_utils import file_select_guard, mark_file_select_executed
from mixar.modules.moodboard.core.moodboard_utils import get_moodboard_viewport_center
from mixar.modules.moodboard.core.image_lifecycle import remove_image_safely

logger = get_logger(__name__)


class MIXIE_OT_imagegen_add_style_image(Operator):
    """Add reference images for generation"""

    bl_idname = "mixie.imagegen_add_style_image"
    bl_label = "Add Reference Images"
    bl_description = "Select reference image files"
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Path to image file",
        subtype="FILE_PATH",
    )

    files: bpy.props.CollectionProperty(
        name="Files",
        type=bpy.types.OperatorFileListElement,
    )

    directory: bpy.props.StringProperty(subtype="DIR_PATH")

    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.tiff;*.webp",
        options={"HIDDEN"},
    )

    def invoke(self, context, event):
        if not file_select_guard(self, context):
            return {"FINISHED"}
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        if not self.files:
            self.report({"WARNING"}, "No files selected")
            return {"CANCELLED"}

        added_count = 0
        for file_elem in self.files:
            filepath = os.path.join(self.directory, file_elem.name)

            try:
                filepath = os.path.abspath(os.path.realpath(filepath))
            except (OSError, ValueError):
                continue

            if not os.path.isfile(filepath):
                continue

            try:
                img = bpy.data.images.load(filepath, check_existing=True)
                img.pack()
            except Exception:
                continue

            ref_item = context.scene.mixie_imagegen_ref_images.add()
            ref_item.image = img
            added_count += 1

        if added_count == 0:
            self.report({"WARNING"}, "No valid images found")
            return {"CANCELLED"}

        self.report({"INFO"}, f"Added {added_count} reference image(s)")
        mark_file_select_executed(self)
        return {"FINISHED"}


class MIXIE_OT_imagegen_remove_style_image(Operator):
    """Remove a reference image by index"""

    bl_idname = "mixie.imagegen_remove_style_image"
    bl_label = "Remove Reference Image"
    bl_description = "Remove the reference image"
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(
        name="Index",
        description="Index of the reference image to remove",
        default=-1,
    )

    def execute(self, context):
        ref_images = context.scene.mixie_imagegen_ref_images

        if self.index == -1:
            for item in list(ref_images):
                remove_image_safely(getattr(item, "image", None))
            ref_images.clear()
            self.report({"INFO"}, "Cleared all reference images")
        elif 0 <= self.index < len(ref_images):
            remove_image_safely(getattr(ref_images[self.index], "image", None))
            ref_images.remove(self.index)
            self.report({"INFO"}, "Removed reference image")
        else:
            self.report({"WARNING"}, "Invalid index")
            return {"CANCELLED"}

        return {"FINISHED"}


class MIXIE_OT_imagegen_refresh(Operator):
    """Refresh the list of available models and styles"""

    bl_idname = "mixie.imagegen_refresh"
    bl_label = "Refresh Models"
    bl_description = "Refresh the list of available models and styles from the server"
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
            from mixar.bootstrap.imagegen_cache import refresh_imagegen_cache

            refresh_imagegen_cache()
            self.report({"INFO"}, "Refreshing models and styles...")
        except ImportError:
            self.report({"ERROR"}, "ImageGen cache module not available")
            return {"CANCELLED"}
        return {"FINISHED"}


class MIXIE_OT_imagegen_upload_reference(Operator):
    """Upload reference images from file system for image generation"""

    bl_idname = "mixie.imagegen_upload_reference"
    bl_label = "Upload Reference Images"
    bl_description = "Select image files to use as references for generation"
    bl_options = {"REGISTER", "UNDO"}

    filepath: bpy.props.StringProperty(
        name="File Path",
        description="Path to image file",
        subtype="FILE_PATH",
    )

    files: bpy.props.CollectionProperty(
        name="Files",
        type=bpy.types.OperatorFileListElement,
    )

    directory: bpy.props.StringProperty(subtype="DIR_PATH")

    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.tiff;*.webp",
        options={"HIDDEN"},
    )

    def invoke(self, context, event):
        if not file_select_guard(self, context):
            return {"FINISHED"}
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        scene = context.scene

        if not self.files:
            self.report({"WARNING"}, "No files selected")
            return {"CANCELLED"}

        # Check if we have the sidebar properties
        if not hasattr(scene, 'mixie_moodboard_sidebar'):
            self.report({"WARNING"}, "Sidebar properties not available")
            return {"CANCELLED"}

        sidebar = scene.mixie_moodboard_sidebar
        if not hasattr(sidebar, 'tab_imagegen'):
            self.report({"WARNING"}, "ImageGen tab properties not available")
            return {"CANCELLED"}

        tab = sidebar.tab_imagegen

        added_count = 0
        viewport_cx, viewport_cy = get_moodboard_viewport_center()
        for file_elem in self.files:
            filepath = os.path.join(self.directory, file_elem.name)

            try:
                filepath = os.path.abspath(os.path.realpath(filepath))
            except (OSError, ValueError):
                continue

            if not os.path.isfile(filepath):
                continue

            try:
                # Load the image
                img = bpy.data.images.load(filepath, check_existing=True)
                img.pack()

                # Add to moodboard so it can be referenced, positioned at viewport centre
                mb_item = scene.mixie_moodboard_images.add()
                mb_item.image = img
                mb_item.position_x = viewport_cx
                mb_item.position_y = viewport_cy
                mb_item.selected = False

                # Get the index of the newly added moodboard item
                mb_index = len(scene.mixie_moodboard_images) - 1

                # Add reference to sidebar's reference_images collection
                ref_item = tab.reference_images.add()
                ref_item.image = img
                ref_item.moodboard_index = mb_index
                ref_item.display_name = img.name

                # Get resolution
                if img.size[0] > 0 and img.size[1] > 0:
                    ref_item.display_resolution = f"{img.size[0]} x {img.size[1]}"
                else:
                    ref_item.display_resolution = "Unknown"

                ref_item.display_path = filepath

                added_count += 1
            except Exception as e:
                logger.error("[ImageGen] Failed to load image: %s", e)
                continue

        if added_count == 0:
            self.report({"WARNING"}, "No valid images found")
            return {"CANCELLED"}

        # Switch off moodboard-selection mode so uploaded refs are primary
        tab.use_reference_images = False

        self.report({"INFO"}, f"Added {added_count} reference image(s)")

        # Redraw the UI
        for area in context.screen.areas:
            if area.type == "MIXIE":
                area.tag_redraw()

        mark_file_select_executed(self)
        return {"FINISHED"}


class MIXIE_OT_imagegen_remove_reference_image(Operator):
    """Remove a reference image from the sidebar list"""

    bl_idname = "mixie.imagegen_remove_reference_image"
    bl_label = "Remove Reference Image"
    bl_description = "Remove this reference image from the list"
    bl_options = {"REGISTER", "UNDO"}

    index: bpy.props.IntProperty(
        name="Index",
        description="Moodboard index of the reference image to remove",
        default=-1,
    )

    def execute(self, context):
        scene = context.scene

        if not hasattr(scene, 'mixie_moodboard_sidebar'):
            return {"CANCELLED"}

        sidebar = scene.mixie_moodboard_sidebar
        if not hasattr(sidebar, 'tab_imagegen'):
            return {"CANCELLED"}

        tab = sidebar.tab_imagegen

        # Find and remove the reference image with matching moodboard_index
        for i, ref_item in enumerate(tab.reference_images):
            if ref_item.moodboard_index == self.index:
                remove_image_safely(getattr(ref_item, "image", None))
                tab.reference_images.remove(i)
                self.report({"INFO"}, "Removed reference image")

                # Redraw the UI
                for area in context.screen.areas:
                    if area.type == "MIXIE":
                        area.tag_redraw()

                return {"FINISHED"}

        self.report({"WARNING"}, "Reference image not found")
        return {"CANCELLED"}


classes = (
    MIXIE_OT_imagegen_add_style_image,
    MIXIE_OT_imagegen_remove_style_image,
    MIXIE_OT_imagegen_refresh,
    MIXIE_OT_imagegen_upload_reference,
    MIXIE_OT_imagegen_remove_reference_image,
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
