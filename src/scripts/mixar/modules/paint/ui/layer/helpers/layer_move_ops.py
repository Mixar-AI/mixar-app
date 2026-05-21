# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer move operators for reordering paint layers."""

import time

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty

from ....core.node.node_utils import get_active_mpaint_node
from ....core.subtree.get_subtree import (
    get_index_dict,
    get_last_child_idx,
    get_lower_neighbor,
    get_parent_dict,
    get_upper_neighbor,
)
from mixar.config.logging_config import get_logger

from .layer_transform_utils import finalize_layer_move

logger = get_logger(__name__)


class MMoveLayer(bpy.types.Operator):
    bl_idname = "wm.m_move_layer"
    bl_label = "Move Layer"
    bl_description = "Move layer"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="Direction", items=(("UP", "Up", ""), ("DOWN", "Down", "")), default="UP"
    )

    layer_idx: IntProperty(
        name="Layer Index",
        description="Index of the layer to move. If -1, uses active layer",
        default=-1
    )

    @classmethod
    def poll(cls, context):
        group_node = get_active_mpaint_node()
        return group_node and len(group_node.node_tree.mp.layers) > 0

    def invoke(self, context, event):
        """Check if adjacent layer is a group and show popup if so."""
        node = get_active_mpaint_node()
        if not node:
            return {'CANCELLED'}

        mp = node.node_tree.mp
        layer_idx = self.layer_idx if self.layer_idx >= 0 else mp.active_layer_index

        if layer_idx < 0 or layer_idx >= len(mp.layers):
            return {'CANCELLED'}

        layer = mp.layers[layer_idx]

        # Get neighbor in the direction of movement
        if self.direction == "UP":
            neighbor_idx, neighbor_layer = get_upper_neighbor(layer)
        else:
            neighbor_idx, neighbor_layer = get_lower_neighbor(layer)

        # If neighbor is a group and current layer is not a group, show popup
        if neighbor_layer and neighbor_layer.type == "GROUP" and layer.type != "GROUP":
            # Store info for the popup
            context.window_manager.mixar_move_layer_idx = layer_idx
            context.window_manager.mixar_move_direction = self.direction
            context.window_manager.mixar_move_group_name = neighbor_layer.name
            return context.window_manager.invoke_popup(self, width=250)

        # Otherwise just execute normally
        return self.execute(context)

    def draw(self, context):
        """Draw popup asking user where to move the layer."""
        layout = self.layout
        wm = context.window_manager

        group_name = getattr(wm, 'mixar_move_group_name', 'Group')
        direction = getattr(wm, 'mixar_move_direction', 'UP')

        col = layout.column(align=True)
        col.label(text=f"Group '{group_name}' is adjacent", icon='FILE_FOLDER')
        col.separator()

        # Move into group option
        row = col.row(align=True)
        row.scale_y = 1.4
        op = row.operator("wm.m_move_layer_with_option", text="Move Into Group", icon='IMPORT')
        op.move_into_group = True
        op.direction = direction

        col.separator(factor=0.5)

        # Move past group option
        row = col.row(align=True)
        row.scale_y = 1.4
        op = row.operator("wm.m_move_layer_with_option", text="Move Past Group", icon='EXPORT')
        op.move_into_group = False
        op.direction = direction

    def execute(self, context):
        """Execute move (used when no group is adjacent)."""
        return self._do_move(context, move_into_group=False)

    def _do_move(self, context, move_into_group=False):
        """Perform the actual layer move."""
        T = time.time()

        wm = context.window_manager
        node = get_active_mpaint_node()
        mp = node.node_tree.mp

        num_layers = len(mp.layers)
        # Use provided layer index, or fall back to active layer
        layer_idx = self.layer_idx if self.layer_idx >= 0 else mp.active_layer_index
        layer = mp.layers[layer_idx]
        layer_name = layer.name  # Store name to find new index after move

        # Get last member of group if selected layer is a group
        last_member_idx = get_last_child_idx(layer)

        # Get neighbor
        neighbor_idx = None
        neighbor_layer = None

        if self.direction == "UP":
            neighbor_idx, neighbor_layer = get_upper_neighbor(layer)

        elif self.direction == "DOWN":
            neighbor_idx, neighbor_layer = get_lower_neighbor(layer)

        if not neighbor_layer:
            return {"CANCELLED"}

        # Capture neighbor name before any move (refs become stale after mp.layers.move())
        neighbor_name = neighbor_layer.name

        # Remember all parents and indices
        parent_dict = get_parent_dict(mp)
        index_dict = get_index_dict(mp)

        if layer.type == "GROUP" and neighbor_layer.type != "GROUP":

            # Group layer UP to standard layer
            if self.direction == "UP":
                mp.layers.move(neighbor_idx, last_member_idx)

            # Group layer DOWN to standard layer
            elif self.direction == "DOWN":
                mp.layers.move(neighbor_idx, layer_idx)

        elif layer.type == "GROUP" and neighbor_layer.type == "GROUP":

            # Group layer UP to group layer
            if self.direction == "UP":
                for i in range(last_member_idx + 1 - layer_idx):
                    mp.layers.move(layer_idx + i, neighbor_idx + i)

            # Group layer DOWN to group layer
            elif self.direction == "DOWN":
                last_neighbor_member_idx = get_last_child_idx(neighbor_layer)
                num_members = last_neighbor_member_idx + 1 - neighbor_idx

                for i in range(num_members):
                    mp.layers.move(neighbor_idx + i, layer_idx + i)

        elif layer.type != "GROUP" and neighbor_layer.type == "GROUP":

            if move_into_group:
                # Move INTO the group
                if self.direction == "UP":
                    # Layer is below the group, wants to move up into it
                    # The layer is already positioned correctly (right after group's last child)
                    # Just update the parent - no physical move needed
                    parent_dict[layer_name] = neighbor_name
                else:
                    # Layer is above the group, wants to move down into it
                    # Move layer to be right after the group header (first child position)
                    # Since layer is above group, after move it should be at neighbor_idx + 1
                    # But we're moving from a lower index to a higher one
                    last_child_idx = get_last_child_idx(neighbor_layer)
                    mp.layers.move(layer_idx, last_child_idx)
                    # NOTE: Use layer_name/neighbor_name because refs become stale after mp.layers.move()
                    parent_dict[layer_name] = neighbor_name

                # Expand the target group to show the moved layer
                # NOTE: neighbor_layer ref may be stale, but expand_children should still work
                if hasattr(neighbor_layer, 'expand_children'):
                    neighbor_layer.expand_children = True
            else:
                # Move PAST the group (original behavior)
                if self.direction == "UP":
                    mp.layers.move(layer_idx, neighbor_idx)
                else:
                    last_neighbor_member_idx = get_last_child_idx(neighbor_layer)
                    mp.layers.move(layer_idx, last_neighbor_member_idx)

                # IMPORTANT: Clear parent relationship when exiting a group
                # The layer is now at root level, not inside any group
                # NOTE: Use layer_name (captured before move) because layer ref becomes stale after mp.layers.move()
                parent_dict[layer_name] = None

        # Standard layer to standard Layer
        else:
            # Capture parent indices BEFORE move (refs become stale after mp.layers.move())
            layer_parent_idx = layer.parent_idx
            neighbor_parent_idx = neighbor_layer.parent_idx

            mp.layers.move(layer_idx, neighbor_idx)

            # Check if layer is leaving a group (moving to a different hierarchy level)
            # This happens when a layer inside a group moves past the group boundary
            # to a standard layer outside the group
            if layer_parent_idx != neighbor_parent_idx:
                # Layer is crossing hierarchy boundary - update parent to match neighbor's level
                # NOTE: Use layer_name (captured before move) because layer ref becomes stale
                if neighbor_parent_idx == -1:
                    # Neighbor is at root level, so layer should also be at root level
                    parent_dict[layer_name] = None
                else:
                    # Neighbor is in a different group, so layer should join that group
                    # Get the neighbor's parent name from parent_dict (captured before move)
                    parent_dict[layer_name] = parent_dict[neighbor_name]

        # Finalize the move (remap parents, update nodes, refresh UI)
        finalize_layer_move(context, node, mp, layer_name, parent_dict, index_dict)

        logger.info(
            "Layer %s is moved in %s ms!",
            layer_name, "{:0.2f}".format((time.time() - T) * 1000)
        )
        wm.mptimer.time = str(time.time())

        return {"FINISHED"}


