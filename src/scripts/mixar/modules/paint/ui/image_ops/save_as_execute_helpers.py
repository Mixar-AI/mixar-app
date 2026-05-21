# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Execute helper functions for Save As Image operator.

This module provides helper functions for the execute method
of the MSaveAsImage operator, handling image saving logic.
"""

import os

import bpy

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...utils.blender_commons import remove_datablock


def prepare_image_for_saving(image, get_linear_color_name, get_srgb_name,
                              set_image_pixels_to_linear, multiply_image_rgb_by_alpha):
    """Prepare image color and alpha settings before saving.

    Handles necessary hacks for float images to save correctly,
    including linear color conversion and alpha multiplication.

    Args:
        image: The Blender image object to prepare.
        get_linear_color_name: Function to get linear colorspace name.
        get_srgb_name: Function to get sRGB colorspace name.
        set_image_pixels_to_linear: Function to convert pixels to linear.
        multiply_image_rgb_by_alpha: Function to multiply RGB by alpha.

    Returns:
        Tuple of (original_colorspace, original_alpha_mode).
    """
    ori_colorspace = image.colorspace_settings.name
    ori_alpha_mode = image.alpha_mode

    if image.is_float:
        # HACK: Set image color to linear first to save linear float image
        if image.colorspace_settings.name == get_linear_color_name():
            set_image_pixels_to_linear(image)

        # HACK: Need to do image operation before saving srgb float image
        if image.colorspace_settings.name == get_srgb_name():
            if image.alpha_mode == "STRAIGHT":
                multiply_image_rgb_by_alpha(image, power=2)

    return ori_colorspace, ori_alpha_mode


def apply_float_image_hacks(image):
    """Apply necessary hacks for float image saving.

    Adjusts colorspace and alpha mode settings for float images
    to ensure they save correctly.

    Args:
        image: The Blender image object to process.

    Returns:
        None
    """
    if image.is_float:
        # HACK: Need to change flip alpha mode before saving float image
        if image.alpha_mode == "PREMUL":
            image.alpha_mode = "STRAIGHT"
        elif image.alpha_mode == "STRAIGHT":
            image.alpha_mode = "PREMUL"


def apply_non_float_image_hacks(image, get_srgb_name):
    """Apply necessary hacks for non-float image saving.

    Sets colorspace to sRGB for non-float images before saving.

    Args:
        image: The Blender image object to process.
        get_srgb_name: Function to get sRGB colorspace name.

    Returns:
        None
    """
    if not image.is_float:
        # HACK: Non float image need to set to srgb when saving
        image.colorspace_settings.name = get_srgb_name()


def save_tiled_image(image, filepath, copy, relative):
    """Save a tiled (UDIM) image using Blender's image save operator.

    Args:
        image: The Blender tiled image object to save.
        filepath: The target filepath.
        copy: Whether to save as a copy.
        relative: Whether to use relative path.

    Returns:
        None
    """
    override = bpy.context.copy()
    override["edit_image"] = image
    with bpy.context.temp_override(**override):
        bpy.ops.image.save_as(
            copy=copy,
            filepath=filepath,
            relative_path=relative,
        )


def create_save_scene_with_settings(operator):
    """Create a temporary scene configured with save settings.

    Creates a new scene with image save settings matching the operator's
    current format and codec settings.

    Args:
        operator: The MSaveAsImage operator instance with format settings.

    Returns:
        The newly created temporary scene object.
    """
    tmpscene = bpy.data.scenes.new("Temp Save As Scene")
    tmpscene.view_settings.view_transform = "Standard"

    # Set settings
    settings = tmpscene.render.image_settings
    settings.file_format = operator.file_format
    settings.color_mode = operator.color_mode
    settings.color_depth = operator.color_depth
    settings.compression = operator.compression
    settings.quality = operator.quality
    if hasattr(settings, "tiff_codec"):
        settings.tiff_codec = operator.tiff_codec
    settings.exr_codec = operator.exr_codec
    settings.jpeg2k_codec = operator.jpeg2k_codec
    settings.use_jpeg2k_cinema_48 = operator.use_jpeg2k_cinema_48
    settings.use_jpeg2k_cinema_preset = operator.use_jpeg2k_cinema_preset
    settings.use_jpeg2k_ycc = operator.use_jpeg2k_ycc
    settings.use_cineon_log = operator.use_cineon_log
    if hasattr(settings, "use_zbuffer"):
        settings.use_zbuffer = operator.use_zbuffer

    return tmpscene


def save_single_image(image, filepath, operator, copy, relative):
    """Save a single (non-tiled) image with format settings.

    Creates a temporary scene, applies operator settings, and saves the image.

    Args:
        image: The Blender image object to save.
        filepath: The target filepath.
        operator: The MSaveAsImage operator instance with format settings.
        copy: Whether to save as a copy.
        relative: Whether to use relative path.

    Returns:
        None
    """
    tmpscene = create_save_scene_with_settings(operator)

    image.save_render(filepath, scene=tmpscene)

    if not copy:
        image.filepath = filepath

        if relative and bpy.data.filepath != "":
            try:
                image.filepath = bpy.path.relpath(image.filepath)
            except Exception as e:
                logger.error(e)
        else:
            image.filepath = bpy.path.abspath(image.filepath)

        image.source = "FILE"
        image.reload()

    # Delete temporary scene
    remove_datablock(bpy.data.scenes, tmpscene)


def restore_image_settings(image, ori_colorspace, ori_alpha_mode):
    """Restore original image settings after saving.

    Args:
        image: The Blender image object.
        ori_colorspace: The original colorspace name to restore.
        ori_alpha_mode: The original alpha mode to restore.

    Returns:
        None
    """
    # Set back colorspace settings
    if image.colorspace_settings.name != ori_colorspace:
        image.colorspace_settings.name = ori_colorspace

    # Set back alpha mode
    if image.alpha_mode != ori_alpha_mode:
        image.alpha_mode = ori_alpha_mode


def cleanup_packed_file(image):
    """Remove packed data from image if present.

    Args:
        image: The Blender image object.

    Returns:
        None
    """
    if image.packed_file:
        image.unpack(method="REMOVE")
