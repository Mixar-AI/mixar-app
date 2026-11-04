# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""New chat while the agent works (the island header's "+").

Starting a new chat cancels the running task, so while one runs the "+"
asks first and offers a parallel scene tab instead (default first row):
the running agent keeps going there while the user starts something new.
"""
from bpy.types import Menu


class MIXIE_CHAT_MT_new_chat_busy(Menu):
    bl_idname = "MIXIE_CHAT_MT_new_chat_busy"
    bl_label = "Mixie is still working"

    def draw(self, context):
        layout = self.layout
        layout.operator_context = 'EXEC_DEFAULT'
        layout.operator("mixie_chat.new_scene_tab", text="Start in a new scene tab", icon='ADD')
        layout.operator("mixie_chat.new_session", text="Stop this task and start over", icon='CANCEL')


classes = (MIXIE_CHAT_MT_new_chat_busy,)
