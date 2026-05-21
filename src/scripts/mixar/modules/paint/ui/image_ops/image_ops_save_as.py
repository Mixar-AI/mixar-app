# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Save As Image operator with format options.

This module provides the MSaveAsImage operator for saving images with
configurable format, color mode, and compression settings.

The UI drawing logic has been extracted to save_as_ui_helpers.py
and execute helpers have been extracted to save_as_execute_helpers.py.
"""

import os

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty
from bpy_extras.io_utils import ExportHelper

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.element.update_image import (
    multiply_image_rgb_by_alpha,
    set_image_pixels_to_linear,
)
from ...core.node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import (
    duplicate_image,
    get_linear_color_name,
    get_srgb_name,
    remove_datablock,
)
from ...utils.common import get_addon_title
from ..other.base_operator import FileSelectOptions
from .image_ops_operators_helper import (
    color_depth_items,
    color_mode_items,
    get_file_format_items,
    pack_image,
    update_save_as_file_format,
)
from .image_ops_utils import format_extensions
from .save_as_ui_helpers import draw_save_as_panel
from .save_as_execute_helpers import (
    prepare_image_for_saving,
    apply_float_image_hacks,
    apply_non_float_image_hacks,
    save_tiled_image,
    save_single_image,
    restore_image_settings,
    cleanup_packed_file,
)


class MSaveAsImage(bpy.types.Operator, ExportHelper, FileSelectOptions):
    """Save As Image"""

    bl_idname = "wm.m_save_as_image"
    bl_label = "Save As Image"
    bl_options = {"REGISTER", "UNDO"}

    file_format: EnumProperty(
        name="File Format",
        items=get_file_format_items(),
        default="PNG",
        update=update_save_as_file_format,
    )

    copy: BoolProperty(
        name="Copy",
        description="Create a new image file without modifying the current image in Blender",
        default=False,
    )

    relative: BoolProperty(
        name="Relative Path",
        description="Select the file relative to the blend file",
        default=True,
    )

    color_mode: EnumProperty(name="Color Mode", items=color_mode_items)

    color_depth: EnumProperty(name="Color Depth", items=color_depth_items)

    tiff_codec: EnumProperty(
        name="Compression",
        items=(
            ("NONE", "None", ""),
            ("DEFLATE", "Deflate", ""),
            ("LZW", "LZW", ""),
            ("PACKBITS", "Pack Bits", ""),
        ),
        default="DEFLATE",
    )

    exr_codec: EnumProperty(
        name="Codec",
        items=(
            ("NONE", "None", ""),
            ("PXR24", "Pxr24 (lossy)", ""),
            ("ZIP", "ZIP (lossless)", ""),
            ("PIZ", "PIZ (lossless)", ""),
            ("RLE", "RLE (lossless)", ""),
            ("ZIPS", "ZIPS (lossless)", ""),
            ("DWAA", "DWAA (lossy)", ""),
        ),
        default="ZIP",
    )

    jpeg2k_codec: EnumProperty(
        name="Codec",
        items=(
            ("JP2", "JP2", ""),
            ("J2K", "J2K", ""),
        ),
        default="JP2",
    )

    compression: IntProperty(
        name="Compression", default=15, min=0, max=100, subtype="PERCENTAGE"
    )
    quality: IntProperty(
        name="Quality", default=90, min=0, max=100, subtype="PERCENTAGE"
    )

    use_jpeg2k_cinema_48: BoolProperty(name="Cinema 48", default=False)
    use_jpeg2k_cinema_preset: BoolProperty(name="Cinema", default=False)
    use_jpeg2k_ycc: BoolProperty(name="YCC", default=False)
    use_cineon_log: BoolProperty(name="Log", default=False)
    use_zbuffer: BoolProperty(name="Log", default=False)

    # Flag for float image
    is_float: BoolProperty(default=False)

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed.

        Args:
            context: The Blender context.

        Returns:
            True if context has an image and active MPaint node, False otherwise.
        """
        return hasattr(context, "image") and context.image and get_active_mpaint_node()

    def draw(self, context):
        """Draw the operator's UI panel with file format and save options.

        Args:
            context: The Blender context.

        Returns:
            None
        """
        draw_save_as_panel(self.layout, self)

    def invoke(self, context, event):
        """Initialize the file browser with current image settings.

        Args:
            context: The Blender context.
            event: The Blender event that triggered the operator.

        Returns:
            Set containing 'RUNNING_MODAL' to wait for user input,
            or result of execute() for image atlas.
        """
        self.use_filter_image = True

        file_ext = format_extensions[self.file_format]
        filename = bpy.path.basename(context.image.filepath)

        # Set filepath
        if context.image.filepath == "" or filename == "" or ".<UDIM>." in filename:
            mp = get_active_mpaint_node().node_tree.mp
            name = context.image.name
            name += ".<UDIM>" if ".<UDIM>." in filename else ""

            # Remove addon title from the file names
            if mp.use_baked and name.startswith(get_addon_title() + " "):
                name = name.replace(get_addon_title() + " ", "")

            if not name.endswith(file_ext):
                name += file_ext
            self.filepath = name
        else:
            self.filepath = context.image.filepath

        # Pass context.image to self
        self.image = context.image

        if self.image.yia.is_image_atlas:
            return self.execute(context)

        # Set default color mode
        if self.file_format in {"BMP", "JPEG", "CINEON", "HDR"}:
            self.color_mode = "RGB"
        else:
            self.color_mode = "RGBA"

        if self.image.is_float:
            self.is_float = True
            if self.color_depth == "8":
                self.color_depth = "16"
        else:
            self.is_float = False

        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def check(self, context):
        """Update the file extension when the file format changes.

        Args:
            context: The Blender context.

        Returns:
            True if file extension was changed, False otherwise.
        """
        change_ext = False
        filepath = self.filepath
        file_ext = format_extensions[self.file_format]

        if bpy.path.basename(filepath):
            # Check current extensions
            for form, ext in format_extensions.items():
                if filepath.endswith(ext):
                    filepath = filepath.replace(ext, "")
                    break

            filepath = bpy.path.ensure_ext(filepath, file_ext)

            if filepath != self.filepath:
                self.filepath = filepath
                change_ext = True

        return change_ext

    def unpack_image(self, context):
        """Unpack the image to disk for saving operations.

        Args:
            context: The Blender context.

        Returns:
            None
        """
        image = self.image

        # Get blender default unpack directory
        self.default_dir = os.path.join(
            os.path.abspath(bpy.path.abspath("//")), "textures"
        )

        # Check if default directory is available or not, delete later if not found now
        self.default_dir_found = os.path.isdir(self.default_dir)

        # Blender always unpack at \\textures\file.ext
        if image.filepath == "":
            self.default_filepath = os.path.join(self.default_dir, image.name)
        else:
            self.default_filepath = os.path.join(
                self.default_dir, bpy.path.basename(image.filepath)
            )

        # Check if file with default path is already available
        self.temp_path = ""
        if (
            os.path.isfile(self.default_filepath)
            and self.default_filepath != self.filepath
        ):
            self.temp_path = os.path.join(self.default_dir, "__TEMP__")
            os.rename(self.default_filepath, self.temp_path)

        # Unpack the file
        image.unpack()
        self.unpacked_path = bpy.path.abspath(image.filepath)

        # HACK: Unpacked path sometimes has inconsistent backslash
        folder, file = os.path.split(self.unpacked_path)
        self.unpacked_path = os.path.join(folder, file)

    def remove_unpacked_image(self, context):
        """Clean up temporary unpacked image files.

        Args:
            context: The Blender context.

        Returns:
            None
        """
        image = self.image

        # Remove unpacked file
        if self.filepath != self.unpacked_path:
            if image.source == "TILED":
                for tile in image.tiles:
                    unpacked_path = self.unpacked_path.replace(
                        "<UDIM>", str(tile.number)
                    )
                    try:
                        os.remove(unpacked_path)
                    except Exception as e:
                        logger.error(e)
            else:
                os.remove(self.unpacked_path)

        # Rename back temporary file
        if self.temp_path != "":
            if self.temp_path != self.filepath:
                os.rename(self.temp_path, self.default_filepath)
            else:
                os.remove(self.temp_path)

        # Delete default directory if not found before
        if not self.default_dir_found:
            os.rmdir(self.default_dir)

    def execute(self, context):
        """Save the image to the specified filepath with selected format and settings.

        Args:
            context: The Blender context.

        Returns:
            Set containing 'FINISHED' on success or 'CANCELLED' if image is an atlas.
        """
        image = self.image

        if image.yia.is_image_atlas:
            self.report({"ERROR"}, "Unpacking image atlas is not supported yet!")
            return {"CANCELLED"}

        if self.copy:
            image = self.image = duplicate_image(image, ondisk_duplicate=False)

        # Prepare image and remember original settings
        ori_colorspace, ori_alpha_mode = prepare_image_for_saving(
            image,
            get_linear_color_name,
            get_srgb_name,
            set_image_pixels_to_linear,
            multiply_image_rgb_by_alpha,
        )

        # Need to pack first to save the image
        if image.is_dirty:
            pack_image(image)

        # Apply image hacks based on float status
        unpacked_to_disk = False
        if not image.is_dirty:
            apply_non_float_image_hacks(image, get_srgb_name)
            apply_float_image_hacks(image)

        # Save image
        if image.source == "TILED":
            save_tiled_image(image, self.filepath, self.copy, self.relative)
        else:
            save_single_image(
                image, self.filepath, self, self.copy, self.relative
            )

        # Remove unpacked file
        if unpacked_to_disk:
            self.remove_unpacked_image(context)

        # Remove packed flag
        cleanup_packed_file(image)

        # Restore original settings
        restore_image_settings(image, ori_colorspace, ori_alpha_mode)

        # Delete copied image
        if self.copy:
            remove_datablock(bpy.data.images, image)

        return {"FINISHED"}


# Re-export helper functions for backward compatibility
from .save_as_ui_helpers import (
    draw_labeled_row,
    draw_file_format_section,
    draw_save_options_section,
    draw_save_as_panel,
)
from .save_as_execute_helpers import (
    prepare_image_for_saving,
    apply_float_image_hacks,
    apply_non_float_image_hacks,
    save_tiled_image,
    save_single_image,
    create_save_scene_with_settings,
    restore_image_settings,
    cleanup_packed_file,
)


# Classes for registration
classes = (MSaveAsImage,)
