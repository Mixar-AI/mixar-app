# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Temporary native controls for checking independent multiline field state."""
import bpy


class OBJECT_PT_qa_multiline_fields(bpy.types.Panel):
    bl_label = 'QA multiline fields'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'
    bl_order = -1000

    def draw(self, context):
        surface = self.layout.mixar_surface(theme='NATIVE')
        for prop in ('qa_multiline_first', 'qa_multiline_second'):
            row = surface.column()
            row.scale_y = 4
            row.mixar_input(context.scene, prop, text='', multiline=True)


def install():
    for prop in ('qa_multiline_first', 'qa_multiline_second'):
        setattr(bpy.types.Scene, prop, bpy.props.StringProperty(options={'SKIP_SAVE'}))
    bpy.utils.register_class(OBJECT_PT_qa_multiline_fields)


def uninstall():
    bpy.utils.unregister_class(OBJECT_PT_qa_multiline_fields)
    for prop in ('qa_multiline_first', 'qa_multiline_second'):
        delattr(bpy.types.Scene, prop)
