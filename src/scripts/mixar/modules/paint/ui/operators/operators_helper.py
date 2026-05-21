# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operators helper module.

This module provides helper functions for paint operators. Functions are
organized into sub-modules by category and re-exported here for backward
compatibility.

Sub-modules:
    - operators_helper_preview: Preview mode functions
    - operators_helper_tangent: Tangent sign and vertex color functions
    - operators_helper_channel: Channel alpha and input functions
    - operators_helper_displacement: Parallax and displacement functions
    - operators_helper_layer: Layer and channel update functions
"""

# Re-export all functions from sub-modules for backward compatibility

# Preview mode functions
from .operators_helper_preview import (
    get_preview,
    set_srgb_view_transform,
    remove_preview,
    update_preview_mode,
    update_layer_preview_mode,
)

# Tangent sign and vertex color functions
from .operators_helper_tangent import (
    update_flip_backface,
    update_enable_tangent_sign_hacks,
    refresh_tangent_sign_vcol,
    actual_refresh_tangent_sign_vcol,
    update_use_linear_blending,
    recover_tangent_sign_process,
)

# Channel alpha and input functions
from .operators_helper_channel import (
    set_input_default_value,
    update_channel_alpha,
    do_alpha_setup,
    update_channel_alpha_blend_mode,
    update_backface_mode,
    update_channel_disable_global_baked,
    check_all_channel_ios,
)

# Parallax and displacement functions
from .operators_helper_displacement import (
    update_parallax_rim_hack,
    update_parallax_height_tweak,
    update_displacement_ref_plane,
    setup_subdiv_to_max_polys,
    update_subdiv_max_polys,
)

# Layer and channel update functions
from .operators_helper_layer import (
    update_active_mp_channel,
    update_layer_index,
    update_sculpt_mode,
)

# Define __all__ to explicitly list all exported functions
__all__ = [
    # Preview mode functions
    "get_preview",
    "set_srgb_view_transform",
    "remove_preview",
    "update_preview_mode",
    "update_layer_preview_mode",
    # Tangent sign and vertex color functions
    "update_flip_backface",
    "update_enable_tangent_sign_hacks",
    "refresh_tangent_sign_vcol",
    "actual_refresh_tangent_sign_vcol",
    "update_use_linear_blending",
    "recover_tangent_sign_process",
    # Channel alpha and input functions
    "set_input_default_value",
    "update_channel_alpha",
    "do_alpha_setup",
    "update_channel_alpha_blend_mode",
    "update_backface_mode",
    "update_channel_disable_global_baked",
    # Parallax and displacement functions
    "update_parallax_rim_hack",
    "update_parallax_height_tweak",
    "update_displacement_ref_plane",
    "setup_subdiv_to_max_polys",
    "update_subdiv_max_polys",
    # Layer and channel update functions
    "update_active_mp_channel",
    "update_layer_index",
    "update_sculpt_mode",
]
