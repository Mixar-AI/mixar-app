# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import re

import bpy

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)
from bpy.props import EnumProperty

from ...core.element.update_fcurves import (
    remove_entity_fcurves,
    shift_normal_modifier_fcurves_up,
    swap_normal_modifier_fcurves,
)
from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes
from ...core.modifier.modifier_commons import delete_modifier_nodes
from ...core.node.node_utils import get_active_mpaint_node
from ...core.subtree.get_subtree import get_tree
from ...utils.common import get_addon_title
from .normal_map_modifier_operators_helper import add_new_normalmap_modifier
from .normal_map_modifier_utils import normalmap_modifier_type_items


class MNewNormalmapModifier(bpy.types.Operator):
    bl_idname = "wm.m_new_normalmap_modifier"
    bl_label = "New Normal Map Modifier"
    bl_description = "New Normal Map Modifier"
    bl_options = {"REGISTER", "UNDO"}

    type: EnumProperty(
        name="Modifier Type", items=normalmap_modifier_type_items, default="INVERT"
    )

    @classmethod
    def poll(cls, context):
        """Checks if the operator can be executed in the current context.

        Args:
            cls: The operator class.
            context: Blender context object.

        Returns:
            bool: True if context has a parent attribute, False otherwise.
        """
        return hasattr(context, "parent")

    def execute(self, context):
        """Creates a new normal map modifier and adds it to a channel.

        Parses the parent context path to identify the layer and channel, creates
        a new modifier of the specified type, rearranges nodes, and updates the UI.

        Args:
            self: The operator instance.
            context: Blender context object with parent attribute.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on error.
        """

        mp = context.parent.id_data.mp
        match = re.match(
            r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", context.parent.path_from_id()
        )
        if not match:
            self.report({"ERROR"}, "Wrong context!")
            return {"CANCELLED"}
        layer = mp.layers[int(match.group(1))]
        ch_idx = int(match.group(2))
        ch = layer.channels[ch_idx]
        root_ch = mp.channels[ch_idx]

        add_new_normalmap_modifier(ch, layer, self.type)

        rearrange_layer_nodes(layer)
        reconnect_layer_nodes(layer)

        # Update UI (with error handling for backward compatibility)
        mpui = context.window_manager.mpui
        try:
            if hasattr(mpui.layer_ui, 'channels') and ch_idx < len(mpui.layer_ui.channels):
                mpui.layer_ui.channels[ch_idx].expand_content = True
        except (IndexError, AttributeError) as e:
            logger.warning("Could not expand channel UI for normal map modifier: %s", e)
        mpui.need_update = True

        return {"FINISHED"}


class MMoveNormalMapModifier(bpy.types.Operator):
    bl_idname = "wm.m_move_normalmap_modifier"
    bl_label = "Move " + get_addon_title() + " Modifier"
    bl_description = "Move " + get_addon_title() + " Modifier"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="Direction", items=(("UP", "Up", ""), ("DOWN", "Down", "")), default="UP"
    )

    @classmethod
    def poll(cls, context):
        """Checks if the operator can be executed in the current context.

        Args:
            cls: The operator class.
            context: Blender context object.

        Returns:
            bool: True if there's an active mpaint node and context has parent
                and modifier attributes, False otherwise.
        """
        return (
            get_active_mpaint_node()
            and hasattr(context, "parent")
            and hasattr(context, "modifier")
        )

    def execute(self, context):
        """Moves a normal map modifier up or down in the modifier stack.

        Swaps the modifier with its neighbor in the specified direction, updates
        F-curves, rearranges nodes, and refreshes the UI.

        Args:
            self: The operator instance.
            context: Blender context object with parent and modifier attributes.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} if unable to move.
        """
        node = get_active_mpaint_node()
        group_tree = node.node_tree
        mp = group_tree.mp

        parent = context.parent

        match = re.match(
            r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", parent.path_from_id()
        )
        if not match:
            self.report({"ERROR"}, "Wrong context!")
            return {"CANCELLED"}
        layer = mp.layers[int(match.group(1))]

        num_mods = len(parent.modifiers_1)
        if num_mods < 2:
            return {"CANCELLED"}

        mod = context.modifier
        index = -1
        for i, m in enumerate(parent.modifiers_1):
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
        parent.modifiers_1.move(index, new_index)
        swap_normal_modifier_fcurves(parent, index, new_index)

        # Rearrange nodes
        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        # Update UI
        context.window_manager.mpui.need_update = True

        return {"FINISHED"}


class MRemoveNormalMapModifier(bpy.types.Operator):
    bl_idname = "wm.m_remove_normalmap_modifier"
    bl_label = "Remove " + get_addon_title() + " Modifier"
    bl_description = "Remove " + get_addon_title() + " Modifier"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Checks if the operator can be executed in the current context.

        Args:
            cls: The operator class.
            context: Blender context object.

        Returns:
            bool: True if context has parent and modifier attributes, False otherwise.
        """
        return hasattr(context, "parent") and hasattr(context, "modifier")

    def execute(self, context):
        """Removes a normal map modifier from a channel.

        Removes F-curves, deletes associated nodes, removes the modifier from the
        modifiers list, reconnects layer nodes, and updates the UI.

        Args:
            self: The operator instance.
            context: Blender context object with parent and modifier attributes.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} on error.
        """
        group_tree = context.parent.id_data
        mp = group_tree.mp

        parent = context.parent
        mod = context.modifier

        match = re.match(
            r"mp\.layers\[(\d+)\]\.channels\[(\d+)\]", parent.path_from_id()
        )
        if not match:
            self.report({"ERROR"}, "Wrong context!")
            return {"CANCELLED"}
        layer = mp.layers[int(match.group(1))]
        tree = get_tree(layer)

        index = -1
        for i, m in enumerate(parent.modifiers_1):
            if m == mod:
                index = i
                break
        if index == -1:
            return {"CANCELLED"}

        if len(parent.modifiers_1) < 1:
            return {"CANCELLED"}

        # Remove modifier fcurves first
        remove_entity_fcurves(parent)
        shift_normal_modifier_fcurves_up(parent, index)

        # Delete the nodes
        delete_modifier_nodes(tree, mod)

        # Delete the modifier
        parent.modifiers_1.remove(index)

        reconnect_layer_nodes(layer)
        rearrange_layer_nodes(layer)

        # Update UI
        context.window_manager.mpui.need_update = True

        return {"FINISHED"}


classes = (
    MNewNormalmapModifier,
    MMoveNormalMapModifier,
    MRemoveNormalMapModifier,
)
