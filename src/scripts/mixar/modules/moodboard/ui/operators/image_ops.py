# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Image Operators

Operators for adding images to the moodboard.
"""

import bpy
from bpy.types import Operator
from bpy.props import StringProperty, CollectionProperty, EnumProperty

from ...constants import MOODBOARD_IMAGE_BASE_SIZE, MOODBOARD_MULTI_IMAGE_GAP
from ...core.moodboard_utils import get_moodboard_viewport_center
from ....common.utils.file_select_utils import file_select_guard, mark_file_select_executed
from ....common.utils.platform_utils import format_shortcut


def _load_image_from_filepath(scene, filepath):
    """Load an image from filepath and add it to the moodboard.

    Reusable helper that loads the image into Blender, packs it, and appends
    it to the moodboard collection.  Returns the new item on success or None.

    Args:
        scene: The current Blender scene.
        filepath: Absolute path to the image file.

    Returns:
        The newly created moodboard item, or None on failure.
    """
    import os

    try:
        img = bpy.data.images.load(filepath, check_existing=True)
        img.colorspace_settings.name = 'sRGB'
        img.pack()
    except Exception:
        return None

    if img.size[1] > 0:
        aspect_ratio = img.size[0] / img.size[1]
        image_width = MOODBOARD_IMAGE_BASE_SIZE * aspect_ratio
    else:
        image_width = MOODBOARD_IMAGE_BASE_SIZE

    viewport_cx, viewport_cy = get_moodboard_viewport_center()

    item = scene.mixie_moodboard_images.add()
    item.image = img
    item.position_x = viewport_cx
    item.position_y = viewport_cy
    item.scale = 1.0
    item.z_order = len(scene.mixie_moodboard_images) - 1
    return item


class MIXIE_OT_moodboard_add_image(Operator):
    """Import image file(s) and add them to the moodboard"""

    bl_idname = "mixie.moodboard_add_image"
    bl_label = "Add Image to Moodboard"
    bl_description = f"Import image file(s) and add them to the moodboard ({format_shortcut('I')})"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(
        name="File Path",
        description="Path to the image file",
        subtype='FILE_PATH'
    )

    directory: StringProperty(
        name="Directory",
        description="Directory of the selected file(s)",
        subtype='DIR_PATH'
    )

    files: CollectionProperty(
        name="Files",
        type=bpy.types.OperatorFileListElement
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

        scene = context.scene

        # Build list of filepaths from multi-selection
        filepaths = []
        if self.files and self.directory:
            for file_elem in self.files:
                if file_elem.name:
                    full_path = os.path.join(self.directory, file_elem.name)
                    filepaths.append(full_path)

        # Fallback to single filepath if no multi-selection
        if not filepaths and self.filepath:
            filepaths.append(self.filepath)

        if not filepaths:
            self.report({'WARNING'}, "No file selected")
            return {'CANCELLED'}

        added_count = 0

        # Place the first image at the viewport centre; subsequent images are
        # laid out side-by-side starting from that centre position.
        viewport_cx, viewport_cy = get_moodboard_viewport_center()
        current_x = viewport_cx

        for i, raw_filepath in enumerate(filepaths):
            # Validate and normalize the file path to prevent path traversal
            try:
                filepath = os.path.abspath(os.path.realpath(raw_filepath))
            except (OSError, ValueError) as e:
                self.report({'WARNING'}, f"Invalid file path: {e}")
                continue

            if not os.path.isfile(filepath):
                self.report({'WARNING'}, f"File not found: {filepath}")
                continue

            item = _load_image_from_filepath(scene, filepath)
            if item is None:
                self.report({'WARNING'}, f"Failed to load image: {filepath}")
                continue

            # Position images side by side
            img = item.image
            if img.size[1] > 0:
                aspect_ratio = img.size[0] / img.size[1]
                image_width = MOODBOARD_IMAGE_BASE_SIZE * aspect_ratio
            else:
                image_width = MOODBOARD_IMAGE_BASE_SIZE

            item.position_x = current_x
            item.position_y = viewport_cy
            current_x += image_width + MOODBOARD_MULTI_IMAGE_GAP
            added_count += 1

        if added_count == 0:
            self.report({'ERROR'}, "No images could be loaded")
            return {'CANCELLED'}
        elif added_count == 1:
            self.report({'INFO'}, "Added 1 image to moodboard")
        else:
            self.report({'INFO'}, f"Added {added_count} images to moodboard")

        mark_file_select_executed(self)
        return {'FINISHED'}


# Blender requirement: enum-items callbacks must keep the returned strings
# referenced from Python, otherwise they can be garbage-collected while the
# UI still points at them (crashes/garbled text).
_existing_image_items = []


def _get_existing_images(self, context):
    """Build enum items from images already loaded in Blender."""
    global _existing_image_items
    items = []
    for i, img in enumerate(bpy.data.images):
        # Skip internal/viewer images
        if img.name.startswith('.') or img.type == 'RENDER_RESULT' or img.type == 'COMPOSITING':
            continue
        desc = f"{img.size[0]}x{img.size[1]}"
        # 5-tuple with the image's preview icon so the search popup shows
        # a thumbnail per row (operator enum popups have no automatic ID
        # icon lookup, unlike prop()/template_ID browse dropdowns).
        try:
            preview = img.preview_ensure()
            icon_id = preview.icon_id if preview else 0
        except Exception:
            icon_id = 0
        items.append((img.name, img.name, desc, icon_id, i))
    if not items:
        items.append(('NONE', "No images available", "", 0, 0))
    _existing_image_items = items
    return items


class MIXIE_OT_moodboard_add_existing_image(Operator):
    """Pick an image already loaded in Blender and add it to the moodboard"""

    bl_idname = "mixie.moodboard_add_existing_image"
    bl_label = "Add Existing Image"
    bl_description = "Pick an image already loaded in Blender and add it to the moodboard"
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = "image_name"

    image_name: EnumProperty(
        name="Image",
        description="Choose an existing image",
        items=_get_existing_images,
    )

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        if self.image_name == 'NONE':
            self.report({'WARNING'}, "No images available in this file")
            return {'CANCELLED'}

        img = bpy.data.images.get(self.image_name)
        if not img:
            self.report({'WARNING'}, f"Image '{self.image_name}' not found")
            return {'CANCELLED'}

        scene = context.scene

        # Add to moodboard collection at the centre of the visible viewport
        viewport_cx, viewport_cy = get_moodboard_viewport_center()
        item = scene.mixie_moodboard_images.add()
        item.image = img
        item.position_x = viewport_cx
        item.position_y = viewport_cy
        item.scale = 1.0
        item.z_order = len(scene.mixie_moodboard_images) - 1

        self.report({'INFO'}, f"Added '{img.name}' to moodboard")
        return {'FINISHED'}


class MIXIE_OT_moodboard_paste_image(Operator):
    """Paste an image from the clipboard and add it to the moodboard"""

    bl_idname = "mixie.moodboard_paste_image"
    bl_label = "Paste Image from Clipboard"
    bl_description = (
        f"Paste an image from the clipboard into the moodboard "
        f"({format_shortcut('V')})"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        import os
        import tempfile

        # Try to grab an image from the system clipboard using PIL/Pillow
        try:
            from PIL import ImageGrab
        except ImportError:
            self.report(
                {'ERROR'},
                "Pillow is required for clipboard paste. "
                "Install it with: pip install Pillow"
            )
            return {'CANCELLED'}

        try:
            clip_img = ImageGrab.grabclipboard()
        except Exception as e:
            self.report({'ERROR'}, f"Failed to read clipboard: {e}")
            return {'CANCELLED'}

        if clip_img is None:
            self.report({'WARNING'}, "No image found in clipboard")
            return {'CANCELLED'}

        # ImageGrab.grabclipboard() may return a list of file paths on some
        # platforms (e.g. Windows when files are copied).  Handle both cases.
        if isinstance(clip_img, list):
            # List of file paths — use the first supported image file
            image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tga', '.tiff', '.webp'}
            filepath = None
            for entry in clip_img:
                if isinstance(entry, str) and os.path.splitext(entry)[1].lower() in image_extensions:
                    filepath = entry
                    break

            if filepath is None:
                self.report({'WARNING'}, "No image found in clipboard")
                return {'CANCELLED'}

            item = _load_image_from_filepath(context.scene, filepath)
            if item is None:
                self.report({'ERROR'}, "Failed to load clipboard image")
                return {'CANCELLED'}

            self.report({'INFO'}, "Pasted image from clipboard")
            return {'FINISHED'}

        # PIL Image object — save to a temporary file then load via the helper
        try:
            # Convert to RGBA for PNG compatibility
            if clip_img.mode not in ('RGB', 'RGBA'):
                clip_img = clip_img.convert('RGBA')

            with tempfile.NamedTemporaryFile(
                suffix='.png', prefix='mixar_clipboard_', delete=False
            ) as tmp:
                tmp_path = tmp.name

            clip_img.save(tmp_path, format='PNG')
        except Exception as e:
            self.report({'ERROR'}, f"Failed to save clipboard image: {e}")
            return {'CANCELLED'}

        try:
            item = _load_image_from_filepath(context.scene, tmp_path)
        finally:
            # Clean up temp file regardless of outcome
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if item is None:
            self.report({'ERROR'}, "Failed to load clipboard image")
            return {'CANCELLED'}

        # Rename the Blender image to something descriptive rather than the
        # temp-file name that was just deleted.
        if item.image:
            item.image.name = "Clipboard Image"

        self.report({'INFO'}, "Pasted image from clipboard")
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_add_image,
    MIXIE_OT_moodboard_add_existing_image,
    MIXIE_OT_moodboard_paste_image,
)
