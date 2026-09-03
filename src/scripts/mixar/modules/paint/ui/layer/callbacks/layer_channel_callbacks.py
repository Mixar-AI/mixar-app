# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer channel property callback functions for channel enable, blend, and intensity.

This module contains callbacks that are triggered when layer channel properties change.
For normal map callbacks, see layer_normal_callbacks.py.
For UV, projection, and override callbacks, see layer_uv_callbacks.py.
"""

import re
import time

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ....core.layer.check_channels import check_start_end_root_ch_nodes
from ....core.node.check_nodes import check_all_layer_channel_io_and_nodes, check_uv_nodes
from ....core.element.update_image import update_layer_images_interpolation
from ....core.io.input_outputs.input_outputs import check_layer_tree_ios
from ....core.subtree.get_subtree import get_tree
from ....utils.common import get_entity_prop_input
from ...list_item.list_item_operators_helper import refresh_list_items


def update_channel_enable(self, context):
    """Update callback when a layer channel is enabled or disabled.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
    T = time.time()
    mp = self.id_data.mp
    if mp.halt_update:
        logger.debug(f"update_channel_enable: halt_update is True, skipping")
        return
    wm = context.window_manager

    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    if not m:
        return
    layer_idx = int(m.group(1))
    ch_index = int(m.group(2))
    if layer_idx >= len(mp.layers) or ch_index >= len(mp.channels):
        return
    layer = mp.layers[layer_idx]
    root_ch = mp.channels[ch_index]
    ch = self

    logger.info(f"update_channel_enable: Layer '{layer.name}', Channel '{root_ch.name}', Enabled: {self.enable}")

    tree = get_tree(layer)

    if root_ch.type == "NORMAL" and self.enable:
        update_layer_images_interpolation(layer, "Cubic")
        # Auto-set override_type to LAYER if channel has processing type.
        # PASSTHROUGH mode doesn't create height_proc/normal_map_proc nodes.
        processing_types = {'BUMP_MAP', 'BUMP_NORMAL_MAP', 'NORMAL_MAP', 'VECTOR_DISPLACEMENT_MAP'}
        if (hasattr(self, 'override_type') and
            self.override_type == 'PASSTHROUGH' and
            self.normal_map_type in processing_types):
            self.override_type = 'LAYER'

    # Check uv maps
    check_uv_nodes(mp)

    # Refresh layer IO - this creates the output sockets for the channel
    logger.debug(f"update_channel_enable: Calling check_all_layer_channel_io_and_nodes")
    check_all_layer_channel_io_and_nodes(layer, tree, ch)

    if mp.halt_reconnect:
        logger.debug(f"update_channel_enable: halt_reconnect is True, skipping reconnection")
        return

    if mp.layer_preview_mode:
        # Refresh preview mode, rearrange and reconnect already done in this event
        logger.debug(f"update_channel_enable: In layer_preview_mode")
        mp.layer_preview_mode = mp.layer_preview_mode
    else:
        logger.debug(f"update_channel_enable: Reconnecting layer nodes")
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        logger.debug(f"update_channel_enable: Reconnecting mp nodes")
        check_start_end_root_ch_nodes(self.id_data)
        reconnect_mp_nodes(self.id_data)
        rearrange_mp_nodes(self.id_data)

    # Disable active edit on overrides
    if not ch.enable:
        ch.active_edit = False
        ch.active_edit_1 = False

    logger.info(f"update_channel_enable: Completed in {(time.time() - T) * 1000:.2f}ms")

    # Update list items
    refresh_list_items(mp)

    logger.info(
        "Channel %s of %s is updated in %s ms!",
        root_ch.name, layer.name, "{:0.2f}".format((time.time() - T) * 1000)
    )
    # Update timer if it exists (legacy mpui pattern)
    if hasattr(wm, 'mptimer'):
        wm.mptimer.time = str(time.time())


