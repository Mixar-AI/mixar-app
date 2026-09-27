# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compact native list for every modifier instance on the selected object."""
import bpy


class MIXAR_UL_zen_modifiers(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        row = layout.row(align=True)
        row.label(text=item.name, icon='MODIFIER')
        remove = row.row(align=True)
        remove.enabled = data.is_editable
        remove.context_pointer_set('object', data)
        remove.context_pointer_set('modifier', item)
        remove.operator_context = 'EXEC_REGION_WIN'
        op = remove.operator('object.modifier_remove', text='', icon='X', emboss=False)
        op.modifier = item.name
        op.use_selected_objects = False


classes = (MIXAR_UL_zen_modifiers,)
