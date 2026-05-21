# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer channel property callback functions for normal map related operations.

This module contains callbacks for normal map type, normal space, backface flip,
write height, and voronoi feature changes.
"""

import re

from ......config.logging_config import get_logger

logger = get_logger(__name__)

from ....core.io.input_outputs.input_outputs import check_layer_channel_linear_node, check_layer_tree_ios
from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ....core.layer.check_channels import check_start_end_root_ch_nodes
from ....core.node.check_nodes import check_all_layer_channel_io_and_nodes, check_uv_nodes
from ....core.node.get_nodes import (
    get_channel_source,
    get_layer_source,
)
from ....core.node.height_operations import update_displacement_height_ratio
from ....core.subtree.get_subtree import get_tree
from ...list_item.list_item_operators_helper import refresh_list_items


def update_normal_map_type(self, context):
    """Update callback for normal map type changes.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return
    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    if not m:
        return
    layer_idx = int(m.group(1))
    ch_idx = int(m.group(2))
    if layer_idx >= len(mp.layers) or ch_idx >= len(mp.channels):
        return
    layer = mp.layers[layer_idx]
    root_ch = mp.channels[ch_idx]
    tree = get_tree(layer)

    # Auto-set override_type to LAYER if user sets a normal_map_type that requires
    # processing nodes. PASSTHROUGH mode doesn't create height_proc/normal_map_proc nodes.
    processing_types = {'BUMP_MAP', 'BUMP_NORMAL_MAP', 'NORMAL_MAP', 'VECTOR_DISPLACEMENT_MAP'}
    if (hasattr(self, 'override_type') and
        self.override_type == 'PASSTHROUGH' and
        self.normal_map_type in processing_types):
        self.override_type = 'LAYER'

    check_all_layer_channel_io_and_nodes(layer, tree, self)
    check_start_end_root_ch_nodes(self.id_data)
    check_uv_nodes(mp)

    check_layer_tree_ios(layer, tree)

    if mp.layer_preview_mode:
        # Set correct active edit
        if self.normal_map_type == "BUMP_MAP" and self.active_edit_1:
            self.active_edit = True
        elif self.normal_map_type == "NORMAL_MAP" and self.active_edit:
            self.active_edit_1 = True
    else:
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        reconnect_mp_nodes(self.id_data)
        rearrange_mp_nodes(self.id_data)

    # Update list items
    refresh_list_items(mp)


def update_normal_space(self, context):
    """Update callback for normal space type changes.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
    mp = self.id_data.mp
    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    if not m:
        return
    layer_idx = int(m.group(1))
    if layer_idx >= len(mp.layers):
        return
    layer = mp.layers[layer_idx]
    tree = get_tree(layer)

    normal_map_proc = tree.nodes.get(self.normal_map_proc)
    if normal_map_proc:
        normal_map_proc.space = self.normal_space


def update_flip_backface_normal(self, context):
    """Update callback for backface normal flip setting.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return
    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    if not m:
        return
    layer_idx = int(m.group(1))
    if layer_idx >= len(mp.layers):
        return
    layer = mp.layers[layer_idx]
    tree = get_tree(layer)

    normal_flip = tree.nodes.get(self.normal_flip)
    if normal_flip:
        normal_flip.mute = self.invert_backface_normal


def update_write_height(self, context):
    """Update callback for write height setting changes.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
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
    ch = self
    tree = get_tree(layer)

    check_all_layer_channel_io_and_nodes(layer, tree, self)
    update_displacement_height_ratio(root_ch)
    check_start_end_root_ch_nodes(self.id_data)
    check_uv_nodes(mp)

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    reconnect_mp_nodes(self.id_data)
    rearrange_mp_nodes(self.id_data)


def update_voronoi_feature(self, context):
    """Update callback for layer voronoi feature changes.

    Args:
        self: The property being updated (YLayer).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return
    layer = self

    if layer.type != "VORONOI":
        return

    source = get_layer_source(layer)
    source.feature = layer.voronoi_feature

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)


def update_layer_channel_voronoi_feature(self, context):
    """Update callback for layer channel voronoi feature changes.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return
    m = re.match(r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", self.path_from_id())
    if not m:
        return
    layer_idx = int(m.group(1))
    if layer_idx >= len(mp.layers):
        return
    layer = mp.layers[layer_idx]
    ch = self

    source = None
    if ch.override_type == "VORONOI":
        source = get_channel_source(ch)

    if not source:
        tree = get_tree(layer)
        source = tree.nodes.get(ch.cache_voronoi)

    if source:
        source.feature = ch.voronoi_feature

        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)


def update_layer_input(self, context):
    """Update callback for layer input type changes.

    Args:
        self: The property being updated (YLayerChannel).
        context: Blender context.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    check_layer_channel_linear_node(self, reconnect=True)
