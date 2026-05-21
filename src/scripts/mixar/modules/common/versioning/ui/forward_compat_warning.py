# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Forward compatibility warning popup operator."""

import bpy
from bpy.props import StringProperty


class MIXAR_OT_forward_compat_warning(bpy.types.Operator):
    """Warn user that the file was saved by a newer Mixar version"""

    bl_idname = "mixar.forward_compat_warning"
    bl_label = "Newer File Version"
    bl_options = {'INTERNAL'}

    file_version: StringProperty(name="File Version", default="")

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        layout.label(
            text=f"This file was saved by Mixar version {self.file_version}.",
            icon='ERROR',
        )
        layout.label(text="Some data may be missing or incorrect.")
        layout.label(text="Save will overwrite with the current version.")


classes = [MIXAR_OT_forward_compat_warning]
