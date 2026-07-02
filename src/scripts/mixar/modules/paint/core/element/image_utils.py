# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Image and mask color utility functions.

This module contains functions for working with image data and mask colors,
including analyzing image brightness and extracting color ID values.
"""

import numpy
from mathutils import Color

from ...utils.common import get_entity_prop_value


def get_image_mask_base_color(mask, image, mask_index):
    """
    Get the base color for an image mask.

    Analyzes the average pixel brightness of an image to determine whether
    to use black or white as the base color.

    Parameters:
        mask: Mask object
        image: Blender image data
        mask_index: Index of the mask

    Returns:
        tuple: RGBA color tuple, either (0, 0, 0, 1) or (1, 1, 1, 1)
    """

    color = (0, 0, 0, 1)
    pxs = numpy.empty(shape=image.size[0] * image.size[1] * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pxs)
    if numpy.average(pxs) > 0.5:
        color = (1, 1, 1, 1)
    return color


def get_mask_color_id_color(mask):
    """
    Get the color ID color from a mask.

    Extracts the RGB color from the mask's color_id property.

    Parameters:
        mask: Mask object

    Returns:
        Color: RGB color from the mask's color_id property
    """
    val = get_entity_prop_value(mask, 'color_id')
    return Color((val[0], val[1], val[2]))
