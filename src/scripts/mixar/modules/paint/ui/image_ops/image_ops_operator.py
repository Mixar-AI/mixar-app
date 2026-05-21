# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image operations operators - re-export hub.

This module re-exports all image operation operators from their respective
submodules for backward compatibility. The operators are split into:
- image_ops_basic: Copy path, open folder, invert, refresh, pack
- image_ops_save: Save, save all baked, save/pack all
- image_ops_save_as: Save As with format options
- image_ops_convert: Bit depth conversion
"""

# Re-export all operators from submodules
from .image_ops_basic import (
    MCopyImagePathToClipboard,
    MOpenContainingImageFolder,
    MInvertImage,
    MRefreshImage,
    MPackImage,
)
from .image_ops_save import (
    MSaveImage,
    MSaveAllBakedImages,
    MSavePackAll,
)
from .image_ops_save_as import MSaveAsImage
from .image_ops_convert import MConvertImageBitDepth

# Classes are registered by their respective source modules
# (image_ops_basic.py, image_ops_save.py, image_ops_save_as.py, image_ops_convert.py)
# No classes tuple here to avoid double registration by bootstrap

__all__ = [
    "MCopyImagePathToClipboard",
    "MOpenContainingImageFolder",
    "MInvertImage",
    "MRefreshImage",
    "MPackImage",
    "MSaveImage",
    "MSaveAllBakedImages",
    "MSaveAsImage",
    "MSavePackAll",
    "MConvertImageBitDepth",
]
