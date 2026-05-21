# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Utility functions for Fill layer material UI."""

from ...core.node.get_nodes import get_layer_source, get_tree


def draw_solid_color_source(layout, layer):
    """Draw solid color picker control.

    Args:
        layout: UI layout
        layer: Backend YLayer
    """
    tree = get_tree(layer)
    source_node = get_layer_source(layer, tree) if tree else None

    if source_node and source_node.bl_idname == 'ShaderNodeRGB':
        # Color picker row
        box_row = layout.box().row(align=True)
        box_row.scale_y = 1.5
        split = box_row.split(factor=0.3, align=True)
        split.label(text="Color")
        split.prop(source_node.outputs[0], 'default_value', text="")
    else:
        # Fallback info
        info_row = layout.row()
        info_row.alignment = 'CENTER'
        info_row.label(text="Solid color source", icon='COLOR')


def get_channel_index(layer, channel):
    """Get the index of a channel within its layer.

    Args:
        layer: YLayer parent layer
        channel: YLayerChannel to find

    Returns:
        int: Index of channel, or -1 if not found
    """
    for i, ch in enumerate(layer.channels):
        if ch == channel:
            return i
    return -1


def get_layer_index(layer):
    """Get the index of a layer within mp.layers.

    Args:
        layer: YLayer to find

    Returns:
        int: Index of layer, or -1 if not found
    """
    mp = layer.id_data.mp
    for i, l in enumerate(mp.layers):
        if l == layer:
            return i
    return -1


def get_layer_color_luminance(layer):
    """Calculate luminance from layer's solid color source.

    Uses standard luminance formula: L = 0.2126*R + 0.7152*G + 0.0722*B

    Args:
        layer: YLayer (fill layer with solid color source)

    Returns:
        float: Luminance value (0.0 to 1.0)
    """
    tree = get_tree(layer)
    source_node = get_layer_source(layer, tree) if tree else None

    if source_node and source_node.bl_idname == 'ShaderNodeRGB':
        color = source_node.outputs[0].default_value
        # Standard luminance formula (ITU-R BT.709)
        luminance = 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]
        return max(0.0, min(1.0, luminance))

    return 1.0  # Default fallback
