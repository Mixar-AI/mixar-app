# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Explicit active-object modifier operations; no multi-selection fan-out."""
import bpy
from bpy.props import EnumProperty, StringProperty
from ...constants import ZEN_MODIFIER_ITEMS
from ...core.zen_object_controls import editable_mesh


class MIXAR_OT_zen_add_modifier(bpy.types.Operator):
    bl_idname = "mixar.zen_add_modifier"
    bl_label = "Add Modifier"
    bl_description = "Add a modifier to the active mesh"
    bl_options = {"REGISTER", "UNDO"}

    object_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    modifier_type: EnumProperty(items=ZEN_MODIFIER_ITEMS)

    @classmethod
    def poll(cls, context):
        return editable_mesh(context) is not None

    def execute(self, context):
        obj = editable_mesh(context, self.object_name)
        if obj is None:
            self.report({"WARNING"}, "Select the original editable mesh again")
            return {"CANCELLED"}
        label = next(item[1] for item in ZEN_MODIFIER_ITEMS if item[0] == self.modifier_type)
        modifier = obj.modifiers.new(name=label, type=self.modifier_type)
        obj.modifiers.active = modifier
        return {"FINISHED"}


class MIXAR_OT_zen_select_modifier(bpy.types.Operator):
    bl_idname = "mixar.zen_select_modifier"
    bl_label = "Edit Modifier"
    bl_description = "Show this modifier's quick controls"
    bl_options = {"INTERNAL"}

    object_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    modifier_name: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return editable_mesh(context) is not None

    def execute(self, context):
        obj = editable_mesh(context, self.object_name)
        modifier = obj.modifiers.get(self.modifier_name) if obj else None
        if modifier is None:
            return {"CANCELLED"}
        obj.modifiers.active = modifier
        if context.area is not None:
            context.area.tag_redraw()
        return {"FINISHED"}


classes = (MIXAR_OT_zen_add_modifier, MIXAR_OT_zen_select_modifier)
