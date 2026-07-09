# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Moodboard Tool Base Operators

Base operators for managing edit tool state.
"""

from bpy.types import Operator


class MIXIE_OT_moodboard_cancel_tool(Operator):
    """Cancel the current image editing tool"""
    bl_idname = "mixie.moodboard_cancel_tool"
    bl_label = "Cancel Tool"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not hasattr(context.scene, 'mixie_edit_tool_state'):
            return False
        return context.scene.mixie_edit_tool_state.active_tool != 'NONE'

    def execute(self, context):
        state = context.scene.mixie_edit_tool_state
        state.active_tool = 'NONE'
        state.is_drawing = False
        state.target_image_index = -1
        state.lasso_points.clear()
        context.area.tag_redraw()
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_cancel_tool,
)
