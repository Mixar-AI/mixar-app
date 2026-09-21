# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Catalog explanations beside native parameter fields."""

import textwrap

import bpy
from bpy.types import Operator


def parameter_help(parameter):
    parts = [parameter.label or parameter.name]
    if getattr(parameter, 'description', ''):
        parts.append(parameter.description)
    if parameter.parameter_type in {'INTEGER', 'FLOAT'}:
        if -1e17 < parameter.minimum <= parameter.maximum < 1e17:
            parts.append(f"Range: {parameter.minimum:g} to {parameter.maximum:g}")
    if getattr(parameter, 'required', False):
        parts.append("Required")
    return '\n\n'.join(parts)


class MIXIE_OT_moodboard_parameter_info(Operator):
    bl_idname = 'mixie.moodboard_parameter_info'
    bl_label = 'Parameter Info'
    details: bpy.props.StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        return properties.details

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=320)

    def draw(self, context):
        for paragraph in self.details.split('\n\n'):
            for line in textwrap.wrap(paragraph, width=45):
                self.layout.label(text=line)
            self.layout.separator(factor=.4)

    def execute(self, context):
        return {'FINISHED'}


classes = (MIXIE_OT_moodboard_parameter_info,)
