# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Explicit material creation for the floating object controls."""
import bpy
from bpy.props import StringProperty
from ...core.zen_object_controls import editable_mesh


class MIXAR_OT_zen_add_material(bpy.types.Operator):
    bl_idname = "mixar.zen_add_material"
    bl_label = "Add Material"
    bl_description = "Create a material in an empty or new slot, keeping existing materials"
    bl_options = {'REGISTER', 'UNDO'}

    object_name: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        obj = editable_mesh(context)
        return obj is not None and obj.data.is_editable

    def execute(self, context):
        obj = editable_mesh(context, self.object_name)
        if obj is None or not obj.data.is_editable:
            return {'CANCELLED'}
        # Blender 5.2 creates a Principled + Output graph in materials.new.
        material = bpy.data.materials.new(name="Material")
        empty = next((i for i, slot in enumerate(obj.material_slots)
                      if slot.material is None), None)
        if empty is None:
            obj.data.materials.append(material)
            obj.active_material_index = len(obj.material_slots) - 1
        else:
            obj.active_material_index = empty
            obj.active_material = material
        if context.region_popup and context.region_popup.type == 'TEMPORARY':
            context.region_popup.tag_refresh_ui()
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


classes = (MIXAR_OT_zen_add_material,)
