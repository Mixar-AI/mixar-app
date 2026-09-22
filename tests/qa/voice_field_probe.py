# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Offline string-field fixture. Dictation still uses the real coordinator."""
import bpy

active = None
clipboard = None


class QA_OT_voice_fields(bpy.types.Operator):
    bl_idname = 'qa.voice_fields'
    bl_label = 'Dictation Fields'
    bl_options = {'INTERNAL'}

    text: bpy.props.StringProperty(name='Text', default='popup seed')
    short: bpy.props.StringProperty(name='Short', default='keep', maxlen=8)

    def invoke(self, context, event):
        global active
        active = self
        return context.window_manager.invoke_props_dialog(self, width=450)

    def draw(self, context):
        self.layout.prop(self, 'text')
        self.layout.prop(self, 'short')

    def execute(self, context):
        return {'FINISHED'}


def install():
    global clipboard
    clipboard = bpy.context.window_manager.clipboard
    bpy.utils.register_class(QA_OT_voice_fields)


def uninstall():
    bpy.context.window_manager.clipboard = clipboard
    bpy.utils.unregister_class(QA_OT_voice_fields)
