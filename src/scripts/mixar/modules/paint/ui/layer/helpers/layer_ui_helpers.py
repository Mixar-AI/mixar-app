# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer UI helpers - re-export hub.

This module re-exports all layer helper functions from their respective
submodules for backward compatibility. The functions are split into:
- layer_enum_helpers: channel_items, get_normal_map_type_items, constants
- layer_create_helpers: add_new_layer, update_new_layer_* callbacks
- layer_operation_helpers: search, remove, replace operations
- layer_duplicate_helpers: layer duplication functions
- layer_override_callbacks: override check/update functions
- layer_channel_callbacks: channel property callbacks
- layer_state_callbacks: layer state and misc callbacks
"""

# Re-export all from submodules
from .layer_enum_helpers import (
    DEFAULT_NEW_IMG_SUFFIX,
    DEFAULT_NEW_VCOL_SUFFIX,
    DEFAULT_NEW_VDM_SUFFIX,
    channel_items,
    get_normal_map_type_items,
)

from .layer_create_helpers import (
    add_new_layer,
    update_channel_idx_new_layer,
    update_new_layer_mask_uv_map,
    update_new_layer_uv_map,
)

from .layer_operation_helpers import (
    draw_move_down_in_layer_group,
    draw_move_up_in_layer_group,
    draw_remove_group,
    remove_layer,
    replace_layer_type,
    search_for_image_node,
    search_for_images,
)

from .layer_duplicate_helpers import (
    duplicate_decal_empty_reference,
    duplicate_layer_nodes_and_images,
    update_driver_targets,
)

from ..callbacks.layer_override_callbacks import (
    check_override_1_layer_channel_nodes,
    check_override_layer_channel_nodes,
    update_layer_channel_override,
    update_layer_channel_override_1,
)

# Import layer_state_callbacks BEFORE layer_channel_callbacks to avoid circular import
# layer_channel_callbacks has a delayed import from layer_state_callbacks, so
# layer_state_callbacks must be fully loaded first
from ..callbacks.layer_state_callbacks import (
    check_layer_projections,
    get_layer_channel_input_label,
    group_trash_update,
    recheck_background_layers_ios,
    update_channel_active_edit,
    update_divide_rgb_by_alpha,
    update_hemi_camera_ray_mask,
    update_hemi_space,
    update_hemi_use_prev_normal,
    update_image_flip_y,
    update_layer_blur_vector,
    update_layer_blur_vector_factor,
    update_layer_channel_override_vcol_name,
    update_layer_channel_use_clamp,
    update_layer_channel_vdisp_flip_yz,
    update_layer_color_chortcut,
    update_layer_edge_detect_radius,
    update_layer_enable,
    update_layer_name,
    update_layer_projection,
    update_layer_source_type,
    update_layer_transform,
    update_layer_uniform_scale_enabled,
    update_layer_use_baked,
)

from ..callbacks.layer_channel_callbacks import (
    update_blend_type,
    update_bump_distance,
    update_bump_midlevel,
    update_channel_enable,
    update_channel_intensity_value,
)
from ..callbacks.layer_normal_callbacks import (
    update_flip_backface_normal,
    update_layer_channel_voronoi_feature,
    update_layer_input,
    update_normal_map_type,
    update_normal_space,
    update_voronoi_feature,
    update_write_height,
)
from ..callbacks.layer_uv_callbacks import (
    check_layer_projection_blends,
    update_projection_blend,
    update_texcoord_type,
    update_uv_name,
)

__all__ = [
    # Constants
    "DEFAULT_NEW_IMG_SUFFIX",
    "DEFAULT_NEW_VCOL_SUFFIX",
    "DEFAULT_NEW_VDM_SUFFIX",
    # Enum helpers
    "channel_items",
    "get_normal_map_type_items",
    # Create helpers
    "add_new_layer",
    "update_channel_idx_new_layer",
    "update_new_layer_mask_uv_map",
    "update_new_layer_uv_map",
    # Operation helpers
    "draw_move_down_in_layer_group",
    "draw_move_up_in_layer_group",
    "draw_remove_group",
    "remove_layer",
    "replace_layer_type",
    "search_for_image_node",
    "search_for_images",
    # Duplicate helpers
    "duplicate_decal_empty_reference",
    "duplicate_layer_nodes_and_images",
    "update_driver_targets",
    # Override callbacks
    "check_override_1_layer_channel_nodes",
    "check_override_layer_channel_nodes",
    "update_layer_channel_override",
    "update_layer_channel_override_1",
    # Channel callbacks
    "check_layer_projection_blends",
    "update_blend_type",
    "update_bump_distance",
    "update_bump_midlevel",
    "update_channel_enable",
    "update_channel_intensity_value",
    "update_flip_backface_normal",
    "update_layer_channel_voronoi_feature",
    "update_layer_input",
    "update_normal_map_type",
    "update_normal_space",
    "update_projection_blend",
    "update_texcoord_type",
    "update_uv_name",
    "update_voronoi_feature",
    "update_write_height",
    # State callbacks
    "check_layer_projections",
    "get_layer_channel_input_label",
    "group_trash_update",
    "recheck_background_layers_ios",
    "update_channel_active_edit",
    "update_divide_rgb_by_alpha",
    "update_hemi_camera_ray_mask",
    "update_hemi_space",
    "update_hemi_use_prev_normal",
    "update_image_flip_y",
    "update_layer_blur_vector",
    "update_layer_blur_vector_factor",
    "update_layer_channel_override_vcol_name",
    "update_layer_channel_use_clamp",
    "update_layer_channel_vdisp_flip_yz",
    "update_layer_color_chortcut",
    "update_layer_edge_detect_radius",
    "update_layer_enable",
    "update_layer_name",
    "update_layer_projection",
    "update_layer_source_type",
    "update_layer_transform",
    "update_layer_uniform_scale_enabled",
    "update_layer_use_baked",
]
