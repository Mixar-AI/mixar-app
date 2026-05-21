# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Main mask properties helper module - re-exports all update callbacks for backward compatibility.

This module has been refactored into smaller submodules:
- mask_properties_name_enable.py: Name and enable state update callbacks
- mask_properties_source.py: Source input and hemisphere-related update callbacks
- mask_properties_uv_transform.py: UV, transform, blur, and blend type update callbacks
- mask_properties_misc.py: Miscellaneous update callbacks (baked, channel, object index, etc.)
"""

# Re-export all functions from submodules for backward compatibility
from .mask_properties_name_enable import (
    update_mask_name,
    update_layer_mask_enable,
    update_mask_active_edit,
)

from .mask_properties_source import (
    update_mask_source_input,
    update_mask_hemi_space,
    update_mask_hemi_camera_ray_mask,
    update_mask_hemi_use_prev_normal,
)

from .mask_properties_uv_transform import (
    update_mask_uv_name,
    update_mask_blend_type,
    update_mask_transform,
    update_mask_blur_vector,
)

from .mask_properties_misc import (
    update_mask_use_baked,
    update_layer_mask_channel_enable,
    update_mask_object_index,
    update_mask_edge_detect_radius,
    update_mask_intensity,
    update_mask_voronoi_feature,
    update_mask_uniform_scale_enabled,
    update_enable_layer_masks,
)

# Define __all__ to explicitly list all exported functions
__all__ = [
    # Name and enable callbacks
    "update_mask_name",
    "update_layer_mask_enable",
    "update_mask_active_edit",
    # Source and hemi callbacks
    "update_mask_source_input",
    "update_mask_hemi_space",
    "update_mask_hemi_camera_ray_mask",
    "update_mask_hemi_use_prev_normal",
    # UV and transform callbacks
    "update_mask_uv_name",
    "update_mask_blend_type",
    "update_mask_transform",
    "update_mask_blur_vector",
    # Miscellaneous callbacks
    "update_mask_use_baked",
    "update_layer_mask_channel_enable",
    "update_mask_object_index",
    "update_mask_edge_detect_radius",
    "update_mask_intensity",
    "update_mask_voronoi_feature",
    "update_mask_uniform_scale_enabled",
    "update_enable_layer_masks",
]
