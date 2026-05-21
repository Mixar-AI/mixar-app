# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image processing operations for baking.

This module provides a unified interface for image processing operations used
during baking. Functions are organized into submodules by category:

- compositor_effects: Compositor-based effects (blur, denoise, dither)
- bake_effects: Bake-based effects (noise blur, FXAA)
- image_resize: Image resizing operations

All public functions are re-exported here for backwards compatibility.
"""

import numpy

# Re-export compositor-based effects
from .compositor_effects import (
    blur_image,
    denoise_image,
    dither_image,
)

# Re-export bake-based effects
from .bake_effects import (
    fxaa_image,
    noise_blur_image,
)

# Re-export image resize operations
from .image_resize import resize_image


# Helper for getting min/max from pixel array (used by get_pointiness_image_minmax_value)
def get_image_minmax(pxs, width, height, channel=0):
    """Get min/max values from a pixel array for a specific channel.

    Args:
        pxs: Flat numpy array of RGBA pixel data.
        width: Image width.
        height: Image height.
        channel: Channel index (0=R, 1=G, 2=B, 3=A).

    Returns:
        tuple: (min_val, max_val) for the specified channel.
    """
    import numpy as np
    # Extract the specific channel from the flat RGBA array
    channel_data = pxs[channel::4]  # Every 4th element starting from channel index
    return float(np.min(channel_data)), float(np.max(channel_data))


def get_pointiness_image_minmax_value(image):
    """Get minimum and maximum values from a pointiness image.

    Uses optimized C++ backend when available for 2-5x speedup.

    Args:
        image: Blender image object containing pointiness data.

    Returns:
        tuple: (min_val, max_val) tuple of float values.
    """

    pxs = numpy.empty(shape=image.size[0] * image.size[1] * 4, dtype=numpy.float32)
    image.pixels.foreach_get(pxs)

    width = image.size[0]
    height = image.size[1]

    # Get min/max across RGB channels using optimized C++ backend
    # Check all three color channels to find global min/max
    min_r, max_r = get_image_minmax(pxs, width, height, channel=0)
    min_g, max_g = get_image_minmax(pxs, width, height, channel=1)
    min_b, max_b = get_image_minmax(pxs, width, height, channel=2)

    min_val = min(min_r, min_g, min_b)
    max_val = max(max_r, max_g, max_b)

    return min_val, max_val


# Define __all__ for explicit public API
__all__ = [
    # Compositor effects
    "blur_image",
    "denoise_image",
    "dither_image",
    # Bake effects
    "fxaa_image",
    "noise_blur_image",
    # Image resize
    "resize_image",
    # Utility functions
    "get_image_minmax",
    "get_pointiness_image_minmax_value",
]
