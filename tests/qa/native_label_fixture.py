# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Ordinary Blender buttons used as the font-size reference outside the island."""
import bpy


class WM_OT_qa_native_label(bpy.types.Operator):
    bl_idname = 'wm.qa_native_label'
    bl_label = 'Native label comparison'

    def execute(self, context):
        return {'FINISHED'}


class OBJECT_PT_qa_native_labels(bpy.types.Panel):
    bl_label = 'Native label comparison'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'
    bl_order = -1000

    def draw(self, context):
        # Deliberately use ordinary UILayout buttons, with no Mixar styling.
        for label in ('Queue', 'Send', 'Generate'):
            self.layout.operator('wm.qa_native_label', text=label)


def install():
    bpy.utils.register_class(WM_OT_qa_native_label)
    bpy.utils.register_class(OBJECT_PT_qa_native_labels)


def uninstall():
    bpy.utils.unregister_class(OBJECT_PT_qa_native_labels)
    bpy.utils.unregister_class(WM_OT_qa_native_label)
