# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Space Switch Operators

Operators for switching between different space types.
"""

import bpy
from bpy.types import Operator
from bpy.props import StringProperty


class MIXAR_OT_switch_space(Operator):
    """Switch the current area to a different space type"""
    bl_idname = "mixar.switch_space"
    bl_label = "Switch Space"
    bl_description = "Switch to a different space type"
    bl_options = {'REGISTER'}

    target_space: StringProperty(
        name="Target Space",
        description="The space type to switch to",
        default="PROPERTIES"
    )

    def execute(self, context):
        if context.area is None:
            self.report({'WARNING'}, "No active area")
            return {'CANCELLED'}

        context.area.ui_type = self.target_space
        return {'FINISHED'}


classes = (
    MIXAR_OT_switch_space,
)
