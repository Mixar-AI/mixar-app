# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Bake operators module - imports and re-exports all baking operators.

This module has been refactored into focused submodules for better maintainability:
- bake_temp_operators.py: Temporary image baking
- bake_image_resize_operator.py: Image resizing
- bake_vcol_operator.py: Vertex color baking
- bake_uv_transfer_operators.py: UV transfer and remapping
- bake_merge_operators.py: Layer and mask merging
- bake_channel_operators.py: Main channel baking and management
"""

# Import all operator classes from submodules
from .bake_temp_operators import MBakeTempImage, MDisableTempImage
from .bake_image_resize_operator import MResizeImage
from .bake_vcol_operator import MBakeChannelToVcol
from .bake_uv_transfer_operators import MTransferSomeLayerUV, MTransferLayerUV
from .bake_merge_operators import MMergeLayer, MMergeMask
from .bake_channel_operators import MDeleteBakedChannelImages, MBakeChannels

# Classes are registered by their respective source modules
# (bake_temp_operators.py, bake_image_resize_operator.py, bake_vcol_operator.py,
#  bake_uv_transfer_operators.py, bake_merge_operators.py, bake_channel_operators.py)
# No classes tuple here to avoid double registration by bootstrap
