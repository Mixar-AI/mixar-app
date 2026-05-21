# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI drawing helper functions for Layer items and settings.

This module re-exports all layer-related UI helper functions from their
respective submodules for backward compatibility.

Submodules:
- ui_helpers_layer_item: Layer item drawing in lists
- ui_helpers_layer_source: Source property drawing (fill, image, material, UV)
- ui_helpers_layer_settings: Main layer settings panel drawing
"""

# Re-export from ui_helpers_layer_item
from .ui_helpers_layer_item import draw_layer_item

# Re-export from ui_helpers_layer_source
from .ui_helpers_layer_source import (
    draw_source_properties,
    draw_node_group_inputs,
    draw_node_props_dynamic,
    draw_image_source_properties,
    draw_material_source_properties,
)

# Re-export from ui_helpers_layer_transform
from .ui_helpers_layer_transform import (
    draw_fill_settings,
    draw_uv_transform_settings,
    draw_coordinate_settings,
)

# Re-export from ui_helpers_layer_settings
from .ui_helpers_layer_settings import draw_layer_settings

# All public exports
__all__ = [
    # Layer item drawing
    'draw_layer_item',
    # Source properties
    'draw_source_properties',
    'draw_node_group_inputs',
    'draw_node_props_dynamic',
    'draw_image_source_properties',
    'draw_material_source_properties',
    'draw_fill_settings',
    'draw_uv_transform_settings',
    'draw_coordinate_settings',
    # Layer settings
    'draw_layer_settings',
]
