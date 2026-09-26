# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Notifications section in Edit > Preferences > System.

Registered from Python into the native Preferences editor, next to Privacy,
which keeps the upstream merge surface untouched.
"""

from bpy.types import Panel


class MIXAR_PT_notifications_preferences(Panel):
    """Agent notification settings (currently the task-completion sound)."""

    bl_label = "Notifications"
    bl_idname = "MIXAR_PT_notifications_preferences"
    bl_space_type = 'PREFERENCES'
    bl_region_type = 'WINDOW'
    bl_context = "system"

    @classmethod
    def poll(cls, context):
        # The property only exists in interactive, non-headless sessions.
        return hasattr(context.window_manager, "mixar_completion_sound")

    def draw(self, context):
        wm = context.window_manager
        muted = wm.mixar_notifications_muted
        layout = self.layout
        layout.prop(
            wm, "mixar_notifications_muted", text="Mute Notifications",
            icon='MUTE_IPO_ON' if muted else 'MUTE_IPO_OFF',
        )
        col = layout.column()
        col.enabled = not muted
        col.prop(wm, "mixar_completion_sound", text="Task Completion Sound")
        row = col.row()
        row.enabled = wm.mixar_completion_sound != 'OFF'
        row.operator(
            "mixie_chat.preview_completion_sound", text="Preview", icon='PLAY',
        )
        sub = col.column()
        sub.active = False
        sub.label(text="Sound played when an agent run finishes.")


classes = (
    MIXAR_PT_notifications_preferences,
)
