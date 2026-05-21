# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Material and cleanup operators for Mixar layers system

This module re-exports operators from split files for backward compatibility:
- create_material_op.py: LAYERS_OT_CreateMaterial
- material_slot_ops.py: Material slot operators
"""

import bpy
from bpy.types import Operator

from .....config.logging_config import get_logger
logger = get_logger(__name__)

from ...core.node.node_utils import get_active_mpaint_node
from ...utils.blender_commons import get_active_material
from ...utils.common import get_addon_title, get_mix_color_indices
from ...utils.constants import AO_MULTIPLY
from ..utils.ui_refresh import request_ui_refresh

# Re-export classes from split files
from .create_material_op import LAYERS_OT_CreateMaterial
from .material_slot_ops import (
    MATERIALS_OT_AddMaterialSlot,
    MATERIALS_OT_RemoveMaterialSlot,
    MATERIALS_OT_MoveMaterialSlot,
)


class LAYERS_OT_RemoveMPaintNode(Operator):
    """Remove Mixar Paint node from material"""

    bl_idname = "wm.m_remove_mp_node"
    bl_label = "Remove " + get_addon_title() + " Node"
    bl_description = "Remove " + get_addon_title() + " node, but keep all baked channel image(s)"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        node = get_active_mpaint_node()
        result = bool(node)
        return result

    def is_baked(self, mp=None):
        if not mp:
            group_node = get_active_mpaint_node()
            if not group_node or not group_node.node_tree:
                return False
            tree = group_node.node_tree
            mp = tree.mp

        return any([c.baked for c in mp.channels if c.baked != ''])

    def invoke(self, context, event):
        if self.is_baked():
            return self.execute(context)
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.label(text="This " + get_addon_title() + " node setup isn't baked yet!")
        self.layout.label(text="Are you sure want to delete?")

    def execute(self, context):
        mat = get_active_material()
        group_node = get_active_mpaint_node()

        if not group_node or not group_node.node_tree:
            return {'CANCELLED'}

        tree = group_node.node_tree
        mp = tree.mp

        if self.is_baked(mp):
            if not mp.use_baked:
                mp.use_baked = True
        else:
            # Search for AO node
            if 'Ambient Occlusion' in mp.channels:
                ao_node = mat.node_tree.nodes.get(AO_MULTIPLY)
                if ao_node:
                    ao_mixcol0, ao_mixcol1, ao_mixout = get_mix_color_indices(ao_node)
                    socket_ins = [l.from_socket for l in ao_node.inputs[ao_mixcol0].links]
                    socket_outs = [l.to_socket for l in ao_node.outputs[ao_mixout].links]

                    for si in socket_ins:
                        for so in socket_outs:
                            mat.node_tree.links.new(si, so)

                    mat.node_tree.nodes.remove(ao_node)

        if self.is_baked(mp) and not mp.enable_baked_outside:
            mp.enable_baked_outside = True

        # Remove the mp node using simple node removal
        # Reconnect links if input and output has same name
        for inp in group_node.inputs:
            if len(inp.links) == 0:
                continue
            outp = group_node.outputs.get(inp.name)
            if not outp:
                continue
            for link in outp.links:
                mat.node_tree.links.new(inp.links[0].from_socket, link.to_socket)

        # Remove the node tree data if it has only one user
        if group_node.node_tree and group_node.node_tree.users == 1:
            bpy.data.node_groups.remove(group_node.node_tree)

        # Remove the node itself
        mat.node_tree.nodes.remove(group_node)

        # Request UI refresh
        request_ui_refresh()

        return {'FINISHED'}


# Only register classes defined in this file
# Imported classes are registered by their source modules to avoid double registration
# (create_material_op.py, material_slot_ops.py)
classes = (
    LAYERS_OT_RemoveMPaintNode,
)
