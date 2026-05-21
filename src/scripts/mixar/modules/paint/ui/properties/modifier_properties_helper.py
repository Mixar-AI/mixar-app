# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re
from ...core.modifier.modifier_commons import check_modifier_nodes
from ...core.modifier.modifier import get_mod_tree
from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes


def update_modifier_enable(self, context):
    """Update callback when modifier enable state changes.

    Checks modifier nodes and reconnects/rearranges layer or root nodes based on
    the modifier's location in the property hierarchy.

    Args:
        self: The modifier property instance.
        context: The Blender context.

    Returns:
        None
    """
    mp = self.id_data.mp
    if mp.halt_update: return
    tree = get_mod_tree(self)

    check_modifier_nodes(self, tree)

    match1 = re.match(r'mp\.layers\[(\d+)\]\.channels\[(\d+)\]\.modifiers\[(\d+)\]', self.path_from_id())
    match2 = re.match(r'mp\.layers\[(\d+)\]\.modifiers\[(\d+)\]', self.path_from_id())
    match3 = re.match(r'mp\.channels\[(\d+)\]\.modifiers\[(\d+)\]', self.path_from_id())

    if match1 or match2:
        if match1: layer = mp.layers[int(match1.group(1))]
        else: layer = mp.layers[int(match2.group(1))]

        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

    elif match3:
        channel = mp.channels[int(match3.group(1))]
        reconnect_mp_nodes(self.id_data)
        rearrange_mp_nodes(self.id_data)