class MMoveLayerWithOption(bpy.types.Operator):
    """Move layer with specific option (into or past group)"""
    bl_idname = "wm.m_move_layer_with_option"
    bl_label = "Move Layer"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    direction: EnumProperty(
        name="Direction", items=(("UP", "Up", ""), ("DOWN", "Down", "")), default="UP"
    )

    move_into_group: BoolProperty(
        name="Move Into Group",
        default=False
    )

    def execute(self, context):
        """Execute the move with the selected option."""
        T = time.time()

        wm = context.window_manager
        node = get_active_mpaint_node()
        if not node:
            return {'CANCELLED'}

        mp = node.node_tree.mp
        layer_idx = getattr(wm, 'mixar_move_layer_idx', mp.active_layer_index)

        if layer_idx < 0 or layer_idx >= len(mp.layers):
            return {'CANCELLED'}

        layer = mp.layers[layer_idx]
        layer_name = layer.name

        # Get neighbor
        if self.direction == "UP":
            neighbor_idx, neighbor_layer = get_upper_neighbor(layer)
        else:
            neighbor_idx, neighbor_layer = get_lower_neighbor(layer)

        if not neighbor_layer or neighbor_layer.type != "GROUP":
            return {'CANCELLED'}

        # Capture neighbor name before any move (refs become stale after mp.layers.move())
        neighbor_name = neighbor_layer.name

        # Remember all parents and indices
        parent_dict = get_parent_dict(mp)
        index_dict = get_index_dict(mp)

        if self.move_into_group:
            # Move INTO the group
            if self.direction == "UP":
                # Layer is below the group, wants to move up into it
                # The layer is already positioned correctly (right after group's last child)
                # Just update the parent - no physical move needed
                parent_dict[layer_name] = neighbor_name
            else:
                # Layer is above the group, wants to move down into it
                # Move layer to be at the last child position (after existing children)
                last_child_idx = get_last_child_idx(neighbor_layer)
                mp.layers.move(layer_idx, last_child_idx)
                # NOTE: Use layer_name/neighbor_name because refs become stale after mp.layers.move()
                parent_dict[layer_name] = neighbor_name

            # Expand the target group to show the moved layer
            # NOTE: neighbor_layer ref may be stale, but expand_children should still work
            if hasattr(neighbor_layer, 'expand_children'):
                neighbor_layer.expand_children = True
        else:
            # Move PAST the group
            if self.direction == "UP":
                mp.layers.move(layer_idx, neighbor_idx)
            else:
                last_neighbor_member_idx = get_last_child_idx(neighbor_layer)
                mp.layers.move(layer_idx, last_neighbor_member_idx)

            # IMPORTANT: Clear parent relationship when exiting a group
            # The layer is now at root level, not inside any group
            # NOTE: Use layer_name (captured before move) because layer ref becomes stale after mp.layers.move()
            parent_dict[layer_name] = None

        # Finalize the move (remap parents, update nodes, refresh UI)
        finalize_layer_move(context, node, mp, layer_name, parent_dict, index_dict)

        logger.info(
            "Layer %s is moved in %s ms!",
            layer_name, "{:0.2f}".format((time.time() - T) * 1000)
        )
        wm.mptimer.time = str(time.time())

        return {"FINISHED"}


# Classes for registration
classes = (
    MMoveLayer,
    MMoveLayerWithOption,
)
