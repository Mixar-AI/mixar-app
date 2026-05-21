# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Float image handling helper functions.

This module provides functions for processing and saving float images,
including color adjustment hacks for preserving color accuracy.
"""

import os
import tempfile

import bpy

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...core.element.update_image import (
    divide_image_rgb_by_alpha,
    multiply_image_rgb_by_alpha,
    set_image_pixels_to_srgb,
)
from ...utils.blender_commons import (
    get_linear_color_name,
    get_noncolor_name,
    get_srgb_name,
    remove_datablock,
)
from .image_ops_utils import format_extensions, pack_image


def preserve_float_color_hack_before_saving(image):
    """Apply color adjustments to float images before saving to preserve color accuracy.

    Performs alpha multiplication/division on float images based on their alpha mode
    and colorspace to ensure colors are preserved correctly when saved to disk.

    Args:
        image: The Blender image object to process.

    Returns:
        None
    """
    if not image.is_float:
        return

    # HACK: Need more calculation for image saved using straight alpha
    if image.alpha_mode == "STRAIGHT":
        if image.colorspace_settings.name == get_srgb_name():
            multiply_image_rgb_by_alpha(image)
        elif image.colorspace_settings.name == get_linear_color_name():
            divide_image_rgb_by_alpha(image)

    # TODO: Saved SRGB Straight still has black glitch around alpha transition
    # and saved SRGB Premultiplied still looks horrible


def save_float_image(image):
    """Save a float image to disk with proper format settings.

    Creates a temporary scene to configure render settings based on the image file
    extension, packs dirty images, saves the image using render output, and cleans up.

    Args:
        image: The Blender float image object to save.

    Returns:
        None
    """

    # NOTE: This hack function is probably not a good idea since it uses a lot of assumption
    # preserve_float_color_hack_before_saving(image)

    # Remembers
    original_path = image.filepath
    ori_colorspace = image.colorspace_settings.name

    # Create temporary scene
    tmpscene = bpy.data.scenes.new("Temp Scene")

    # Set settings
    settings = tmpscene.render.image_settings

    # Check current extensions
    for form, ext in format_extensions.items():
        if image.filepath.endswith(ext):
            if form == "OPEN_EXR_MULTILAYER" and image.type != "MULTILAYER":
                continue
            settings.file_format = form
            break

    if settings.file_format in {"OPEN_EXR", "OPEN_EXR_MULTILAYER"}:
        settings.exr_codec = "ZIP"
        settings.color_depth = "32"
    elif settings.file_format in {"PNG", "TIFF"}:
        settings.color_depth = "16"

    # Need to pack first to save the image
    if image.is_dirty:
        pack_image(image)

    full_path = bpy.path.abspath(image.filepath)
    image.save_render(full_path, scene=tmpscene)
    # HACK: If image still dirty after saving, save using standard save method
    if image.is_dirty:
        image.save()
    image.source = "FILE"

    # Delete temporary scene
    remove_datablock(bpy.data.scenes, tmpscene)

    # Set back colorspace
    if image.colorspace_settings.name != ori_colorspace:
        image.colorspace_settings.name = ori_colorspace

    # Remove packed flag
    if image.packed_file:
        image.unpack(method="REMOVE")

    # Reload image
    image.reload()


def pack_float_image_27x(image):
    """Pack a float image for Blender 2.7x compatibility.

    Saves the float image to a temporary file with appropriate settings, then packs
    it into the blend file. This function handles legacy Blender 2.7x behavior.

    Args:
        image: The Blender float image object to pack.

    Returns:
        None
    """
    original_path = image.filepath

    # Create temporary scene
    tmpscene = bpy.data.scenes.new("Temp Scene")

    # Set settings
    settings = tmpscene.render.image_settings

    # if image.filepath == '':
    # if original_path == '':
    if bpy.path.basename(original_path) == "":
        if hasattr(image, "use_alpha") and image.use_alpha:
            settings.file_format = "PNG"
            settings.color_depth = "16"
            # settings.color_mode = 'RGBA'
            settings.compression = 15
            image_name = "_temp_image.png"
        else:
            settings.file_format = "HDR"
            settings.color_depth = "32"
            image_name = "_temp_image.hdr"
    else:
        settings.file_format = image.file_format
        if image.file_format in {"CINEON", "DPX"}:
            settings.color_depth = "10"
        elif image.file_format in {"TIFF"}:
            settings.color_depth = "16"
        elif image.file_format in {"HDR", "OPEN_EXR_MULTILAYER", "OPEN_EXR"}:
            settings.color_depth = "32"
        else:
            settings.color_depth = "16"
        image_name = bpy.path.basename(original_path)

    temp_filepath = os.path.join(tempfile.gettempdir(), image_name)

    # Save image
    image.save_render(temp_filepath, scene=tmpscene)
    image.source = "FILE"
    image.filepath = temp_filepath
    if image.file_format == "PNG":
        image.colorspace_settings.name = get_srgb_name()
    else:
        image.colorspace_settings.name = get_noncolor_name()

    # Delete temporary scene
    remove_datablock(bpy.data.scenes, tmpscene)

    # Pack image
    image.pack()

    # image.reload()

    # Bring back to original path
    image.filepath = original_path
    os.remove(temp_filepath)


def preserve_float_color_hack_before_packing(image):
    """Apply color adjustments to float images before packing to preserve color accuracy.

    Performs alpha division and sRGB conversion on float images based on their alpha
    mode and colorspace to ensure colors are preserved correctly when packed.

    Args:
        image: The Blender image object to process.

    Returns:
        None
    """
    if not image.is_float:
        return

    # HACK: Divide by alpha if using straight alpha
    if image.alpha_mode == "STRAIGHT":
        divide_image_rgb_by_alpha(image)

    # Check if image is using srgb colorspace
    if image.colorspace_settings.name == get_srgb_name():

        # HACK: Multiply by alpha if using premultiplied alpha
        if image.alpha_mode == "PREMUL":
            multiply_image_rgb_by_alpha(image)

        # HACK: If float image use srgb colorspace, it need to be converted to srgb first before packing
        set_image_pixels_to_srgb(image)
