# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Check and manage source trees for texture painting layers, channels, and masks.

This module provides the main interface for source tree operations, re-exporting
functions from specialized submodules for backward compatibility.

Submodules:
    - mask_source_tree: Mask source tree check and UV neighbor operations
    - channel_source_tree: Channel source tree enable/disable operations
    - layer_source_tree: Layer source tree enable/disable operations
"""

# Re-export all functions from submodules for backward compatibility
from .mask_source_tree import (
    check_mask_source_tree,
    check_mask_uv_neighbor,
)
from .channel_source_tree import (
    enable_channel_source_tree,
    disable_channel_source_tree,
)
from .layer_source_tree import (
    enable_layer_source_tree,
    disable_layer_source_tree,
)

__all__ = [
    "check_mask_source_tree",
    "check_mask_uv_neighbor",
    "enable_channel_source_tree",
    "disable_channel_source_tree",
    "enable_layer_source_tree",
    "disable_layer_source_tree",
]
