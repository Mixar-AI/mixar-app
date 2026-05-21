# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer checking functions - main entry point module.

This module re-exports all layer checking functions from their respective
submodules for backwards compatibility. The implementation has been split into:

- enable_state_checks.py: Layer, mask, and channel enable state checking
- layer_type_checks.py: Layer type and map type checking functions
- channel_and_processing_checks.py: Channel checking and processing requirement functions
"""

# Re-export all functions from submodules for backwards compatibility
from .enable_state_checks import (
    get_channel_enabled,
    get_layer_enabled,
    get_mask_enabled,
)

from .layer_type_checks import (
    any_decal_inside_layer,
    check_need_prev_normal,
    get_first_vdm_layer,
    is_layer_using_bump_map,
    is_layer_using_normal_map,
    is_layer_using_vdisp_map,
    is_layer_using_vector,
    is_layer_vdm,
)

from .channel_and_processing_checks import (
    any_layers_using_bump_map,
    any_layers_using_channel,
    any_layers_using_disp,
    any_layers_using_displacement,
    any_layers_using_normal_map,
    any_layers_using_vdisp,
    check_layer_divider_alpha,
    has_previous_layer_channels,
    is_any_layer_using_channel,
    is_height_process_needed,
    is_normal_process_needed,
    is_overlay_normal_empty,
    is_root_ch_prop_node_unique,
    is_vdisp_process_needed,
)

# Define __all__ for explicit public API
__all__ = [
    # Enable state checks
    "get_channel_enabled",
    "get_layer_enabled",
    "get_mask_enabled",
    # Layer type checks
    "any_decal_inside_layer",
    "check_need_prev_normal",
    "get_first_vdm_layer",
    "is_layer_using_bump_map",
    "is_layer_using_normal_map",
    "is_layer_using_vdisp_map",
    "is_layer_using_vector",
    "is_layer_vdm",
    # Channel and processing checks
    "any_layers_using_bump_map",
    "any_layers_using_channel",
    "any_layers_using_disp",
    "any_layers_using_displacement",
    "any_layers_using_normal_map",
    "any_layers_using_vdisp",
    "check_layer_divider_alpha",
    "has_previous_layer_channels",
    "is_any_layer_using_channel",
    "is_height_process_needed",
    "is_normal_process_needed",
    "is_overlay_normal_empty",
    "is_root_ch_prop_node_unique",
    "is_vdisp_process_needed",
]
