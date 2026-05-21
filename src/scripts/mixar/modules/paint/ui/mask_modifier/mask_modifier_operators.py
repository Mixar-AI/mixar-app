# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

import bpy
from bpy.props import EnumProperty

from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes
from ...core.modifier.mask_modifier import (
    delete_mask_modifier_nodes,
    mask_modifier_type_items,
)
from ...core.subtree.get_subtree import get_mask_tree
from .mask_modifier_operators_helpers import add_new_mask_modifier


class MNewMaskModifier(bpy.types.Operator):
    bl_idname = "wm.m_new_mask_modifier"
    bl_label = "New Mask Modifier"
    bl_description = "New Mask Modifier"
    bl_options = {"REGISTER", "UNDO"}

    type: EnumProperty(
        name="Modifier Type", items=mask_modifier_type_items, default="INVERT"
    )

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed in the current context.

        Args:
            context: Blender context object.

        Returns:
            bool: True if context has both mask and layer attributes, False otherwise.
        """
        return hasattr(context, "mask") and hasattr(context, "layer")

    def execute(self, context):
        """Execute the new mask modifier creation operation.

        Creates a new mask modifier of the specified type, rearranges and reconnects
        layer nodes, and updates the UI to expand the mask content.

        Args:
            context: Blender context object containing mask and layer information.

        Returns:
            set: A set containing 'FINISHED' to indicate successful completion.
        """
        match = re.match(
            r"mp\.layers\[(\d+)\]\.masks\[(\d+)\]", context.mask.path_from_id()
        )
        mask_idx = int(match.group(2))

        add_new_mask_modifier(context.mask, self.type)

        rearrange_layer_nodes(context.layer)
        reconnect_layer_nodes(context.layer)

        # Update UI
        mpui = context.window_manager.mpui
        mpui.layer_ui.masks[mask_idx].expand_content = True
        mpui.need_update = True

        return {"FINISHED"}


class MMoveMaskModifier(bpy.types.Operator):
    bl_idname = "wm.m_move_mask_modifier"
    bl_label = "Move Mask Modifier"
    bl_description = "Move Mask Modifier"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="Direction", items=(("UP", "Up", ""), ("DOWN", "Down", "")), default="UP"
    )

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed in the current context.

        Args:
            context: Blender context object.

        Returns:
            bool: True if context has mask, modifier, and layer attributes, False otherwise.
        """
        return (
            hasattr(context, "mask")
            and hasattr(context, "modifier")
            and hasattr(context, "layer")
        )

    def execute(self, context):
        """Execute the mask modifier move operation.

        Moves a mask modifier up or down in the modifier stack, rearranges nodes,
        and updates the UI. Operation is cancelled if movement is not possible.

        Args:
            context: Blender context object containing layer, mask, and modifier.

        Returns:
            set: A set containing 'FINISHED' if successful, 'CANCELLED' if the
                operation cannot be performed (insufficient modifiers, invalid index,
                or movement out of bounds).
        """
        layer = context.layer
        mask = context.mask
        mod = context.modifier

        num_mods = len(mask.modifiers)
        if num_mods < 2:
            return {"CANCELLED"}

        index = -1
        for i, m in enumerate(mask.modifiers):
            if m == mod:
                index = i
                break
        if index == -1:
            return {"CANCELLED"}

        # Get new index
        if self.direction == "UP" and index > 0:
            new_index = index - 1
        elif self.direction == "DOWN" and index < num_mods - 1:
            new_index = index + 1
        else:
            return {"CANCELLED"}

        # Swap modifier
        mask.modifiers.move(index, new_index)

        # Reconnect modifier nodes
        rearrange_layer_nodes(layer)
        reconnect_layer_nodes(layer)

        # Update UI
        context.window_manager.mpui.need_update = True

        return {"FINISHED"}


class MRemoveMaskModifier(bpy.types.Operator):
    bl_idname = "wm.m_remove_mask_modifier"
    bl_label = "Remove Mask Modifier"
    bl_description = "Remove Mask Modifier"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed in the current context.

        Args:
            context: Blender context object.

        Returns:
            bool: True if context has layer, mask, and modifier attributes, False otherwise.
        """
        return (
            hasattr(context, "layer")
            and hasattr(context, "mask")
            and hasattr(context, "modifier")
        )

    def execute(self, context):
        """Execute the mask modifier removal operation.

        Deletes the modifier's nodes from the tree, removes the modifier from the
        mask's modifier list, rearranges and reconnects layer nodes, and updates the UI.

        Args:
            context: Blender context object containing layer, mask, and modifier.

        Returns:
            set: A set containing 'FINISHED' if successful, 'CANCELLED' if the
                modifier is not found in the mask's modifier list.
        """
        layer = context.layer
        mask = context.mask
        mod = context.modifier
        tree = get_mask_tree(mask)

        index = -1
        for i, m in enumerate(mask.modifiers):
            if m == mod:
                index = i
                break
        if index == -1:
            return {"CANCELLED"}

        delete_mask_modifier_nodes(tree, context.modifier)

        mask.modifiers.remove(index)

        rearrange_layer_nodes(layer)
        reconnect_layer_nodes(layer)

        # Update UI
        context.window_manager.mpui.need_update = True

        return {"FINISHED"}


class MASK_MODIFIERS_MT_add_menu(bpy.types.Menu):
    """Menu for adding mask modifiers"""
    bl_idname = "MASK_MODIFIERS_MT_add_menu"
    bl_label = "Add Mask Modifier"

    def draw(self, context):
        layout = self.layout

        # Invert modifier
        op = layout.operator("wm.m_new_mask_modifier", text="Invert", icon='MODIFIER')
        op.type = 'INVERT'

        # Ramp modifier
        op = layout.operator("wm.m_new_mask_modifier", text="Ramp", icon='COLORSET_08_VEC')
        op.type = 'RAMP'

        # Curve modifier
        op = layout.operator("wm.m_new_mask_modifier", text="Curve", icon='CURVE_DATA')
        op.type = 'CURVE'


classes = (
    MNewMaskModifier,
    MMoveMaskModifier,
    MRemoveMaskModifier,
    MASK_MODIFIERS_MT_add_menu,
)
