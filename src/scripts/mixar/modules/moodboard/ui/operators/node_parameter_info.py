# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Catalog explanations beside native parameter fields."""

import textwrap

import bpy
from bpy.types import Operator


class MIXIE_OT_moodboard_parameter_info(Operator):
    bl_idname = 'mixie.moodboard_parameter_info'
    bl_label = 'Parameter Info'
    details: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        return properties.details

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=400)

    def draw(self, context):
        layout = self.layout
        if hasattr(layout, 'mixar_surface'):
            layout = layout.mixar_surface(theme='ZEN')
        title, _, body = self.details.partition('\n\n')
        for line in textwrap.wrap(title, width=45):
            layout.label(text=line, icon='INFO')
        layout.separator()
        for paragraph in body.split('\n\n'):
            for source_line in paragraph.splitlines():
                for line in textwrap.wrap(source_line, width=45):
                    layout.label(text=line)
            layout.separator(factor=.4)

    def execute(self, context):
        return {'FINISHED'}


classes = (MIXIE_OT_moodboard_parameter_info,)
