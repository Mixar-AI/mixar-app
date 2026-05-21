# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Color space and colorspace name utilities."""

import bpy
from mathutils import Color

# Import from common module for backward compatibility
from ...common.utils.color_utils import get_noncolor_name, remove_datablock


def is_bl_newer_than(major, minor=0, patch=0):
    """Check if the current Blender version is newer than or equal to the specified version.

    Args:
        major (int): Major version number.
        minor (int, optional): Minor version number. Defaults to 0.
        patch (int, optional): Patch version number. Defaults to 0.

    Returns:
        bool: True if current version >= specified version, False otherwise.
    """
    return bpy.app.version >= (major, minor, patch)




def get_srgb_name():
    """Get the correct sRGB colorspace name for the current Blender version.

    Checks for "sRGB" colorspace name, tries variations like "srgb" prefix, or creates
    a temporary image to determine the default sRGB colorspace name.

    Returns:
        str: The sRGB colorspace name (e.g., "sRGB" or variant).
    """
    names = (
        bpy.types.Image.bl_rna.properties["colorspace_settings"]
        .fixed_type.properties["name"]
        .enum_items.keys()
    )
    if "sRGB" not in names:

        # Try 'srgb' prefix
        for name in names:
            if name.lower().startswith("srgb"):
                return name

        # Check srgb name by creating new 8-bit image
        mpprops = bpy.context.window_manager.mpprops

        if mpprops.custom_srgb_name == "":
            temp_image = bpy.data.images.new(
                "temmmmp", width=1, height=1, alpha=False, float_buffer=False
            )
            mpprops.custom_srgb_name = temp_image.colorspace_settings.name
            remove_datablock(bpy.data.images, temp_image)

        return mpprops.custom_srgb_name

    return "sRGB"


def get_linear_color_name():
    """Get the correct linear colorspace name for the current Blender version.

    Checks for version-appropriate linear colorspace name ("Linear Rec.709" for Blender 4+,
    "Linear" for earlier versions), or searches for any name containing "linear".

    Returns:
        str: The linear colorspace name (e.g., "Linear Rec.709" or "Linear").
    """
    names = (
        bpy.types.Image.bl_rna.properties["colorspace_settings"]
        .fixed_type.properties["name"]
        .enum_items.keys()
    )
    linear_name = "Linear Rec.709" if is_bl_newer_than(4) else "Linear"

    if linear_name not in names:

        # Try to get 'linear' in a name
        for name in names:
            if "linear" in name.lower():
                linear_name = name
                break

    return linear_name


def srgb_to_linear_per_element(e):
    """Convert a single sRGB color element to linear color space.

    Args:
        e (float): The sRGB color element value (0.0-1.0).

    Returns:
        float: The linear color space value.
    """
    if e <= 0.03928:
        return e / 12.92
    else:
        return pow((e + 0.055) / 1.055, 2.4)


def linear_to_srgb_per_element(e):
    """Convert a single linear color element to sRGB color space.

    Args:
        e (float): The linear color element value (0.0-1.0).

    Returns:
        float: The sRGB color space value.
    """
    if e > 0.0031308:
        return 1.055 * (pow(e, (1.0 / 2.4))) - 0.055
    else:
        return 12.92 * e


def srgb_to_linear(inp):
    """Convert sRGB color to linear color space.

    Args:
        inp (float or mathutils.Color): A single float value or Color object to convert.

    Returns:
        float or mathutils.Color: The converted linear color value or Color object.
    """

    if type(inp) == float:
        return srgb_to_linear_per_element(inp)

    elif type(inp) == Color:

        c = inp.copy()

        for i in range(3):
            c[i] = srgb_to_linear_per_element(c[i])

        return c


def linear_to_srgb(inp):
    """Convert linear color to sRGB color space.

    Args:
        inp (float or mathutils.Color): A single float value or Color object to convert.

    Returns:
        float or mathutils.Color: The converted sRGB color value or Color object.
    """

    if type(inp) == float:
        return linear_to_srgb_per_element(inp)

    elif type(inp) == Color:

        c = inp.copy()

        for i in range(3):
            c[i] = linear_to_srgb_per_element(c[i])

        return c
