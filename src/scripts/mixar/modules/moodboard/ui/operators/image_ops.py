# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Media Operators

Operators for adding images and videos to the moodboard.
"""

import bpy
from bpy.types import Operator
from bpy.props import (
    StringProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    BoolProperty,
)

from ...core.moodboard_utils import place_new_moodboard_item
from ....common.utils.file_select_utils import file_select_guard, mark_file_select_executed
from ....common.utils.platform_utils import format_shortcut


def _media_filter_glob():
    """Build the file picker filter from Blender's compiled media support."""
    image_extensions = set(getattr(bpy.path, "extensions_image", ()))
    movie_extensions = set(getattr(bpy.path, "extensions_movie", ()))
    return ";".join(f"*{ext}" for ext in sorted(image_extensions | movie_extensions))


def _load_media_from_filepath(scene, filepath, anchor=None):
    """Load an image or movie from filepath and add it to the moodboard.

    Reusable helper that loads the media into Blender, packs still images,
    keeps movies linked to their source path, appends it to the moodboard
    collection, and positions it into visible free space centred on *anchor*
    (canvas coords, e.g. the cursor) or the viewport centre when *anchor* is
    ``None``. Returns the new item on success or None.

    Args:
        scene: The current Blender scene.
        filepath: Absolute path to the image or movie file.
        anchor: Optional ``(x, y)`` canvas coordinates to centre the image on.

    Returns:
        The newly created moodboard media item, or None on failure.
    """
    try:
        img = bpy.data.images.load(filepath, check_existing=True)
        img.colorspace_settings.name = 'sRGB'
        # Blender cannot pack movies into the blend file. Keep their original
        # path so a later video-generation submitter can stream the real bytes.
        if img.source != 'MOVIE':
            img.pack()
        elif img.frame_duration < 1 or img.size[0] <= 0 or img.size[1] <= 0:
            return None
    except Exception:
        return None

    item = scene.mixie_moodboard_images.add()
    item.image = img
    item.scale = 1.0
    item.z_order = len(scene.mixie_moodboard_images) - 1
    place_new_moodboard_item(scene, item, anchor=anchor)
    return item


class MIXIE_OT_moodboard_add_image(Operator):
    """Import image or video file(s) and add them to the moodboard"""

    bl_idname = "mixie.moodboard_add_image"
    bl_label = "Add Media to Moodboard"
    bl_description = (
        f"Import image or video files and add them to the moodboard "
        f"({format_shortcut('I')})"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(
        name="File Path",
        description="Path to the image or video file",
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
        default=_media_filter_glob(),
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

        # Each item is dropped into the nearest free slot near the viewport
        # centre so uploads never stack on top of existing board media.
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

            item = _load_media_from_filepath(scene, filepath)
            if item is None:
                self.report({'WARNING'}, f"Failed to load media: {filepath}")
                continue

            added_count += 1

        if added_count == 0:
            self.report({'ERROR'}, "No media could be loaded")
            return {'CANCELLED'}
        elif added_count == 1:
            self.report({'INFO'}, "Added 1 media item to moodboard")
        else:
            self.report({'INFO'}, f"Added {added_count} media items to moodboard")

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
    """Pick image or video media already loaded in Blender"""

    bl_idname = "mixie.moodboard_add_existing_image"
    bl_label = "Add Existing Media"
    bl_description = "Pick an image or video already loaded in Blender"
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

        # Add to moodboard collection, positioned into visible free space.
        item = scene.mixie_moodboard_images.add()
        item.image = img
        item.scale = 1.0
        item.z_order = len(scene.mixie_moodboard_images) - 1
        place_new_moodboard_item(scene, item)

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

    # Cursor position (canvas coords) captured at invoke so the paste lands
    # under the mouse instead of at the viewport centre.
    cursor_x: FloatProperty(options={'HIDDEN'})
    cursor_y: FloatProperty(options={'HIDDEN'})
    use_cursor: BoolProperty(default=False, options={'HIDDEN'})

    def invoke(self, context, event):
        region = context.region
        view2d = getattr(region, "view2d", None) if region else None
        if view2d is not None:
            self.cursor_x, self.cursor_y = view2d.region_to_view(
                event.mouse_region_x, event.mouse_region_y
            )
            self.use_cursor = True
        else:
            self.use_cursor = False
        return self.execute(context)

    def execute(self, context):
        import os
        import tempfile

        scene = context.scene
        anchor = (self.cursor_x, self.cursor_y) if self.use_cursor else None

        # Primary path: paste from the reliable in-app clipboard (images and text
        # boxes copied from the moodboard) — a lossless duplicate, no round-trip.
        from ...core.moodboard_clipboard import has_clipboard, paste_clipboard
        if has_clipboard():
            pasted = paste_clipboard(scene, anchor=anchor)
            if pasted:
                for area in context.screen.areas:
                    if area.type == 'MIXIE':
                        area.tag_redraw()
                self.report({'INFO'}, f"Pasted {pasted} item{'s' if pasted != 1 else ''}")
                return {'FINISHED'}

        # Fallback: grab an external image from the system clipboard via Pillow.
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

            item = _load_media_from_filepath(context.scene, filepath, anchor=anchor)
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
            item = _load_media_from_filepath(context.scene, tmp_path, anchor=anchor)
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