def update_blend_type(self, context):
    """Update callback for layer channel blend type changes.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
    T = time.time()

    wm = context.window_manager
    mp = self.id_data.mp
    if mp.halt_update:
        return
    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    if not m:
        return
    layer_idx = int(m.group(1))
    ch_index = int(m.group(2))
    if layer_idx >= len(mp.layers) or ch_index >= len(mp.channels):
        return
    layer = mp.layers[layer_idx]
    tree = get_tree(layer)
    root_ch = mp.channels[ch_index]

    check_all_layer_channel_io_and_nodes(layer, tree, self)
    check_uv_nodes(mp)

    # Reconnect all layer channels if normal channel is updated
    if root_ch.type == "NORMAL":
        reconnect_layer_nodes(layer)
    else:
        reconnect_layer_nodes(layer, ch_index)

    rearrange_layer_nodes(layer)

    reconnect_mp_nodes(self.id_data)
    rearrange_mp_nodes(self.id_data)

    logger.info(
        "Layer %s blend type is changed in %s ms!",
        layer.name, "{:0.2f}".format((time.time() - T) * 1000)
    )
    # Update timer if it exists (legacy mpui pattern)
    if hasattr(wm, 'mptimer'):
        wm.mptimer.time = str(time.time())


def update_channel_intensity_value(self, context):
    """Update callback for layer channel intensity/opacity changes.

    Updates the channel's intensity input socket's default value.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
    T = time.time()

    mp = self.id_data.mp
    if mp.halt_update:
        return

    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    if not m:
        return
    layer_idx = int(m.group(1))
    ch_index = int(m.group(2))
    if layer_idx >= len(mp.layers) or ch_index >= len(mp.channels):
        return
    layer = mp.layers[layer_idx]
    root_ch = mp.channels[ch_index]

    # Get the channel's intensity input socket and update its default value
    intensity_input = get_entity_prop_input(self, 'intensity_value')
    if intensity_input:
        intensity_input.default_value = self.intensity_value

    logger.info(
        "Layer %s channel %s intensity changed to %.3f in %.2f ms!",
        layer.name, root_ch.name, self.intensity_value,
        (time.time() - T) * 1000
    )


def update_bump_midlevel(self, context):
    """Update callback for bump_midlevel changes.

    Updates the channel's bump midlevel input socket's default value.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    # Get the channel's bump_midlevel input socket and update its default value
    midlevel_input = get_entity_prop_input(self, 'bump_midlevel')
    if midlevel_input:
        midlevel_input.default_value = self.bump_midlevel


def update_bump_distance(self, context):
    """Update callback for bump_distance changes.

    Updates the channel's bump distance input socket's default value.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    # Get the channel's bump_distance input socket and update its default value
    distance_input = get_entity_prop_input(self, 'bump_distance')
    if distance_input:
        distance_input.default_value = self.bump_distance


def update_layer_intensity_value(self, context):
    """Update callback for layer intensity/opacity changes.

    Updates the intensity input socket's default value when layer opacity changes.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    T = time.time()

    mp = self.id_data.mp
    if mp.halt_update:
        return

    # Get the layer's intensity input socket and update its default value
    intensity_input = get_entity_prop_input(self, 'intensity_value')
    if intensity_input:
        intensity_input.default_value = self.intensity_value

    logger.info(
        "Layer %s intensity changed to %.3f in %.2f ms!",
        self.name,
        self.intensity_value,
        (time.time() - T) * 1000,
    )


def update_blend_linked(self, context):
    """Update callback when blend_linked is toggled.

    When enabled, syncs all channel blend modes to the linked_blend_type.

    Args:
        self: The property being updated (MLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    layer = self

    # Only update channels if blending is linked
    if layer.blend_linked:
        mp.halt_update = True
        try:
            for ch in layer.channels:
                ch.blend_type = layer.linked_blend_type

            # The per-channel update_blend_type callbacks were suppressed by
            # the halt flag, so rebuild the node graph here (same sequence as
            # update_blend_type) before releasing it.
            tree = get_tree(layer)
            check_all_layer_channel_io_and_nodes(layer, tree)
            check_uv_nodes(mp)

            reconnect_layer_nodes(layer)
            rearrange_layer_nodes(layer)

            reconnect_mp_nodes(self.id_data)
            rearrange_mp_nodes(self.id_data)
        finally:
            mp.halt_update = False

        logger.info(f"Blend linked enabled: synced all channels to {layer.linked_blend_type}")


def update_linked_blend_type(self, context):
    """Update callback when linked_blend_type changes.

    When blend_linked is enabled, updates all channel blend modes to match.

    Args:
        self: The property being updated (MLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    layer = self

    # Only update channels if blending is linked
    if layer.blend_linked:
        mp.halt_update = True
        try:
            for ch in layer.channels:
                ch.blend_type = layer.linked_blend_type

            # The per-channel update_blend_type callbacks were suppressed by
            # the halt flag, so rebuild the node graph here (same sequence as
            # update_blend_type) before releasing it.
            tree = get_tree(layer)
            check_all_layer_channel_io_and_nodes(layer, tree)
            check_uv_nodes(mp)

            reconnect_layer_nodes(layer)
            rearrange_layer_nodes(layer)

            reconnect_mp_nodes(self.id_data)
            rearrange_mp_nodes(self.id_data)
        finally:
            mp.halt_update = False

        logger.info(f"Linked blend type changed to {layer.linked_blend_type}")
