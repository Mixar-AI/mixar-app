# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""UI drawing helper functions for Layers and Masks.

This module serves as a coordinator that re-exports all UI helper functions
from their respective submodules for backward compatibility.

Submodules:
- ui_helpers_materials: Material section drawing
- ui_helpers_toolbar: Layer toolbar drawing
- ui_helpers_channels: Channel settings drawing
- ui_helpers_base: Base input property drawing
- ui_helpers_mask: Mask settings drawing
- ui_helpers_layer: Layer item and settings drawing
"""

# Re-export base functions
from .ui_helpers_base import draw_input_prop

# Re-export mask and layer helpers
from .ui_helpers_mask import draw_mask_settings
from .ui_helpers_layer import draw_layer_item, draw_layer_settings

# Re-export materials section
from .ui_helpers_materials import draw_materials_section

# Re-export toolbar
from .ui_helpers_toolbar import draw_top_toolbar

# Re-export channel helpers (only actively used functions)
from .ui_helpers_channels import (
    draw_normal_map_image_source,
    draw_channel_settings,
)


def draw_brush_settings(context, layout, layer):
    """Draw full brush properties for IMAGE layers in texture paint mode.

    Draws the complete brush properties panel as shown in Active Tool and
    Workspace Settings, including brush asset, settings, color picker, stroke,
    falloff, symmetry, and options.

    Only shows when:
    - Layer is IMAGE type
    - Context mode is PAINT_TEXTURE
    - A brush is active

    Args:
        context: Blender context.
        layout: UI layout to draw into.
        layer: Backend YLayer.
    """
    from .ui_helpers_brush import draw_full_brush_properties

    draw_full_brush_properties(context, layout, layer)


# Define __all__ for explicit exports
__all__ = [
    # Base
    'draw_input_prop',
    # Mask and layer
    'draw_mask_settings',
    'draw_layer_item',
    'draw_layer_settings',
    # Materials
    'draw_materials_section',
    # Toolbar
    'draw_top_toolbar',
    # Channels
    'draw_normal_map_image_source',
    'draw_channel_settings',
    # Brush
    'draw_brush_settings',
]
