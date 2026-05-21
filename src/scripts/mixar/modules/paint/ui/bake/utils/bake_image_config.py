# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image configuration functions for entity baking - colorspace, color, and image creation."""

import bpy

from ....utils.blender_commons import (
    get_noncolor_name,
    get_srgb_name,
)
from ...udim.udim_operators_helper import fill_tile
from ...udim.udim_utils_io import initial_pack_udim


def get_image_colorspace(bprops, bake_type, root_ch=None):
    """Determine the colorspace for the baked image.

    Parameters:
        bprops: Bake properties
        bake_type: Bake type string
        root_ch: Root channel (for OTHER_OBJECT_CHANNELS)

    Returns:
        str: Colorspace name
    """
    colorspace = get_srgb_name()

    if bprops.type == "OTHER_OBJECT_CHANNELS" and root_ch:
        colorspace = (
            get_noncolor_name()
            if root_ch.colorspace == "LINEAR" or root_ch.type == "VALUE"
            else get_srgb_name()
        )
    elif bprops.type in {
        "BEVEL_NORMAL",
        "MULTIRES_NORMAL",
        "OTHER_OBJECT_NORMAL",
        "OBJECT_SPACE_NORMAL",
        "AO",
        "POINTINESS",
        "CAVITY",
        "DUST",
        "PAINT_BASE",
        "BEVEL_MASK",
        "POSITION",
    }:
        colorspace = get_noncolor_name()

    # Using float image will always make the image linear/non-color
    if bprops.hdr:
        colorspace = get_noncolor_name()

    return colorspace


def get_base_color(bprops, bake_type):
    """Get the base color for the baked image.

    Parameters:
        bprops: Bake properties
        bake_type: Bake type string

    Returns:
        list: RGBA color as list of 4 floats
    """
    if bprops.type == "AO":
        color = [1.0, 1.0, 1.0, 1.0]
    elif bake_type in {"NORMAL", "NORMALS"}:
        color = [0.5, 0.5, 1.0, 1.0]
    elif bprops.type == "FLOW":
        color = [0.5, 0.5, 0.0, 1.0]
    else:
        color = [0.5, 0.5, 0.5, 1.0]

    # Make image transparent if its baked from other objects
    if bprops.type.startswith("OTHER_OBJECT_"):
        color = [0.0, 0.0, 0.0, 0.0]

    return color


def create_bake_image(bprops, image_name, colorspace, color, width, height, tilenums):
    """Create a new image for baking.

    Parameters:
        bprops: Bake properties
        image_name: Name for the image
        colorspace: Colorspace for the image
        color: Base color
        width: Image width
        height: Image height
        tilenums: List of UDIM tile numbers

    Returns:
        Image: Created Blender image
    """
    if bprops.use_udim:
        image = bpy.data.images.new(
            name=image_name,
            width=width,
            height=height,
            alpha=True,
            float_buffer=bprops.hdr,
            tiled=True,
        )

        # Fill tiles
        for tilenum in tilenums:
            fill_tile(image, tilenum, color, width, height)
        initial_pack_udim(image, color)

        # Remember base color
        image.yui.base_color = color
    else:
        image = bpy.data.images.new(
            name=image_name,
            width=width,
            height=height,
            alpha=True,
            float_buffer=bprops.hdr,
        )

    image.generated_color = color
    image.colorspace_settings.name = colorspace

    return image
