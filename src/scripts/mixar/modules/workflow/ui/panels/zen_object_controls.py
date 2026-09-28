# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Small property cards opened below Zen's adaptive object bar."""
import bpy
from ...core.zen_object_controls import selected_object, selected_modifier
from .zen_modifier_properties import draw_modifier_properties
from .zen_material_properties import draw_material_properties


def _properties(layout):
    layout.use_property_split = True
    layout.use_property_decorate = False
    layout.scale_y = 1.2
    return layout


class MIXAR_PT_zen_object_modifiers(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_label = "Modifier"
    bl_ui_units_x = 22

    @classmethod
    def poll(cls, context):
        obj = selected_object(context)
        return obj is not None and obj.type == "MESH"

    def draw(self, context):
        obj = selected_object(context)
        if obj is None or obj.type != "MESH":
            return
        layout = self.layout
        layout.use_property_decorate = False
        split = layout.split(factor=0.40)
        left = split.column()
        heading = left.row(align=True)
        heading.label(text="Modifiers")
        add = heading.row(align=True)
        add.enabled = obj.is_editable
        add.operator_context = 'INVOKE_REGION_WIN'
        add.operator("wm.call_menu", text="", icon='ADD').name = "MIXAR_MT_zen_modifier_catalog"
        if (obj.modifiers and hasattr(bpy.types, 'MIXAR_UL_zen_modifiers')
                and hasattr(obj, 'mixar_zen_modifier_index')):
            listing = left.column()
            listing.enabled = obj.is_editable
            rows = min(4, len(obj.modifiers))
            listing.template_list('MIXAR_UL_zen_modifiers', '', obj, 'modifiers',
                                  obj, 'mixar_zen_modifier_index', rows=rows, maxrows=rows)
        right = _properties(split.column())
        right.scale_y = 1.0
        right.enabled = obj.is_editable
        modifier = selected_modifier(obj)
        if modifier:
            draw_modifier_properties(right, modifier)
            right.separator(factor=0.3)
            apply = right.row()
            apply.enabled = obj.is_editable and obj.data.is_editable
            apply.operator_context = 'EXEC_REGION_WIN'
            op = apply.operator('object.modifier_apply', text='Apply', icon='CHECKMARK')
            op.modifier = modifier.name
            op.use_selected_objects = False
        else:
            right.label(text="Add a modifier with +.")


class MIXAR_PT_zen_object_textures(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "HEADER"
    bl_label = "Textures"
    bl_ui_units_x = 22

    @classmethod
    def poll(cls, context):
        obj = selected_object(context)
        return obj is not None and obj.type == "MESH"

    def draw(self, context):
        obj = selected_object(context)
        if obj is None or obj.type != "MESH":
            return
        layout = _properties(self.layout)
        layout.scale_y = 1.1
        if len(obj.material_slots) > 1:
            layout.template_list('MATERIAL_UL_matslots', 'zen', obj, 'material_slots',
                                 obj, 'active_material_index', rows=2, maxrows=3)
        header = layout.row(align=True)
        picker = header.row(align=True)
        picker.enabled = obj.is_editable
        picker.prop_search(obj, 'active_material', context.blend_data, 'materials', text='')
        add = header.row(align=True)
        add.enabled = obj.is_editable and obj.data.is_editable
        add.operator('mixar.zen_add_material', text="", icon='ADD').object_name = obj.name
        material = obj.active_material
        if material is None:
            layout.label(text="Add a material to start texturing.", icon='MATERIAL')
            create = layout.row()
            create.enabled = obj.is_editable and obj.data.is_editable
            create.operator('mixar.zen_add_material', text='Create Material',
                            icon='ADD').object_name = obj.name
            return
        draw_material_properties(layout, context, material)



classes = (MIXAR_PT_zen_object_modifiers, MIXAR_PT_zen_object_textures)
