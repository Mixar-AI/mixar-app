# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Path-free async preview API for the independent backend agent."""
import bpy

from ...core import preview_render


class MIXIE_CHAT_OT_agent_preview_render(bpy.types.Operator):
    bl_idname = 'mixie_chat.agent_preview_render'
    bl_label = 'Agent Preview Render'
    bl_options = {'INTERNAL'}

    job_key: bpy.props.StringProperty()
    action: bpy.props.EnumProperty(items=(('START', 'Start', ''), ('POLL', 'Poll', '')), default='START')

    def execute(self, context):
        if self.action == 'START':
            result = preview_render.start(context, self.job_key)
        else:
            result = preview_render.poll(self.job_key)
        # A single response slot; retained job results live in the core module.
        bpy.app.driver_namespace['mixie_agent_preview_response'] = result
        return {'FINISHED'}


classes = (MIXIE_CHAT_OT_agent_preview_render,)
