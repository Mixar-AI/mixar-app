# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helper functions for channel baking operations.

This module re-exports all helper functions for backward compatibility.
The actual implementations are split across:
- bake_object_helpers.py: Object-related baking operations
- bake_image_helpers.py: Image processing during baking
- bake_vcol_helpers.py: Vertex color baking operations
- bake_target_helpers.py: Bake target operations
"""

from mixar.config.logging_config import get_logger

# Re-export all functions for backward compatibility
from ..object_prep.bake_object_helpers import (
    get_bake_objects,
    setup_multi_material,
    prepare_objects_for_bake,
    recover_multi_material,
    post_bake_operations,
)

from ..utils.bake_image_helpers import (
    process_baked_images,
    _process_normal_channel_images,
    set_bake_info_to_images,
)

from ..bake_target.bake_target_helpers import (
    process_custom_bake_targets,
    _get_bake_target_default_colors,
    _create_bake_target_image,
    _fill_existing_bake_target,
    _copy_bake_target_channels,
    rgba_letters,
)

from ..utils.bake_vcol_helpers import (
    bake_vcol_for_channels,
)

logger = get_logger(__name__)

# Define __all__ for explicit public API
__all__ = [
    # Object helpers
    "get_bake_objects",
    "setup_multi_material",
    "prepare_objects_for_bake",
    "recover_multi_material",
    "post_bake_operations",
    # Image helpers
    "process_baked_images",
    "_process_normal_channel_images",
    "set_bake_info_to_images",
    # Bake target helpers
    "process_custom_bake_targets",
    "_get_bake_target_default_colors",
    "_create_bake_target_image",
    "_fill_existing_bake_target",
    "_copy_bake_target_channels",
    "rgba_letters",
    # Vcol helpers
    "bake_vcol_for_channels",
]
