# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer channel setup helper functions.

Uses layer type handlers for type-specific behavior.
"""

from ....core.io.input_outputs.input_outputs import check_layer_channel_linear_node
from ....core.layer_handlers import get_handler


def setup_layer_channels(
    layer,
    mp,
    channel_idx,
    blend_type,
    normal_blend_type,
    normal_map_type,
    normal_space,
    solid_color=(1, 1, 1),
):
    """Set up channels for a layer.

    Uses layer type handlers for type-specific channel setup.

    Args:
        layer: The layer object.
        mp: The mixar paint data structure.
        channel_idx (int): Index of channel to affect.
        blend_type (str): Blend mode for the layer.
        normal_blend_type (str): Blend mode for normal channel.
        normal_map_type (str): Type of normal map (BUMP_MAP, NORMAL_MAP, etc.).
        normal_space (str): Normal map space (TANGENT, OBJECT, etc.).
        solid_color (tuple, optional): RGB color for override. Defaults to (1, 1, 1).
    """
    # Get handler for this layer type
    handler = get_handler(layer.type)
    default_enabled_channels = handler.get_default_enabled_channels(mp)

    # Check if procedural material layer (special case for COLOR with material source)
    is_procedural = (
        layer.type == "PROCEDURAL" or
        (layer.type == "COLOR" and hasattr(layer, 'source_type') and layer.source_type == "MATERIAL")
    )

    for i, ch in enumerate(layer.channels):
        root_ch = mp.channels[i]

        # Determine channel enablement using handler
        if is_procedural:
            # Use procedural handler's default channels
            proc_handler = get_handler('PROCEDURAL')
            proc_channels = proc_handler.get_default_enabled_channels(mp)
            ch.enable = root_ch.name in proc_channels
        elif layer.type in {"GROUP", "BACKGROUND"}:
            ch.enable = True
        elif channel_idx == i or channel_idx == -1:
            ch.enable = True
        else:
            ch.enable = root_ch.name in default_enabled_channels

        # Set blend types for enabled channels
        if ch.enable:
            if root_ch.type == "NORMAL":
                ch.normal_blend_type = normal_blend_type
                ch.normal_space = normal_space
            else:
                ch.blend_type = blend_type

        if root_ch.type == "NORMAL":
            ch.normal_map_type = normal_map_type
            _setup_normal_channel_defaults(layer, ch)

        # Set linear node of layer channel
        check_layer_channel_linear_node(ch, layer, root_ch)

        # Set override using handler
        handler.setup_channel_defaults(ch, root_ch, solid_color)


def _setup_normal_channel_defaults(layer, ch):
    """Set up default values for normal channel.

    Args:
        layer: The layer object.
        ch: The channel object.
    """
    if layer.type in {"BACKGROUND"}:
        # Background layer has default bump distance of 0.0 and no height writing
        ch.bump_distance = 0.0
        ch.bump_midlevel = 0.5
        ch.write_height = False
    else:
        # Non-background layers get proper defaults for height processing
        ch.bump_distance = 0.05  # Height range for bump
        ch.bump_midlevel = 0.5  # Neutral bump value
        ch.write_height = False  # Convert to normals for visual bumps



