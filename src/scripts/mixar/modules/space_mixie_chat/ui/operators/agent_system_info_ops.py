# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only system capability API for the independent agent."""
import bpy
from ...core.render_devices import system_info


class MIXIE_CHAT_OT_agent_system_info(bpy.types.Operator):
    bl_idname = 'mixie_chat.agent_system_info'
    bl_label = 'Agent System Information'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        bpy.app.driver_namespace['mixie_agent_system_info'] = system_info(context)
        return {'FINISHED'}


classes = (MIXIE_CHAT_OT_agent_system_info,)
