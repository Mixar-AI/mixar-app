# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer visual and transform callback functions.

This module serves as a coordinator that re-exports callbacks from submodules:
- layer_callbacks_transform: Transform, blur, uniform scale callbacks
- layer_callbacks_source: Source type, color shortcut, baked image callbacks
- layer_callbacks_projection: Projection type, hardness, axis, UV extension callbacks

Submodules:
- layer_callbacks_transform: Transform-related callbacks
- layer_callbacks_source: Source type callbacks
- layer_callbacks_projection: Projection callbacks and utilities
"""

# Re-export transform callbacks
from .layer_callbacks_transform import (
    update_layer_blur_vector,
    update_layer_blur_vector_factor,
    update_layer_edge_detect_radius,
    update_layer_transform,
    update_layer_uniform_scale_enabled,
)

# Re-export source callbacks
from .layer_callbacks_source import (
    update_layer_color_chortcut,
    update_layer_source_type,
    update_layer_use_baked,
)

# Re-export projection callbacks and utilities
from .layer_callbacks_projection import (
    check_layer_projections,
    recheck_background_layers_ios,
    update_channel_source_transform,
    update_layer_projection,
    update_projection_axis,
    update_projection_hardness,
    update_uv_extension,
)


# Define __all__ for explicit exports
__all__ = [
    # Transform callbacks
    'update_layer_transform',
    'update_layer_blur_vector',
    'update_layer_blur_vector_factor',
    'update_layer_uniform_scale_enabled',
    'update_layer_edge_detect_radius',
    # Source callbacks
    'update_layer_color_chortcut',
    'update_layer_use_baked',
    'update_layer_source_type',
    # Projection callbacks and utilities
    'check_layer_projections',
    'recheck_background_layers_ios',
    'update_layer_projection',
    'update_projection_hardness',
    'update_projection_axis',
    'update_uv_extension',
    'update_channel_source_transform',
]
