# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Callbacks for per-channel source property changes.

This module contains callbacks triggered when MChannelSource properties change.
These callbacks update the node graph to reflect per-channel source overrides.
"""

import re

from ......config.logging_config import get_logger

logger = get_logger(__name__)


def _get_layer_and_channel_from_path(self):
    """Extract layer and channel from property path.

    Args:
        self: MChannelSource property group.

    Returns:
        tuple: (layer, channel, channel_index) or (None, None, None) if not found.
    """
    mp = self.id_data.mp
    path = self.path_from_id()

    # Path format: mp.layers[X].channels[Y].channel_source
    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]\.channel_source", path)
    if not m:
        return None, None, None

    layer_idx = int(m.group(1))
    ch_idx = int(m.group(2))

    if layer_idx >= len(mp.layers) or ch_idx >= len(mp.channels):
        return None, None, None

    layer = mp.layers[layer_idx]
    channel = layer.channels[ch_idx]

    return layer, channel, ch_idx


def on_channel_source_type_changed(self, context):
    """Handle channel source type changes.

    Called when source_type or enabled changes. Updates the node graph
    to use the appropriate source (layer source, image, or solid).

    Args:
        self: MChannelSource property group.
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    layer, channel, ch_idx = _get_layer_and_channel_from_path(self)
    if layer is None:
        return

    root_ch = mp.channels[ch_idx]
    logger.debug(
        f"Channel source type changed: Layer '{layer.name}', "
        f"Channel '{root_ch.name}', Type: {self.source_type}, Enabled: {self.enabled}"
    )

    # TODO: Implement node graph updates
    # When enabled and source_type changes:
    # - DEFAULT: Remove per-channel source node, use layer source
    # - IMAGE: Create/update ShaderNodeTexImage with image_name
    # - SOLID: Create/update ShaderNodeRGB or ShaderNodeValue

    # For now, just log the change
    if self.enabled and self.source_type != "DEFAULT":
        logger.info(
            f"Per-channel source enabled for {root_ch.name}: {self.source_type}"
        )


def on_channel_source_image_changed(self, context):
    """Handle channel source image changes.

    Called when image_name or interpolation changes. Updates the
    per-channel image texture node.

    Args:
        self: MChannelSource property group.
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    layer, channel, ch_idx = _get_layer_and_channel_from_path(self)
    if layer is None:
        return

    # Only process if enabled and using IMAGE source type
    if not self.enabled or self.source_type != "IMAGE":
        return

    root_ch = mp.channels[ch_idx]
    logger.debug(
        f"Channel source image changed: Layer '{layer.name}', "
        f"Channel '{root_ch.name}', Image: {self.image_name}"
    )

    # TODO: Implement image node update
    # - Find or create the per-channel image texture node
    # - Set node.image = bpy.data.images.get(self.image_name)
    # - Set node.interpolation = self.interpolation


def on_channel_source_solid_changed(self, context):
    """Handle channel source solid color/value changes.

    Called when solid_color or solid_value changes. Updates the
    per-channel solid value node.

    Args:
        self: MChannelSource property group.
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    layer, channel, ch_idx = _get_layer_and_channel_from_path(self)
    if layer is None:
        return

    # Only process if enabled and using SOLID source type
    if not self.enabled or self.source_type != "SOLID":
        return

    root_ch = mp.channels[ch_idx]
    logger.debug(
        f"Channel source solid changed: Layer '{layer.name}', "
        f"Channel '{root_ch.name}'"
    )

    # TODO: Implement solid node update
    # - Find or create the per-channel solid node
    # - For COLOR channels: use ShaderNodeRGB, set outputs[0].default_value
    # - For VALUE channels: use ShaderNodeValue, set outputs[0].default_value
