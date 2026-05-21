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
    shift_modifier_fcurves_up,
    swap_modifier_fcurves,
)
from ...core.io.arrangements.layer_arrangements import rearrange_layer_nodes, rearrange_mp_nodes
from ...core.io.connections.layer_connections import reconnect_layer_nodes, reconnect_mp_nodes
from ...core.modifier.modifier import (
    add_new_modifier,
    check_modifiers_trees,
    modifier_type_items,
)
from ...core.modifier.modifier_commons import delete_modifier_nodes
from ...core.node.node_utils import get_active_mpaint_node
from ...core.subtree.get_subtree import get_mod_tree
from ...utils.common import get_addon_title
from .modifier_popup import CHANNEL_OT_ModifiersPopup


class MNewMPaintModifier(bpy.types.Operator):
    bl_idname = "wm.m_new_mpaint_modifier"
    bl_label = "New " + get_addon_title() + " Modifier"
    bl_description = "New " + get_addon_title() + " Modifier"
    bl_options = {"REGISTER", "UNDO"}

    type: EnumProperty(
        name="Modifier Type", items=modifier_type_items, default="INVERT"
    )

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed in the current context.

        Args:
            cls: The class.
            context: Blender context object.

        Returns:
            bool: True if an active mpaint node exists and context has a parent attribute.
        """
        return get_active_mpaint_node() and hasattr(context, "parent")

    def execute(self, context):
        """Execute the operator to create a new modifier.

        Args:
            self: The operator instance.
            context: Blender context object.

        Returns:
            set: {'FINISHED'} on success.
        """
        node = get_active_mpaint_node()
        group_tree = node.node_tree
        mp = group_tree.mp

        m1 = re.match(r"^mp\.layers\[(\d+)\]$", context.parent.path_from_id())
        m2 = re.match(
            r"^mp\.layers\[(\d+)\]\.channels\[(\d+)\]$", context.parent.path_from_id()
        )
        m3 = re.match(r"^mp\.channels\[(\d+)\]$", context.parent.path_from_id())

        if m1:
            layer = mp.layers[int(m1.group(1))]
        elif m2:
            layer = mp.layers[int(m2.group(1))]
        else:
            layer = None

        mod = add_new_modifier(context.parent, self.type)

        # if self.type == 'RGB_TO_INTENSITY' and root_ch.type == 'RGB':
        #    mod.rgb2i_col = (1,0,1,1)

        # If RGB to intensity is added, bump base is better be 0.0
        if layer and self.type == "RGB_TO_INTENSITY":
            for i, ch in enumerate(mp.channels):
                c = context.layer.channels[i]
                if ch.type == "NORMAL":
                    c.bump_base_value = 0.0

        # Expand channel content to see added modifier (with error handling for backward compatibility)
        try:
            if m1:
                context.layer_ui.expand_content = True
            elif m2:
                ch_idx = int(m2.group(2))
                if hasattr(context.layer_ui, 'channels') and ch_idx < len(context.layer_ui.channels):
                    context.layer_ui.channels[ch_idx].expand_content = True
            elif m3:
                context.channel_ui.expand_content = True
        except (IndexError, AttributeError) as e:
            logger.warning("Could not expand UI for modifier: %s", e)

        # Reconnect and rearrange nodes
        if layer:
            reconnect_layer_nodes(layer)
            rearrange_layer_nodes(layer)
        else:
            reconnect_mp_nodes(group_tree)
            rearrange_mp_nodes(group_tree)

        # Update UI
        context.window_manager.mpui.need_update = True

        return {"FINISHED"}


class MMoveMPaintModifier(bpy.types.Operator):
    bl_idname = "wm.m_move_mpaint_modifier"
    bl_label = "Move " + get_addon_title() + " Modifier"
    bl_description = "Move " + get_addon_title() + " Modifier"
    bl_options = {"REGISTER", "UNDO"}

    direction: EnumProperty(
        name="Direction", items=(("UP", "Up", ""), ("DOWN", "Down", "")), default="UP"
    )

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed in the current context.

        Args:
            cls: The class.
            context: Blender context object.

        Returns:
            bool: True if active mpaint node exists and context has parent and modifier attributes.
        """
        return (
            get_active_mpaint_node()
            and hasattr(context, "parent")
            and hasattr(context, "modifier")
        )

    def execute(self, context):
        """Execute the operator to move a modifier up or down in the stack.

        Args:
            self: The operator instance.
            context: Blender context object.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} if operation cannot be performed.
        """
        node = get_active_mpaint_node()
        group_tree = node.node_tree
        mp = group_tree.mp

        parent = context.parent

        num_mods = len(parent.modifiers)
        if num_mods < 2:
            return {"CANCELLED"}

        mod = context.modifier
        index = -1
        for i, m in enumerate(parent.modifiers):
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

        layer = context.layer if hasattr(context, "layer") else None

        # Swap modifier
        parent.modifiers.move(index, new_index)
        swap_modifier_fcurves(parent, index, new_index)

        # Reconnect and rearrange nodes
        if layer:
            reconnect_layer_nodes(layer)
            rearrange_layer_nodes(layer)
        else:
            reconnect_mp_nodes(group_tree)
            rearrange_mp_nodes(group_tree)

        # Update UI
        context.window_manager.mpui.need_update = True

        return {"FINISHED"}


