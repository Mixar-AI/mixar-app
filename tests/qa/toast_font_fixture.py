# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Native font references and no-op action counters for isolated notification QA."""
import bpy
from native_label_fixture import WM_OT_qa_native_label

calls = {'review': 0, 'continue': 0}
labels = ['Queue', 'Send', 'Generate']


class VIEW3D_PT_qa_toast_fonts(bpy.types.Panel):
    bl_label = 'Notification font reference'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Toast QA'

    def draw(self, context):
        for text in labels:
            self.layout.operator('wm.qa_native_label', text=text)


class WM_OT_qa_toast_review(bpy.types.Operator):
    bl_idname = 'wm.qa_toast_review'
    bl_label = 'Review notification fixture'

    def execute(self, context):
        calls['review'] += 1
        return {'FINISHED'}


class WM_OT_qa_toast_continue(bpy.types.Operator):
    bl_idname = 'wm.qa_toast_continue'
    bl_label = 'Continue notification fixture'

    def execute(self, context):
        calls['continue'] += 1
        return {'FINISHED'}


CLASSES = (WM_OT_qa_native_label, VIEW3D_PT_qa_toast_fonts,
           WM_OT_qa_toast_review, WM_OT_qa_toast_continue)


def install():
    calls.update(review=0, **{'continue': 0})
    labels[:] = ['Queue', 'Send', 'Generate']
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def uninstall():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
