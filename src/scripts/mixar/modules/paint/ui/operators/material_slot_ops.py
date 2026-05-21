# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Material slot operators for Mixar layers system"""

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator


class MATERIALS_OT_AddMaterialSlot(Operator):
    """Add a new material slot to the active object"""
    bl_idname = "wm.m_add_material_slot"
    bl_label = "Add Material Slot"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object or context.active_object
        if not obj:
            return False
        return obj.type in {'MESH', 'META', 'CURVE', 'CURVES', 'SURFACE', 'FONT'}

    def execute(self, context):
        obj = context.object or context.active_object
        if not obj:
            return {'CANCELLED'}

        # Use context override to ensure operators work in Properties panel
        with context.temp_override(object=obj, active_object=obj):
            bpy.ops.object.material_slot_add()

        return {'FINISHED'}


class MATERIALS_OT_RemoveMaterialSlot(Operator):
    """Remove the active material slot from the object"""
    bl_idname = "wm.m_remove_material_slot"
    bl_label = "Remove Material Slot"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.object or context.active_object
        if not obj:
            return False
        if obj.type not in {'MESH', 'META', 'CURVE', 'CURVES', 'SURFACE', 'FONT'}:
            return False
        return len(obj.material_slots) > 0

    def execute(self, context):
        obj = context.object or context.active_object
        if not obj:
            return {'CANCELLED'}

        # Use context override to ensure operators work in Properties panel
        with context.temp_override(object=obj, active_object=obj):
            bpy.ops.object.material_slot_remove()

        return {'FINISHED'}


class MATERIALS_OT_MoveMaterialSlot(Operator):
    """Move the active material slot up or down"""
    bl_idname = "wm.m_move_material_slot"
    bl_label = "Move Material Slot"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(
        name="Direction",
        items=[
            ('UP', "Up", "Move slot up"),
            ('DOWN', "Down", "Move slot down"),
        ],
        default='UP'
    )

    @classmethod
    def poll(cls, context):
        obj = context.object or context.active_object
        if not obj:
            return False
        if obj.type not in {'MESH', 'META', 'CURVE', 'CURVES', 'SURFACE', 'FONT'}:
            return False
        return len(obj.material_slots) > 1

    def execute(self, context):
        obj = context.object or context.active_object
        if not obj:
            return {'CANCELLED'}

        # Use context override to ensure operators work in Properties panel
        with context.temp_override(object=obj, active_object=obj):
            bpy.ops.object.material_slot_move(direction=self.direction)

        return {'FINISHED'}


# Classes for registration
classes = (
    MATERIALS_OT_AddMaterialSlot,
    MATERIALS_OT_RemoveMaterialSlot,
    MATERIALS_OT_MoveMaterialSlot,
)
