# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer movement operator for Mixar layers system"""

from bpy.props import EnumProperty, IntProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_mp_nodes
from ...core.node.node_utils import get_active_mpaint_node
from ..utils.ui_refresh import request_ui_refresh

logger = get_logger(__name__)


class LAYERS_OT_MoveLayer(Operator):
    """Move layer up or down"""

    bl_idname = "layers.move_layer"
    bl_label = "Move Layer"
    bl_description = "Move layer up or down"
    bl_options = {"REGISTER", "UNDO"}

    index: IntProperty()

    direction: EnumProperty(
        items=[
            ("UP", "Up", "Move up"),
            ("DOWN", "Down", "Move down"),
        ]
    )

    @classmethod
    def poll(cls, context):
        return get_active_mpaint_node() is not None

    def execute(self, context):
        """Move layer up or down in the layer list and update the node tree.

        Args:
            context: Blender context.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on failure.
        """
        node = get_active_mpaint_node()
        if not node:
            return {"CANCELLED"}

        group_tree = node.node_tree
        mp = group_tree.mp
        scene = context.scene
        layers = scene.mixar_layers

        if self.direction == "UP" and self.index > 0:
            new_index = self.index - 1
        elif self.direction == "DOWN" and self.index < len(layers) - 1:
            new_index = self.index + 1
        else:
            return {"CANCELLED"}

        # Move in the UI list
        layers.move(self.index, new_index)
        scene.mixar_active_layer_index = new_index

        # Move in the backend mp.layers and update the node tree
        if self.index < len(mp.layers) and new_index < len(mp.layers):
            mp.layers.move(self.index, new_index)
            mp.active_layer_index = new_index

            reconnect_mp_nodes(group_tree)
            rearrange_mp_nodes(group_tree)
        else:
            logger.warning(
                "mp.layers index out of range (%d/%d), skipping node update",
                self.index, len(mp.layers),
            )

        request_ui_refresh()
        return {"FINISHED"}


# Classes for registration
classes = (
    LAYERS_OT_MoveLayer,
)
