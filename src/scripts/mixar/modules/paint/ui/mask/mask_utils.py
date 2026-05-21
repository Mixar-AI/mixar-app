# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ...core.node.check_nodes import (
    check_all_layer_channel_io_and_nodes,
    check_uv_nodes,
)
from ...core.node.get_nodes import get_mask_source
from ...core.subtree.get_subtree import get_tree


def update_mask_texcoord_type(self, context, reconnect=True):
    """Update callback when mask texture coordinate type changes.

    Args:
        self: YLayerMask property group being updated.
        context: Blender context object.
        reconnect (bool, optional): Whether to reconnect and rearrange nodes. Defaults to True.
    """
    mp = self.id_data.mp
    if mp.halt_update:
        return

    match = re.match(r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", self.path_from_id())
    layer = mp.layers[int(match.group(1))]
    mask_idx = int(match.group(2))
    mask = self
    tree = get_tree(layer)

    # Update global uv
    check_uv_nodes(mp)

    # Update layer tree inputs
    check_all_layer_channel_io_and_nodes(layer, tree)

    # Set image source projection
    if mask.type == "IMAGE":
        source = get_mask_source(mask)
        source.projection = (
            "BOX" if mask.texcoord_type in {"Generated", "Object"} else "FLAT"
        )

    if reconnect:
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        reconnect_mp_nodes(self.id_data)
        rearrange_mp_nodes(self.id_data)
