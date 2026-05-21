# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import bpy
from bpy.props import *

from ...core.node.node_utils import get_active_mpaint_node
from .list_item_operators_helper import refresh_list_items


class MRefreshListItems(bpy.types.Operator):
    bl_idname = "wm.m_refresh_list_items"
    bl_label = "Refresh List Items"
    bl_description = "Refresh List Items"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed.

        Args:
            context: Blender context object.

        Returns:
            bool: True if there is an active mpaint node, False otherwise.
        """
        return get_active_mpaint_node()

    def execute(self, context):
        """Execute the refresh list items operation.

        Refreshes all list items for the active mpaint node.

        Args:
            context: Blender context object.

        Returns:
            set: {'FINISHED'} to indicate successful completion.
        """
        node = get_active_mpaint_node()
        mp = node.node_tree.mp

        refresh_list_items(mp)

        return {'FINISHED'}


classes = (
    MRefreshListItems,
)