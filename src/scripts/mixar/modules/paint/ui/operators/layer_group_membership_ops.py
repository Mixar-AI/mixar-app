# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Layer group membership operators for Mixar layers system.

This module provides operators for managing layer group membership including
adding layers to existing groups, moving layers to new groups, and removing
layers from groups.
"""

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty
from bpy.types import Operator

from .....config.logging_config import get_logger

logger = get_logger(__name__)

from ...core.io.arrangements.layer_arrangements import rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_mp_nodes
from ...core.node.node_utils import get_active_mpaint_node
from ...core.subtree.layer_hierarchy import get_list_of_all_children_and_child_ids
from ..utils.ui_refresh import request_ui_refresh


def get_available_groups(self, context):
    """Get list of available group layers for the enum property.

    Args:
        context: Blender context.

    Returns:
        list: List of tuples (identifier, name, description) for enum items.
    """
    items = [('-1', 'Root Level (No Group)', 'Move layers to root level')]

    node = get_active_mpaint_node()
    if not node:
        return items

    mp = node.node_tree.mp

    # Get the selected layer indices to exclude them and their children from targets
    wm = context.window_manager
    selected_indices = set()
    if hasattr(wm, 'mixar_ui'):
        for i, ui_layer in enumerate(wm.mixar_ui.ui_layers):
            if ui_layer.selected and i < len(mp.layers):
                selected_indices.add(i)
                # Also exclude all children of selected groups
                layer = mp.layers[i]
                if layer.type == 'GROUP':
                    _, child_ids = get_list_of_all_children_and_child_ids(layer)
                    selected_indices.update(child_ids)

    # Add all GROUP type layers as options (except selected ones and their children)
    for i, layer in enumerate(mp.layers):
        if layer.type == 'GROUP' and i not in selected_indices:
            items.append((str(i), layer.name, f'Add layers to "{layer.name}" group'))

    return items


class LAYERS_OT_MoveSelectedToGroup(Operator):
    """Move all selected layers into a layer group"""

    bl_idname = "layers.move_selected_to_group"
    bl_label = "Move Selected to Group"
    bl_description = "Move all selected layers into a new layer group"
    bl_options = {"REGISTER", "UNDO"}

    group_name: StringProperty(
        name="Group Name",
        description="Name for the new layer group",
        default="Layer Group"
    )

    @classmethod
    def poll(cls, context):
        """Check if operator can be executed."""
        wm = context.window_manager
        if not hasattr(wm, 'mixar_ui'):
            return False
        return any(layer.selected for layer in wm.mixar_ui.ui_layers)

    def invoke(self, context, event):
        """Initialize group name and show dialog."""
        wm = context.window_manager
        if not hasattr(wm, 'mixar_ui'):
            return {'CANCELLED'}

        selected_count = sum(1 for layer in wm.mixar_ui.ui_layers if layer.selected)
        self.group_name = f"Group ({selected_count} layers)"

        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        """Draw group creation dialog UI."""
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        wm = context.window_manager
        main_col = layout.column(align=False)

        group_box = main_col.box()
        group_col = group_box.column(align=False)

        # Header
        header_row = group_col.row(align=True)
        header_row.scale_y = 1.4
        selected_count = sum(1 for layer in wm.mixar_ui.ui_layers if layer.selected)
        header_row.label(text="Move to Group", icon='GROUP')

        group_col.separator(factor=1.2)

        # Info text
        info_row = group_col.row(align=True)
        info_row.label(text=f"Moving {selected_count} layer(s) to group", icon='INFO')

        group_col.separator(factor=0.4)

        # Group name input
        name_row = group_col.row(align=True)
        name_row.scale_y = 1.4
        name_split = name_row.split(factor=0.25, align=True)
        label_col = name_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Name:")
        name_split.prop(self, "group_name", text="")

        group_col.separator(factor=0.4)
        group_col.separator(factor=0.8)

    def execute(self, context):
        """Move selected layers into a new group."""
        from ..layer.helpers.layer_create_helpers import add_new_layer
        from ...utils.blender_commons import get_unique_name

        wm = context.window_manager
        if not hasattr(wm, 'mixar_ui'):
            return {'CANCELLED'}

        node = get_active_mpaint_node()
        if not node:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp
        group_tree = node.node_tree

        # Get selected layer names (store by name since indices may shift after group creation)
        selected_layer_names = []
        for i, ui_layer in enumerate(wm.mixar_ui.ui_layers):
            if ui_layer.selected and i < len(mp.layers):
                selected_layer_names.append(mp.layers[i].name)

        # Fallback to active layer if nothing selected
        if not selected_layer_names:
            active_idx = mp.active_layer_index
            if active_idx >= 0 and active_idx < len(mp.layers):
                selected_layer_names.append(mp.layers[active_idx].name)
            else:
                self.report({'WARNING'}, "No layers selected")
                return {'CANCELLED'}

        # Ensure unique group name
        group_name = get_unique_name(self.group_name, mp.layers)

        # Halt updates during group creation
        mp.halt_update = True

        try:
            # Create new GROUP layer
            group_layer = add_new_layer(
                group_tree=group_tree,
                layer_name=group_name,
                layer_type='GROUP',
                channel_idx=0,
                blend_type='MIX',
                normal_blend_type='MIX',
                normal_map_type='BUMP_MAP',
                texcoord_type='UV',
            )

            # Get the index of the newly created group
            group_idx = None
            for i, layer in enumerate(mp.layers):
                if layer.name == group_layer.name:
                    group_idx = i
                    break

            if group_idx is None:
                self.report({'ERROR'}, "Failed to find created group")
                return {'CANCELLED'}

            # Find layers to move by name (indices may have shifted after group creation)
            layers_to_move = []
            for layer in mp.layers:
                if layer.name in selected_layer_names and layer.name != group_layer.name:
                    layers_to_move.append(layer)

            moved_count = 0
            for layer in layers_to_move:
                # Skip layers already in the target group
                if layer.parent_idx == group_idx:
                    continue

                # Update parent_idx
                layer.parent_idx = group_idx
                moved_count += 1
                logger.info(f"Moved layer '{layer.name}' into group '{group_name}'")

            # Expand the new group to show children
            group_layer.expand_children = True

        finally:
            mp.halt_update = False

        # Reconnect and rearrange nodes
        reconnect_mp_nodes(group_tree)
        rearrange_mp_nodes(group_tree)

        # Clear selections after operation
        for ui_layer in wm.mixar_ui.ui_layers:
            ui_layer.selected = False

        request_ui_refresh()

        self.report({'INFO'}, f"Created group '{group_name}' with {moved_count} layer(s)")

        return {"FINISHED"}


class LAYERS_OT_AddLayersToGroup(Operator):
    """Add selected layers or active layer to an existing group"""

    bl_idname = "layers.add_layers_to_group"
    bl_label = "Add to Group"
    bl_description = "Add selected layers to an existing group"
    bl_options = {"REGISTER", "UNDO"}

    target_group: EnumProperty(
        name="Target Group",
        description="Select the group to add layers to",
        items=get_available_groups,
    )

    layer_index: IntProperty(
        name="Layer Index",
        description="Index of a specific layer to add to group (-1 to use selection)",
        default=-1
    )

    @classmethod
    def poll(cls, context):
        """Check if operator can be executed."""
        return get_active_mpaint_node() is not None

    def invoke(self, context, event):
        """Show dialog for selecting target group."""
        node = get_active_mpaint_node()
        if not node:
            return {'CANCELLED'}

        mp = node.node_tree.mp
        has_groups = any(layer.type == 'GROUP' for layer in mp.layers)

        if not has_groups:
            self.report({'WARNING'}, "No groups available. Create a group first.")
            return {'CANCELLED'}

        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        """Draw the group selection dialog UI."""
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        node = get_active_mpaint_node()
        mp = node.node_tree.mp
        wm = context.window_manager

        main_col = layout.column(align=False)

        group_box = main_col.box()
        group_col = group_box.column(align=False)

        # Header
        header_row = group_col.row(align=True)
        header_row.scale_y = 1.4
        header_row.label(text="Add to Group", icon='GROUP')

        group_col.separator(factor=1.2)

        # Info about affected layers
        if self.layer_index >= 0 and self.layer_index < len(mp.layers):
            layer = mp.layers[self.layer_index]
            info_row = group_col.row(align=True)
            info_row.label(text=f'Adding layer: "{layer.name}"', icon='INFO')
        else:
            selected_count = 0
            if hasattr(wm, 'mixar_ui'):
                selected_count = sum(1 for layer in wm.mixar_ui.ui_layers if layer.selected)
            info_row = group_col.row(align=True)
            if selected_count > 0:
                info_row.label(text=f"Adding {selected_count} selected layer(s)", icon='INFO')
            else:
                # Fallback to active layer
                active_idx = mp.active_layer_index
                if active_idx >= 0 and active_idx < len(mp.layers):
                    active_layer = mp.layers[active_idx]
                    info_row.label(text=f'Adding active layer: "{active_layer.name}"', icon='INFO')
                else:
                    info_row.label(text="No layers selected", icon='ERROR')

        group_col.separator(factor=0.4)

        # Group selection dropdown
        group_row = group_col.row(align=True)
        group_row.scale_y = 1.4
        group_split = group_row.split(factor=0.25, align=True)
        label_col = group_split.column(align=True)
        label_col.alignment = "RIGHT"
        label_col.label(text="Group:")
        group_split.prop(self, "target_group", text="")

        group_col.separator(factor=0.8)

    def execute(self, context):
        """Add layers to the selected group."""
        node = get_active_mpaint_node()
        if not node:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp
        wm = context.window_manager
        group_tree = node.node_tree

        target_idx = int(self.target_group)
        layers_to_move = self._get_layers_to_move(mp, wm)

        if not layers_to_move:
            self.report({'WARNING'}, "No layers to add to group")
            return {'CANCELLED'}

        # Validate no circular references
        if not self._validate_no_circular_refs(mp, target_idx, layers_to_move):
            return {'CANCELLED'}

        # Update parent_idx for each layer
        moved_count = self._update_layer_parents(mp, layers_to_move, target_idx)

        if moved_count == 0:
            self.report({'INFO'}, "Layers are already in the target group")
            return {'FINISHED'}

        # Expand target group
        if target_idx != -1:
            target_layer = mp.layers[target_idx]
            if hasattr(target_layer, 'expand_children'):
                target_layer.expand_children = True

        # Reconnect and rearrange nodes
        reconnect_mp_nodes(group_tree)
        rearrange_mp_nodes(group_tree)

        # Clear selections
        if hasattr(wm, 'mixar_ui'):
            for ui_layer in wm.mixar_ui.ui_layers:
                ui_layer.selected = False

        request_ui_refresh()

        if target_idx == -1:
            self.report({'INFO'}, f"Moved {moved_count} layer(s) to root level")
        else:
            target_name = mp.layers[target_idx].name
            self.report({'INFO'}, f"Added {moved_count} layer(s) to group '{target_name}'")

        return {"FINISHED"}

    def _get_layers_to_move(self, mp, wm):
        """Get list of layer indices to move."""
        layers_to_move = []

        if self.layer_index >= 0 and self.layer_index < len(mp.layers):
            layers_to_move.append(self.layer_index)
        elif hasattr(wm, 'mixar_ui'):
            for i, ui_layer in enumerate(wm.mixar_ui.ui_layers):
                if ui_layer.selected and i < len(mp.layers):
                    layers_to_move.append(i)

        # Fallback to active layer if nothing selected
        if not layers_to_move:
            active_idx = mp.active_layer_index
            if active_idx >= 0 and active_idx < len(mp.layers):
                layers_to_move.append(active_idx)

        return layers_to_move

    def _validate_no_circular_refs(self, mp, target_idx, layers_to_move):
        """Validate that moving layers won't nest groups inside other groups."""
        if target_idx == -1:
            return True

        for layer_idx in layers_to_move:
            layer = mp.layers[layer_idx]
            # GROUP layers cannot be nested inside other groups
            if layer.type == 'GROUP':
                self.report(
                    {'ERROR'},
                    f'Cannot add group "{layer.name}" into another group. '
                    f'Groups must remain at root level.'
                )
                return False
        return True

    def _update_layer_parents(self, mp, layers_to_move, target_idx):
        """Update parent_idx for layers and return count of moved layers."""
        moved_count = 0
        for layer_idx in layers_to_move:
            layer = mp.layers[layer_idx]

            if layer.parent_idx == target_idx:
                continue

            layer.parent_idx = target_idx
            moved_count += 1
            logger.info(f"Moved layer '{layer.name}' to group index {target_idx}")

        return moved_count


