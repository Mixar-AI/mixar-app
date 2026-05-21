# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

from ....core.node.node_utils import get_active_mpaint_node
from ....utils.blender_commons import get_bpy_data, get_unique_name
from ....utils.common import get_addon_title


def update_new_bake_target_preset(self, context):
    """Update name for new bake target based on selected preset.

    Args:
        self: Operator instance with preset and name properties.
        context: Blender context.
    """
    node = get_active_mpaint_node()
    tree = node.node_tree
    mp = tree.mp

    tree_name = tree.name.replace(get_addon_title() + " ", "")
    if self.preset == "BLANK":
        suffix = " Bake Target"
    elif self.preset == "ORM":
        suffix = " ORM"
    elif self.preset == "DX_NORMAL":
        suffix = " Normal DirectX"

    # self.name = get_unique_name(tree_name + suffix, mp.bake_targets)
    self.name = get_unique_name(tree_name + suffix, get_bpy_data().images)
