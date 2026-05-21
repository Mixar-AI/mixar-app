# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Channel image operators for Mixar.

This module serves as a coordinator that re-exports all channel image
operators from their respective submodules.

Submodules:
- channel_image_utils: Utility functions for image operations
- channel_override_image_ops: Channel override operators
- brush_texture_ops: Brush texture operators
"""

# Re-export utility functions
from .channel_image_utils import get_existing_images, is_normal_map_filename

# Re-export channel override operators
from .channel_override_image_ops import (
    MOpenImageToOverrideChannel,
    MOpenImageToOverride1Channel,
    MSelectExistingImage,
)

# Re-export brush texture operators
from ..utils.brush_texture_ops import MClearBrushTexture, MOpenImageToBrushTexture

# Re-export brush generation operators
from ..utils.brush_gen_ops import (
    MGenerateBrushTexture,
    MApplyBrushSelectedImage,
    MBrushGenClearReference,
    MBrushGenRefreshModels,
)

# Classes are registered by their respective source modules
# (channel_override_image_ops.py, brush_texture_ops.py, brush_gen_ops.py)
# No classes tuple here to avoid double registration by bootstrap


# Define __all__ for explicit exports
__all__ = [
    # Utility functions
    'is_normal_map_filename',
    'get_existing_images',
    # Channel override operators
    'MOpenImageToOverrideChannel',
    'MOpenImageToOverride1Channel',
    'MSelectExistingImage',
    # Brush texture operators
    'MOpenImageToBrushTexture',
    'MClearBrushTexture',
    # Brush generation operators
    'MGenerateBrushTexture',
    'MApplyBrushSelectedImage',
    'MBrushGenClearReference',
    'MBrushGenRefreshModels',
]
