# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Update callbacks for mask name and enable state changes."""

import re

from ...core.layer.check_channels import check_start_end_root_ch_nodes
from ...core.layer.update_layers import change_layer_name
from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ...core.node.check_nodes import (
    check_all_layer_channel_io_and_nodes,
    check_uv_nodes,
)
from ...core.node.get_nodes import get_mask_source
from ...core.subtree.get_subtree import get_tree
from ...utils.blender_commons import get_active_object
from ..list_item.list_item_operators_helper import refresh_list_items
from ..list_item.list_item_utils import set_active_entity_item


def update_mask_name(self, context):
    """Update callback when mask name changes, synchronizing with layer name if needed.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
    """

    mp = self.id_data.mp
    if mp.halt_update:
        return
    match = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", self.path_from_id())
    if not match:
        return
    layer = mp.layers[int(match.group(1))]
    src = get_mask_source(self)

    # Also update layer name if mask name is renamed in certain pattern
    m = re.match(r"^Mask\s.*\((.+)\)$", self.name)
    if m:
        old_layer_name = layer.name
        new_layer_name = m.group(1)

        mp.halt_update = True
        layer.name = new_layer_name

        # Also update other mask names
        for mask in layer.masks:
            if mask == self:
                continue
            mm = re.match(r"^Mask\s.*\((.+)\)$", mask.name)
            if mm:
                mask.name = mask.name.replace(mm.group(1), new_layer_name)

        mp.halt_update = False

    if self.type == "IMAGE" and self.segment_name != "":
        return
    change_layer_name(mp, get_active_object(), src, self, layer.masks)


def update_layer_mask_enable(self, context):
    """Update callback when mask enable state changes.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    match = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", self.path_from_id())
    if not match:
        return
    layer = mp.layers[int(match.group(1))]
    tree = get_tree(layer)

    # check_mask_mix_nodes(layer, tree, self)

    check_uv_nodes(mp)
    check_all_layer_channel_io_and_nodes(layer, tree)
    check_start_end_root_ch_nodes(layer.id_data)

    reconnect_layer_nodes(layer)
    rearrange_layer_nodes(layer)

    # for ch in self.channels:
    #    update_layer_mask_channel_enable(ch, context)

    reconnect_mp_nodes(self.id_data)
    rearrange_mp_nodes(self.id_data)

    self.active_edit = self.enable and self.type in {"IMAGE", "VCOL", "COLOR_ID"}

    # Update list items
    refresh_list_items(mp, repoint_active=True)


def update_mask_active_edit(self, context):
    """Update callback when mask active edit state changes.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return
    if self.halt_update:
        return

    # Only image mask can be edited
    # if self.active_edit and self.type not in {'IMAGE', 'VCOL'}:
    #    self.halt_update = True
    #    self.active_edit = False
    #    self.halt_update = False
    #    return

    mp = self.id_data.mp

    try:
        match = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", self.path_from_id())
        if not match:
            return
        layer_idx = int(match.group(1))
        if layer_idx >= len(mp.layers):
            return
        layer = mp.layers[layer_idx]
        mask_idx = int(match.group(2))
        if mask_idx >= len(layer.masks):
            return

        # Disable other active edits
        if self.active_edit:
            mp.halt_update = True
            for c in layer.channels:
                c.active_edit = False
                c.active_edit_1 = False

            for m in layer.masks:
                if m == self:
                    continue
                # m.halt_update = True
                m.active_edit = False
                # m.halt_update = False

            mp.halt_update = False

        # Refresh
        mp.active_layer_index = layer_idx

        # Set active subitem - wrap in try-except since list_items might be inconsistent
        try:
            set_active_entity_item(self)
        except (IndexError, AttributeError, ReferenceError):
            pass  # list_items in inconsistent state, skip
    except (IndexError, AttributeError, ReferenceError):
        pass  # Data in inconsistent state during mask creation