class LAYERS_OT_RemoveFromGroup(Operator):
    """Remove layer from its current group (move to root level)"""

    bl_idname = "layers.remove_from_group"
    bl_label = "Remove from Group"
    bl_description = "Remove the layer from its current group and move to root level"
    bl_options = {"REGISTER", "UNDO"}

    layer_index: IntProperty(
        name="Layer Index",
        description="Index of the layer to remove from its group",
        default=-1
    )

    @classmethod
    def poll(cls, context):
        """Check if operator can be executed."""
        return get_active_mpaint_node() is not None

    def execute(self, context):
        """Remove layer from its group."""
        node = get_active_mpaint_node()
        if not node:
            self.report({'ERROR'}, "No active Mixar node found")
            return {'CANCELLED'}

        mp = node.node_tree.mp
        group_tree = node.node_tree

        layer_idx = self.layer_index
        if layer_idx < 0:
            layer_idx = mp.active_layer_index

        if layer_idx < 0 or layer_idx >= len(mp.layers):
            self.report({'ERROR'}, "Invalid layer index")
            return {'CANCELLED'}

        layer = mp.layers[layer_idx]

        if layer.parent_idx == -1:
            self.report({'INFO'}, f"Layer '{layer.name}' is already at root level")
            return {'FINISHED'}

        old_parent_name = mp.layers[layer.parent_idx].name
        layer.parent_idx = -1

        logger.info(f"Removed layer '{layer.name}' from group '{old_parent_name}'")

        reconnect_mp_nodes(group_tree)
        rearrange_mp_nodes(group_tree)

        request_ui_refresh()

        self.report({'INFO'}, f"Removed '{layer.name}' from group '{old_parent_name}'")

        return {"FINISHED"}


# Classes for registration
classes = (
    LAYERS_OT_MoveSelectedToGroup,
    LAYERS_OT_AddLayersToGroup,
    LAYERS_OT_RemoveFromGroup,
)
