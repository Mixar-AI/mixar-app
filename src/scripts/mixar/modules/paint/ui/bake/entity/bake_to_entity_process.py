# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Processing functions for entity baking - image creation, baking, and result handling.

This module re-exports all functions from helper modules for backward compatibility.
The implementation is split across:
- bake_image_config.py: Image configuration (colorspace, color, image creation)
- bake_execution.py: Bake execution and post-processing
- bake_result_handlers.py: Result handling (atlas, layers, masks, overrides, info storage)
"""

# Re-export image configuration functions
from ..utils.bake_image_config import (
    get_image_colorspace,
    get_base_color,
    create_bake_image,
)

# Re-export bake execution functions
from ..utils.bake_execution import (
    execute_bake,
    post_process_image,
    bake_other_object_alpha,
)

# Re-export result handling functions
from ..utils.bake_result_handlers import (
    handle_image_atlas,
    create_layer_from_bake,
    create_mask_from_bake,
    update_channel_override,
    store_bake_info,
)

# Expose all public functions for backward compatibility
__all__ = [
    # Image configuration
    "get_image_colorspace",
    "get_base_color",
    "create_bake_image",
    # Bake execution
    "execute_bake",
    "post_process_image",
    "bake_other_object_alpha",
    # Result handling
    "handle_image_atlas",
    "create_layer_from_bake",
    "create_mask_from_bake",
    "update_channel_override",
    "store_bake_info",
]
