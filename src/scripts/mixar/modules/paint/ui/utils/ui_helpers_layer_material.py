# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""MATERIAL section UI for layers.

This module serves as a coordinator that provides the main draw_material_section
function, using helper functions from submodules.

Submodules:
- ui_helpers_fill_utils: Utility functions
- ui_helpers_fill_extras: Channel extras drawing
"""

from ...core.layer_handlers import get_handler

# Re-export utility functions for backwards compatibility
from .ui_helpers_fill_utils import (
    draw_solid_color_source,
    get_channel_index,
    get_layer_color_luminance,
    get_layer_index,
)

# Re-export extras functions
from .ui_helpers_fill_extras import (
    draw_ao_image_inline,
    draw_channel_extras,
    draw_channel_image_selector,
    draw_normal_channel_extras,
    draw_normal_image_extras,
)


def draw_material_section(context, layout, layer, mp):
    """Draw MATERIAL section for Fill layers (flat layout like paint layer).

    Contains source selection and per-channel controls.

    Args:
        context: Blender context
        layout: UI layout to draw into
        layer: Backend YLayer
        mp: Root MPaint property group
    """
    # Only show for Fill layers (type='COLOR')
    if layer.type != 'COLOR':
        return

    # ========== CHANNEL LIST ==========
    _draw_channel_list(context, layout, layer, mp)


def _draw_channel_list(context, layout, layer, mp):
    """Draw channel list using layer type handlers.

    Delegates to the appropriate handler based on layer type.

    Args:
        context: Blender context
        layout: UI layout
        layer: Backend YLayer
        mp: Root MPaint property group
    """
    # Channel header row
    ch_header = layout.row(align=True)
    ch_header.scale_y = 1.2
    ch_header.label(text="Channels", icon='NODE_TEXTURE')
    ch_header.menu("CHANNELS_MT_add_channel_menu", text="", icon='ADD')

    layout.separator(factor=0.3)

    # Get handler for this layer type
    handler = get_handler(layer.type)

    # Draw each channel using handler
    for i, channel in enumerate(layer.channels):
        if i >= len(mp.channels):
            continue

        root_ch = mp.channels[i]
        handler.draw_channel_row(context, layout, channel, root_ch, layer, mp)


# Backwards compatibility aliases with underscore prefix
_draw_solid_color_source = draw_solid_color_source
_draw_channel_extras = draw_channel_extras
_draw_normal_image_extras = draw_normal_image_extras
_draw_normal_channel_extras = draw_normal_channel_extras
_draw_ao_image_inline = draw_ao_image_inline
_draw_channel_image_selector = draw_channel_image_selector
_get_channel_index = get_channel_index
_get_layer_index = get_layer_index
_get_layer_color_luminance = get_layer_color_luminance


# Define __all__ for explicit exports
__all__ = [
    'draw_material_section',
    'draw_solid_color_source',
    'draw_channel_extras',
    'draw_normal_image_extras',
    'draw_normal_channel_extras',
    'draw_ao_image_inline',
    'draw_channel_image_selector',
    'get_channel_index',
    'get_layer_index',
    'get_layer_color_luminance',
]