class MRemoveMPaintModifier(bpy.types.Operator):
    bl_idname = "wm.m_remove_mpaint_modifier"
    bl_label = "Remove " + get_addon_title() + " Modifier"
    bl_description = "Remove " + get_addon_title() + " Modifier"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if the operator can be executed in the current context.

        Args:
            cls: The class.
            context: Blender context object.

        Returns:
            bool: True if context has both parent and modifier attributes.
        """
        return hasattr(context, "parent") and hasattr(context, "modifier")

    def execute(self, context):
        """Execute the operator to remove a modifier.

        Args:
            self: The operator instance.
            context: Blender context object.

        Returns:
            set: {'FINISHED'} on success, {'CANCELLED'} if modifier cannot be removed.
        """
        group_tree = context.parent.id_data
        mp = group_tree.mp

        parent = context.parent
        mod = context.modifier

        index = -1
        for i, m in enumerate(parent.modifiers):
            if m == mod:
                index = i
                break
        if index == -1:
            return {"CANCELLED"}

        if len(parent.modifiers) < 1:
            return {"CANCELLED"}

        layer = context.layer if hasattr(context, "layer") else None

        tree = get_mod_tree(parent)

        # Remove modifier fcurves first
        remove_entity_fcurves(mod)
        shift_modifier_fcurves_up(parent, index)

        # Delete the nodes
        delete_modifier_nodes(tree, mod)

        # Delete the modifier
        parent.modifiers.remove(index)

        # Delete modifier pipeline if no modifier left
        # if len(parent.modifiers) == 0:
        #    unset_modifier_pipeline_nodes(tree, parent)

        check_modifiers_trees(parent)

        if layer:
            reconnect_layer_nodes(layer)
        else:
            reconnect_mp_nodes(group_tree)

        # Rearrange nodes
        if layer:
            rearrange_layer_nodes(layer)
        else:
            rearrange_mp_nodes(group_tree)

        # Update UI
        context.window_manager.mpui.need_update = True

        return {"FINISHED"}


class CHANNEL_MODIFIERS_MT_add_menu(bpy.types.Menu):
    """Menu for adding channel modifiers"""
    bl_idname = "CHANNEL_MODIFIERS_MT_add_menu"
    bl_label = "Add Channel Modifier"

    def draw(self, context):
        layout = self.layout

        # Modifier types from Mixar Paint with full parity
        modifiers = [
            ('INVERT', 'Invert', 'MODIFIER'),
            ('RGB_TO_INTENSITY', 'RGB to Intensity', 'IMAGE_RGB_ALPHA'),
            ('INTENSITY_TO_RGB', 'Intensity to RGB', 'IMAGE_RGB'),
            ('COLOR_RAMP', 'Color Ramp', 'COLORSET_08_VEC'),
            ('RGB_CURVE', 'RGB Curve', 'CURVE_DATA'),
            ('HUE_SATURATION', 'Hue Saturation', 'COLOR'),
            ('BRIGHT_CONTRAST', 'Brightness Contrast', 'LIGHT_SUN'),
            ('MATH', 'Math', 'PLUS'),
        ]

        for mod_type, label, icon in modifiers:
            op = layout.operator("wm.m_new_mpaint_modifier", text=label, icon=icon)
            op.type = mod_type


class LAYER_MODIFIERS_MT_add_menu(bpy.types.Menu):
    """Menu for adding layer modifiers"""
    bl_idname = "LAYER_MODIFIERS_MT_add_menu"
    bl_label = "Add Layer Modifier"

    def draw(self, context):
        layout = self.layout

        # Same modifier types for layers
        modifiers = [
            ('INVERT', 'Invert', 'MODIFIER'),
            ('RGB_TO_INTENSITY', 'RGB to Intensity', 'IMAGE_RGB_ALPHA'),
            ('INTENSITY_TO_RGB', 'Intensity to RGB', 'IMAGE_RGB'),
            ('COLOR_RAMP', 'Color Ramp', 'COLORSET_08_VEC'),
            ('RGB_CURVE', 'RGB Curve', 'CURVE_DATA'),
            ('HUE_SATURATION', 'Hue Saturation', 'COLOR'),
            ('BRIGHT_CONTRAST', 'Brightness Contrast', 'LIGHT_SUN'),
            ('MATH', 'Math', 'PLUS'),
        ]

        for mod_type, label, icon in modifiers:
            op = layout.operator("wm.m_new_mpaint_modifier", text=label, icon=icon)
            op.type = mod_type


# Only register classes defined in this file
# CHANNEL_OT_ModifiersPopup is registered by modifier_popup.py to avoid double registration
classes = (
    MNewMPaintModifier,
    MMoveMPaintModifier,
    MRemoveMPaintModifier,
    CHANNEL_MODIFIERS_MT_add_menu,
    LAYER_MODIFIERS_MT_add_menu,
)
