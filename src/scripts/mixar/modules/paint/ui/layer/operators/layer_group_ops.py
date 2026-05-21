# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer group operations for moving layers in/out of groups."""

import time

import bpy
from bpy.props import EnumProperty, IntProperty

from ....core.element.update_fcurves import remap_layer_fcurves
from ....core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ....core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ....core.layer.layer_utils import (
    get_layer_index_by_name,
    get_root_height_channel,
    is_bottom_member,
    is_top_member,
)
from ....core.node.check_nodes import check_all_layer_channel_io_and_nodes
from ....core.node.height_operations import update_displacement_height_ratio
from ....core.node.node_utils import get_active_mpaint_node
from ....core.subtree.get_subtree import (
    get_index_dict,
    get_last_child_idx,
    get_lower_neighbor,
    get_parent_dict,
    get_upper_neighbor,
)
from ...list_item.list_item_operators_helper import refresh_list_items
from mixar.config.logging_config import get_logger

from ..helpers.layer_transform_utils import is_valid_parent, validate_layer_hierarchy

logger = get_logger(__name__)


class MMoveInOutLayerGroup(bpy.types.Operator):
    """Move layer into or out of a layer group"""
    bl_idname = "wm.m_move_in_out_layer_group"
    bl_label = "Move Into/Out of Group"
    bl_description = "Move layer into or out of a layer group"
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

    def execute(self, context):
        from ..helpers.layer_ui_helpers import recheck_background_layers_ios

        T = time.time()

        wm = context.window_manager
        node = get_active_mpaint_node()
        mp = node.node_tree.mp

        # Use provided layer index, or fall back to active layer
        layer_idx = self.layer_idx if self.layer_idx >= 0 else mp.active_layer_index
        layer = mp.layers[layer_idx]

        # Remember all parents and indices before modification
        parent_dict = get_parent_dict(mp)
        index_dict = get_index_dict(mp)

        moved = False

        if self.direction == "UP":
            # Check if we're at the top of a group - move OUT
            if is_top_member(layer):
                # Get parent group
                parent = mp.layers[layer.parent_idx] if layer.parent_idx >= 0 else None
                if parent:
                    # Move layer out to parent's parent level
                    # New parent becomes grandparent (or -1 if parent was top-level)
                    new_parent_idx = parent.parent_idx
                    new_parent_name = mp.layers[new_parent_idx].name if new_parent_idx >= 0 else None

                    # Move the layer physically to be just above the group
                    parent_idx = layer.parent_idx
                    mp.layers.move(layer_idx, parent_idx)

                    # Update parent dict for this layer
                    parent_dict[layer.name] = new_parent_name
                    moved = True
            else:
                # Check if upper neighbor is a GROUP - move INTO it
                neighbor_idx, neighbor = get_upper_neighbor(layer)
                if neighbor and neighbor.type == "GROUP":
                    # Move into the group as its last child
                    last_child_idx = get_last_child_idx(neighbor)

                    # Move layer to be after last child (inside the group)
                    if layer_idx != last_child_idx:
                        mp.layers.move(layer_idx, last_child_idx)

                    # Update parent dict
                    parent_dict[layer.name] = neighbor.name

                    # Expand the target group to show the moved layer
                    if hasattr(neighbor, 'expand_children'):
                        neighbor.expand_children = True
                    moved = True

        elif self.direction == "DOWN":
            # Check if we're at the bottom of a group - move OUT
            if is_bottom_member(layer):
                # Get parent group
                parent = mp.layers[layer.parent_idx] if layer.parent_idx >= 0 else None
                if parent:
                    # Move layer out to parent's parent level
                    new_parent_idx = parent.parent_idx
                    new_parent_name = mp.layers[new_parent_idx].name if new_parent_idx >= 0 else None

                    # Move the layer physically to be just below the group's last child
                    parent_last_child_idx = get_last_child_idx(parent)
                    if layer_idx != parent_last_child_idx:
                        mp.layers.move(layer_idx, parent_last_child_idx)

                    # Update parent dict for this layer
                    parent_dict[layer.name] = new_parent_name
                    moved = True
            else:
                # Check if lower neighbor is a GROUP - move INTO it
                neighbor_idx, neighbor = get_lower_neighbor(layer)
                if neighbor and neighbor.type == "GROUP":
                    # Move into the group as its first child
                    # Move layer to be right after the group header
                    mp.layers.move(layer_idx, neighbor_idx + 1)

                    # Update parent dict
                    parent_dict[layer.name] = neighbor.name

                    # Expand the target group to show the moved layer
                    if hasattr(neighbor, 'expand_children'):
                        neighbor.expand_children = True
                    moved = True

        if not moved:
            return {"CANCELLED"}

        # Remap parents - but first validate that parent assignments are valid
        for lay in mp.layers:
            # GROUP layers must always be at root level - never assign a parent
            if lay.type == 'GROUP':
                lay.parent_idx = -1
                continue

            parent_name = parent_dict[lay.name]
            # Only set parent if it's a valid GROUP (or None for root)
            if is_valid_parent(mp, parent_name):
                lay.parent_idx = get_layer_index_by_name(mp, parent_name)
            else:
                logger.warning(
                    f"Attempted to set non-GROUP '{parent_name}' as parent of '{lay.name}'. "
                    f"Setting to root level instead."
                )
                lay.parent_idx = -1

        # Validate hierarchy integrity (in case of any edge cases)
        validate_layer_hierarchy(mp)

        # Remap fcurves
        remap_layer_fcurves(mp, index_dict)

        # Height calculation can be changed after moving layer
        height_root_ch = get_root_height_channel(mp)
        if height_root_ch:
            update_displacement_height_ratio(height_root_ch)

        # Background layers should update its ios
        recheck_background_layers_ios(mp, index_dict)

        # Update GROUP layer IOs and internal nodes to ensure they have proper inputs for child layers
        # This is critical when layers are moved into/out of groups
        for lay in mp.layers:
            if lay.type == 'GROUP':
                # Update tree IOs (creates/removes input/output sockets)
                check_all_layer_channel_io_and_nodes(lay)
                # Reconnect internal nodes
                reconnect_layer_nodes(lay)
                rearrange_layer_nodes(lay)

        # Also update the moved layer's IOs and connections (its has_parent status may have changed)
        check_all_layer_channel_io_and_nodes(layer)
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        # Refresh layer channel blend nodes
        reconnect_mp_nodes(node.node_tree)
        rearrange_mp_nodes(node.node_tree)

        # Update list items
        refresh_list_items(mp, repoint_active=True)

        # Update UI
        wm.mpui.need_update = True

        logger.info(
            "Layer %s moved in/out of group in %s ms!",
            layer.name, "{:0.2f}".format((time.time() - T) * 1000)
        )
        wm.mptimer.time = str(time.time())

        return {"FINISHED"}


class MMoveInOutLayerGroupMenu(bpy.types.Menu):
    """Menu for moving layer into/out of groups"""
    bl_idname = "LAYERS_MT_move_in_out_group"
    bl_label = "Move In/Out of Group"

    def draw(self, context):
        layout = self.layout

        col = layout.column()
        op = col.operator("wm.m_move_in_out_layer_group", text="Move Up (Into/Out of Group)", icon="TRIA_UP")
        op.direction = "UP"

        op = col.operator("wm.m_move_in_out_layer_group", text="Move Down (Into/Out of Group)", icon="TRIA_DOWN")
        op.direction = "DOWN"


# Classes for registration
classes = (
    MMoveInOutLayerGroup,
    MMoveInOutLayerGroupMenu,
)
