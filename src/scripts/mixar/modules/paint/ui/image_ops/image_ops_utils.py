# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy

from ...core.element.update_image import (
    copy_image_pixels,
    copy_image_pixels_with_conversion,
    replace_image,
)
from ...utils.blender_commons import get_linear_color_name, get_srgb_name
from ..udim.udim_utils import copy_udim_pixels, fill_tile, initial_pack_udim

format_extensions = {
    "BMP": ".bmp",
    "IRIS": ".rgb",
    "PNG": ".png",
    "JPEG": ".jpg",
    "JPEG2000": ".jp2",
    "TARGA": ".tga",
    "TARGA_RAW": ".tga",
    "CINEON": ".cin",
    "DPX": ".dpx",
    "OPEN_EXR_MULTILAYER": ".exr",
    "OPEN_EXR": ".exr",
    "HDR": ".hdr",
    "TIFF": ".tif",
    "WEBP": ".webp",
}


def toggle_image_bit_depth(
    image, no_copy=False, force_srgb=False, convert_colorspace=False
):
    """Toggle the bit depth of an image between 8-bit and 32-bit float.

    Creates a new image with the opposite bit depth of the original image and copies
    the pixel data. The original image is replaced with the new one.

    Args:
        image: The Blender image object to convert.
        no_copy (bool): If True, skip copying pixel data. Defaults to False.
        force_srgb (bool): If True, force the new image to use sRGB colorspace. Defaults to False.
        convert_colorspace (bool): If True, convert colorspace based on bit depth
            (float uses linear/PREMUL, byte uses sRGB/STRAIGHT). Defaults to False.

    Returns:
        The new image object with converted bit depth.
    """

    if image.yua.is_udim_atlas or image.yia.is_image_atlas:
        return

    # Create new image based on original image but with different bit depth
    if image.source == "TILED":

        # Make sure image has filepath
        if image.filepath == "":
            initial_pack_udim(image)

        tilenums = [tile.number for tile in image.tiles]
        new_image = bpy.data.images.new(
            image.name,
            width=image.size[0],
            height=image.size[1],
            alpha=True,
            float_buffer=not image.is_float,
            tiled=True,
        )

        # Fill tiles
        color = (0, 0, 0, 0)
        for tilenum in tilenums:
            ori_width = image.tiles.get(tilenum).size[0]
            ori_height = image.tiles.get(tilenum).size[1]
            fill_tile(new_image, tilenum, color, ori_width, ori_height)
        initial_pack_udim(new_image, color)

    else:
        new_image = bpy.data.images.new(
            image.name,
            width=image.size[0],
            height=image.size[1],
            alpha=True,
            float_buffer=not image.is_float,
        )

        if image.filepath != "":
            new_image.filepath = image.filepath

    if force_srgb:
        new_image.colorspace_settings.name = get_srgb_name()
    elif convert_colorspace:
        if new_image.is_float:
            # Float image will use linear color and premultiplied alpha
            new_image.colorspace_settings.name = get_linear_color_name()
            new_image.alpha_mode = "PREMUL"
        else:
            # Byte image will use srgb color and straight alpha
            new_image.colorspace_settings.name = get_srgb_name()
            new_image.alpha_mode = "STRAIGHT"
    else:
        new_image.colorspace_settings.name = image.colorspace_settings.name

    # Copy image pixels
    if no_copy == False:
        if image.source == "TILED":
            copy_udim_pixels(image, new_image, convert_colorspace=convert_colorspace)
        else:
            if convert_colorspace:
                copy_image_pixels_with_conversion(image, new_image)
            else:
                copy_image_pixels(image, new_image)

    # Pack image
    if image.source != "TILED" and image.packed_file:
        pack_image(new_image, reload_float=True)

    # Replace image
    replace_image(image, new_image)

    return new_image


def pack_image(image, reload_float=False):
    """Pack an image into the blend file.

    Packs the image data into the blend file and optionally reloads float images
    to ensure they display correctly.

    Args:
        image: The Blender image object to pack.
        reload_float (bool): If True, reload the image after packing if it's a float image.
            Defaults to False.

    Returns:
        None
    """

    # NOTE: This hack function is probably not a good idea since it uses a lot of assumption
    # preserve_float_color_hack_before_packing(image)

    image.pack()

    # HACK: Some operation need Float image to be reloaded to be showed correctly
    if image.is_float and reload_float:
        image.reload()
