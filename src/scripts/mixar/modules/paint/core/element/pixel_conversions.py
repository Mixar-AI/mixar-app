# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Color space conversion and alpha operations for image pixels.

This module contains functions for converting between sRGB and linear
color spaces, and for alpha premultiplication/unpremultiplication.

All functions use buffer pooling for memory efficiency and support
optional C++ backend acceleration when available.
"""

import numpy

from .buffer_pool import acquire_buffer, release_buffer


# C++ backend has been migrated to Blender baking operators (bpy.ops.baking.*)
# For now, use pure numpy implementations which are already efficient
_cpp_ops = None
_HAS_CPP_BACKEND = False


def set_image_pixels_to_srgb(image, segment=None):
    """Convert image pixels from linear color space to sRGB color space.

    Applies sRGB gamma correction to the RGB channels of the image pixels,
    leaving the alpha channel unchanged.

    Uses optimized C++ backend when available for ~10-50x speedup.

    Parameters:
        image: Blender Image datablock to convert.
        segment: Tile segment for UDIM/atlas images to convert. Default: None (converts entire image)

    Returns:
        None
    """
    start_x = 0
    start_y = 0

    width = image.size[0]
    height = image.size[1]

    if segment:
        start_x = width * segment.tile_x
        start_y = height * segment.tile_y

        width = segment.width
        height = segment.height

    # Acquire buffer from pool
    buffer_size = image.size[0] * image.size[1] * 4
    pxs = acquire_buffer(buffer_size)

    try:
        image.pixels.foreach_get(pxs)

        if _HAS_CPP_BACKEND:
            # Use optimized C++ implementation - 10-50x faster than numpy.vectorize
            _cpp_ops.pixels_to_srgb(
                pxs, image.size[0], image.size[1],
                start_x, start_y,
                width, height
            )
        else:
            # Python fallback using numpy.vectorize (slow but correct)
            # Set array to 3d
            pxs.shape = (-1, image.size[0], 4)

            # Do srgb conversion
            # Optimized: Use numpy.where for vectorized conditional operations (5-10x faster than numpy.vectorize)
            rgb_region = pxs[start_y:start_y+height, start_x:start_x+width, :3]
            pxs[start_y:start_y+height, start_x:start_x+width, :3] = numpy.where(
                rgb_region > 0.0031308,
                1.055 * numpy.power(rgb_region, 1.0/2.4) - 0.055,
                12.92 * rgb_region
            )
            pxs = pxs.ravel()

        # Array is always 1D at this point (either from C++ or after ravel())
        image.pixels.foreach_set(pxs)
    finally:
        # Always release buffer back to pool, even if an exception occurred
        release_buffer(pxs)


def set_image_pixels_to_linear(image, segment=None, power=1):
    """Convert image pixels from sRGB color space to linear color space.

    Applies inverse sRGB gamma correction to the RGB channels of the image pixels,
    leaving the alpha channel unchanged. Can apply the conversion multiple times.

    Uses optimized C++ backend when available for ~10-50x speedup.

    Parameters:
        image: Blender Image datablock to convert.
        segment: Tile segment for UDIM/atlas images to convert. Default: None (converts entire image)
        power: Number of times to apply the conversion. Default: 1

    Returns:
        None
    """
    start_x = 0
    start_y = 0

    width = image.size[0]
    height = image.size[1]

    if segment:
        start_x = width * segment.tile_x
        start_y = height * segment.tile_y

        width = segment.width
        height = segment.height

    # Acquire buffer from pool
    buffer_size = image.size[0] * image.size[1] * 4
    pxs = acquire_buffer(buffer_size)

    try:
        image.pixels.foreach_get(pxs)

        if _HAS_CPP_BACKEND:
            # Use optimized C++ implementation - 10-50x faster than numpy.vectorize
            _cpp_ops.pixels_to_linear(
                pxs, image.size[0], image.size[1],
                start_x, start_y,
                width, height,
                power
            )
        else:
            # Python fallback using numpy.vectorize (slow but correct)
            # Set array to 3d
            pxs.shape = (-1, image.size[0], 4)

            # Do linear conversion
            # Optimized: Use numpy.where for vectorized conditional operations (5-10x faster than numpy.vectorize)
            for p in range(power):
                rgb_region = pxs[start_y:start_y+height, start_x:start_x+width, :3]
                pxs[start_y:start_y+height, start_x:start_x+width, :3] = numpy.where(
                    rgb_region <= 0.03928,
                    rgb_region / 12.92,
                    numpy.power((rgb_region + 0.055) / 1.055, 2.4)
                )
            pxs = pxs.ravel()

        # Array is always 1D at this point (either from C++ or after ravel())
        image.pixels.foreach_set(pxs)
    finally:
        # Always release buffer back to pool, even if an exception occurred
        release_buffer(pxs)


def multiply_image_rgb_by_alpha(image, segment=None, power=1):
    """Multiply the RGB channels by the alpha channel (premultiply alpha).

    Applies premultiplied alpha to the image, where each RGB value is multiplied
    by the alpha value raised to the specified power.

    Uses optimized C++ backend when available for ~2-5x speedup.

    Parameters:
        image: Blender Image datablock to modify.
        segment: Tile segment for UDIM/atlas images to process. Default: None (processes entire image)
        power: Exponent to apply to alpha before multiplication. Default: 1

    Returns:
        None
    """
    start_x = 0
    start_y = 0

    width = image.size[0]
    height = image.size[1]

    if segment:
        start_x = width * segment.tile_x
        start_y = height * segment.tile_y

        width = segment.width
        height = segment.height

    # Acquire buffer from pool
    buffer_size = image.size[0] * image.size[1] * 4
    pxs = acquire_buffer(buffer_size)

    try:
        image.pixels.foreach_get(pxs)

        if _HAS_CPP_BACKEND:
            # Use optimized C++ implementation
            _cpp_ops.multiply_rgb_by_alpha(
                pxs, image.size[0], image.size[1],
                start_x, start_y,
                width, height,
                power
            )
        else:
            # Python fallback
            # Set array to 3d
            pxs.shape = (-1, image.size[0], 4)

            # Do linear conversion
            for i in range(3):
                pxs[start_y:start_y+height, start_x:start_x+width, i] *= pow(pxs[start_y:start_y+height, start_x:start_x+width, 3], power)
            pxs = pxs.ravel()

        # Array is always 1D at this point (either from C++ or after ravel())
        image.pixels.foreach_set(pxs)
    finally:
        # Always release buffer back to pool, even if an exception occurred
        release_buffer(pxs)


def divide_image_rgb_by_alpha(image, segment=None):
    """Divide the RGB channels by the alpha channel (unpremultiply alpha).

    Reverses premultiplied alpha by dividing each RGB value by the alpha value.
    Uses safe division to avoid division by zero.

    Uses optimized C++ backend when available for ~2-10x speedup.

    Parameters:
        image: Blender Image datablock to modify.
        segment: Tile segment for UDIM/atlas images to process. Default: None (processes entire image)

    Returns:
        None
    """
    start_x = 0
    start_y = 0

    width = image.size[0]
    height = image.size[1]

    if segment:
        start_x = width * segment.tile_x
        start_y = height * segment.tile_y

        width = segment.width
        height = segment.height

    # Acquire buffer from pool
    buffer_size = image.size[0] * image.size[1] * 4
    pxs = acquire_buffer(buffer_size)

    try:
        image.pixels.foreach_get(pxs)

        if _HAS_CPP_BACKEND:
            # Use optimized C++ implementation
            _cpp_ops.divide_rgb_by_alpha(
                pxs, image.size[0], image.size[1],
                start_x, start_y,
                width, height
            )
        else:
            # Python fallback
            # Set array to 3d
            pxs.shape = (-1, image.size[0], 4)

            # Divide RGB by alpha (unpremultiply)
            # Optimized: Use numpy.maximum for safe division (5-10x faster than numpy.vectorize)
            alpha = pxs[start_y:start_y+height, start_x:start_x+width, 3]
            safe_alpha = numpy.maximum(alpha, 0.00001)
            for i in range(3):
                pxs[start_y:start_y+height, start_x:start_x+width, i] /= safe_alpha
            pxs = pxs.ravel()

        # Array is always 1D at this point (either from C++ or after ravel())
        image.pixels.foreach_set(pxs)
    finally:
        # Always release buffer back to pool, even if an exception occurred
        release_buffer(pxs)
