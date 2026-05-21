# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pixel manipulation functions for image processing.

This module contains functions for copying, converting, and manipulating
pixel data in Blender images. It includes support for tile segments,
color space conversions, and alpha channel operations.

Memory Optimization:
    This module uses buffer pooling to reduce memory allocation overhead.
    Buffers are reused across operations, significantly reducing GC pressure
    and allocation time for repeated operations on same-sized images.

    Use clear_buffer_pool() to free pooled memory when needed.
    See buffer_pool.py for detailed lifecycle documentation.
"""

import numpy

from .....config.logging_config import get_logger
logger = get_logger(__name__)

try:
    import bpy
    _HAS_BPY = True
except ImportError:
    _HAS_BPY = False

# Import buffer pool functions
from .buffer_pool import (
    acquire_buffer,
    release_buffer,
    clear_buffer_pool,
    get_pool_stats,
)

# Import color conversion functions
from .pixel_conversions import (
    set_image_pixels_to_srgb,
    set_image_pixels_to_linear,
    multiply_image_rgb_by_alpha,
    divide_image_rgb_by_alpha,
)

# Re-export all public functions for backward compatibility
__all__ = [
    # Buffer pool
    'clear_buffer_pool',
    'get_pool_stats',
    # Pixel operations
    'copy_image_channel_pixels',
    'copy_image_pixels',
    'set_image_pixels',
    'copy_image_pixels_with_conversion',
    # Color conversions (re-exported)
    'set_image_pixels_to_srgb',
    'set_image_pixels_to_linear',
    'multiply_image_rgb_by_alpha',
    'divide_image_rgb_by_alpha',
]

def _check_cpp_backend():
    """Check if C++ baking operators are available."""
    if not _HAS_BPY:
        return False
    try:
        return hasattr(bpy.ops, 'baking') and hasattr(bpy.ops.baking, 'copy_image_pixels')
    except Exception:
        return False


_HAS_CPP_BACKEND = _check_cpp_backend()

# Log backend status at module load
if _HAS_CPP_BACKEND:
    logger.info("C++ baking operators available - using optimized backend")
else:
    logger.info("C++ baking operators not available - using NumPy fallback")


def copy_image_channel_pixels(src, dest, src_idx=0, dest_idx=0, segment=None, segment_src=None, invert_value=False):
    """Copy a specific color channel from source image to destination image.

    Copies pixel data from one channel (R, G, B, or A) of the source image to a
    specific channel of the destination image. Supports tile segments and value inversion.

    Uses optimized C++ backend when available for ~2-5x speedup.

    Parameters:
        src: Source Blender Image datablock.
        dest: Destination Blender Image datablock.
        src_idx: Source channel index (0=R, 1=G, 2=B, 3=A). Default: 0
        dest_idx: Destination channel index (0=R, 1=G, 2=B, 3=A). Default: 0
        segment: Destination tile segment for UDIM/atlas images. Default: None
        segment_src: Source tile segment for UDIM/atlas images. Default: None
        invert_value: If True, inverts the channel values (1.0 - value). Default: False

    Returns:
        None
    """
    # Guard against empty images
    if src.size[0] == 0 or src.size[1] == 0:
        return
    if dest.size[0] == 0 or dest.size[1] == 0:
        return

    start_x = 0
    start_y = 0

    src_start_x = 0
    src_start_y = 0

    width = src.size[0]
    height = src.size[1]

    if segment:
        # Use segment dimensions for tile offset calculation (consistent with copy_image_pixels)
        start_x = segment.width * segment.tile_x
        start_y = segment.height * segment.tile_y

    if segment_src:
        width = segment_src.width
        height = segment_src.height

        src_start_x = width * segment_src.tile_x
        src_start_y = height * segment_src.tile_y

    if _HAS_CPP_BACKEND:
        # Use optimized C++ baking operator
        logger.debug("copy_image_channel_pixels: using C++ backend")
        bpy.ops.baking.copy_image_channel_pixels(
            src_image=src,
            dest_image=dest,
            src_width=src.size[0],
            src_height=src.size[1],
            dest_width=dest.size[0],
            dest_height=dest.size[1],
            src_idx=src_idx,
            dest_idx=dest_idx,
            start_x=start_x,
            start_y=start_y,
            src_start_x=src_start_x,
            src_start_y=src_start_y,
            copy_width=width,
            copy_height=height,
            invert_value=invert_value
        )
    else:
        # Python/NumPy fallback
        logger.debug("copy_image_channel_pixels: using NumPy fallback")
        dest_size = dest.size[0] * dest.size[1] * 4
        src_size = src.size[0] * src.size[1] * 4
        dest_pxs = acquire_buffer(dest_size)
        src_pxs = acquire_buffer(src_size)

        try:
            dest.pixels.foreach_get(dest_pxs)
            src.pixels.foreach_get(src_pxs)

            # Set array to 3d
            dest_pxs.shape = (-1, dest.size[0], 4)
            src_pxs.shape = (-1, src.size[0], 4)

            # Copy to selected channel
            if invert_value:
                dest_pxs[start_y:start_y+height, start_x:start_x+width][::, ::, dest_idx] = 1.0 - src_pxs[src_start_y:src_start_y+height, src_start_x:src_start_x+width][::, ::, src_idx]
            else:
                dest_pxs[start_y:start_y+height, start_x:start_x+width][::, ::, dest_idx] = src_pxs[src_start_y:src_start_y+height, src_start_x:src_start_x+width][::, ::, src_idx]
            dest_pxs = dest_pxs.ravel()

            dest.pixels.foreach_set(dest_pxs)
        finally:
            # Always release buffers back to pool, even if an exception occurred
            release_buffer(dest_pxs)
            release_buffer(src_pxs)


def copy_image_pixels(src, dest, segment=None, segment_src=None):
    """Copy all pixel data from source image to destination image.

    Copies the entire pixel buffer from the source image to the destination image.
    Supports tile segments for UDIM/atlas workflows.

    Uses optimized C++ backend when available for ~2-10x speedup.

    Parameters:
        src: Source Blender Image datablock.
        dest: Destination Blender Image datablock.
        segment: Destination tile segment for UDIM/atlas images. Default: None
        segment_src: Source tile segment for UDIM/atlas images. Default: None

    Returns:
        None
    """
    # Guard against empty images
    if src.size[0] == 0 or src.size[1] == 0:
        return
    if dest.size[0] == 0 or dest.size[1] == 0:
        return

    start_x = 0
    start_y = 0

    src_start_x = 0
    src_start_y = 0

    width = src.size[0]
    height = src.size[1]

    if segment:
        start_x = segment.width * segment.tile_x
        start_y = segment.height * segment.tile_y

    if segment_src:
        width = segment_src.width
        height = segment_src.height

        src_start_x = width * segment_src.tile_x
        src_start_y = height * segment_src.tile_y

    if _HAS_CPP_BACKEND:
        # Use optimized C++ baking operator
        logger.debug("copy_image_pixels: using C++ backend")
        bpy.ops.baking.copy_image_pixels(
            src_image=src,
            dest_image=dest,
            src_width=src.size[0],
            src_height=src.size[1],
            dest_width=dest.size[0],
            dest_height=dest.size[1],
            start_x=start_x,
            start_y=start_y,
            src_start_x=src_start_x,
            src_start_y=src_start_y,
            copy_width=width,
            copy_height=height
        )
        # Update image to refresh GPU texture
        dest.update()
    else:
        # Python/NumPy fallback
        logger.debug("copy_image_pixels: using NumPy fallback")
        dest_size = dest.size[0] * dest.size[1] * 4
        src_size = src.size[0] * src.size[1] * 4
        target_pxs = acquire_buffer(dest_size)
        source_pxs = acquire_buffer(src_size)

        try:
            dest.pixels.foreach_get(target_pxs)
            src.pixels.foreach_get(source_pxs)

            # Set array to 3d
            target_pxs.shape = (-1, dest.size[0], 4)
            source_pxs.shape = (-1, src.size[0], 4)

            target_pxs[start_y:start_y+height, start_x:start_x+width] = source_pxs[src_start_y:src_start_y+height, src_start_x:src_start_x+width]
            target_pxs = target_pxs.ravel()

            dest.pixels.foreach_set(target_pxs)

            # Update image to refresh GPU texture
            # NOTE: This is intentionally inside the try block. The finally block
            # ensures buffers are released even if update() fails.
            dest.update()
        finally:
            # Always release buffers back to pool, even if an exception occurred
            release_buffer(target_pxs)
            release_buffer(source_pxs)


def set_image_pixels(image, color, segment=None):
    """Set all pixels in an image to a specific color.

    Fills the entire image or a specific tile segment with a uniform color value.

    Uses optimized C++ backend when available for ~2-5x speedup.

    Parameters:
        image: Blender Image datablock to modify.
        color: RGBA color tuple/list to fill the image with (e.g., [1.0, 0.0, 0.0, 1.0]).
        segment: Tile segment for UDIM/atlas images to fill. Default: None (fills entire image)

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

    if _HAS_CPP_BACKEND:
        # Use optimized C++ baking operator
        logger.debug("set_image_pixels: using C++ backend")
        bpy.ops.baking.set_image_pixels(
            image=image,
            width=image.size[0],
            height=image.size[1],
            start_x=start_x,
            start_y=start_y,
            fill_width=width,
            fill_height=height,
            color=color
        )
    else:
        # Python/NumPy fallback
        logger.debug("set_image_pixels: using NumPy fallback")
        buffer_size = image.size[0] * image.size[1] * 4
        pxs = acquire_buffer(buffer_size)

        try:
            image.pixels.foreach_get(pxs)

            # Set array to 3d
            pxs.shape = (-1, image.size[0], 4)
            pxs[start_y:start_y+height, start_x:start_x+width] = color
            pxs = pxs.ravel()

            image.pixels.foreach_set(pxs)
        finally:
            # Always release buffer back to pool, even if an exception occurred
            release_buffer(pxs)


def copy_image_pixels_with_conversion(src, dest, segment=None, segment_src=None):
    """Copy image pixels with automatic color space and bit depth conversion.

    Copies pixels from source to destination and automatically handles conversion
    between different bit depths (byte/float) and color spaces (sRGB/linear).

    Parameters:
        src: Source Blender Image datablock.
        dest: Destination Blender Image datablock.
        segment: Destination tile segment for UDIM/atlas images. Default: None
        segment_src: Source tile segment for UDIM/atlas images. Default: None

    Returns:
        None
    """
    copy_image_pixels(src, dest, segment, segment_src)

    # Convert image colors after copying if destination image and source image has different bit depth
    if dest.is_float and not src.is_float:
        # Byte to float
        set_image_pixels_to_linear(dest, power=1)
        multiply_image_rgb_by_alpha(dest, power=1)
    else:
        # Float to byte
        divide_image_rgb_by_alpha(dest)
        set_image_pixels_to_srgb(dest)
