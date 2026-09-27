# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Preview and toggle the shared task-completion sound preference."""

from __future__ import annotations

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from ...core.completion_sound import CHIME, OFF, play_sound
from ...core import sound_feedback


class MIXIE_CHAT_OT_preview_completion_sound(Operator):
    """Play the completion sound so it can be heard before it is chosen."""

    bl_idname = "mixie_chat.preview_completion_sound"
    bl_label = "Preview Completion Sound"
    bl_options = {'INTERNAL'}

    # Empty = whatever is currently selected in the picker.
    sound: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        value = self.sound or getattr(
            context.window_manager, "mixar_completion_sound", ""
        )
        play_sound(value)
        return {'FINISHED'}


class MIXIE_CHAT_OT_toggle_completion_sound(Operator):
    """Toggle automatic sounds without discarding the selected clip."""

    bl_idname = "mixie_chat.toggle_completion_sound"
    bl_label = "Task Completion Sounds"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        wm = context.window_manager
        return (hasattr(wm, "mixar_notifications_muted") and
                hasattr(wm, "mixar_completion_sound"))

    @classmethod
    def description(cls, context, properties):
        wm = context.window_manager
        off = wm.mixar_notifications_muted or wm.mixar_completion_sound == OFF
        if off:
            return "Task completion sounds: Off — click to enable"
        return "Task completion sounds: On — click to mute"

    def execute(self, context):
        wm = context.window_manager
        if wm.mixar_completion_sound == OFF:
            wm.mixar_completion_sound = CHIME
            wm.mixar_notifications_muted = False
        else:
            wm.mixar_notifications_muted = not wm.mixar_notifications_muted
        if wm.mixar_notifications_muted:
            sound_feedback.cancel()
        else:
            sound_feedback.show()
        return {'FINISHED'}


classes = (
    MIXIE_CHAT_OT_toggle_completion_sound,
    MIXIE_CHAT_OT_preview_completion_sound,
)
