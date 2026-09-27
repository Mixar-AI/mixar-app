# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Preview and toggle the shared task-completion sound preference."""

from __future__ import annotations

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from ...core.completion_sound import (
    CHIME,
    OFF,
    get_completion_sound,
    get_notifications_muted,
    play_sound,
    set_completion_sound,
)
from ...core import sound_feedback


class MIXIE_CHAT_OT_preview_completion_sound(Operator):
    """Play the completion sound so it can be heard before it is chosen."""

    bl_idname = "mixie_chat.preview_completion_sound"
    bl_label = "Preview Completion Sound"
    bl_options = {'INTERNAL'}

    # Empty = whatever is currently selected in the picker.
    sound: StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        play_sound(self.sound or get_completion_sound())
        return {'FINISHED'}


class MIXIE_CHAT_OT_toggle_completion_sound(Operator):
    """Toggle automatic sounds without discarding the selected clip."""

    bl_idname = "mixie_chat.toggle_completion_sound"
    bl_label = "Task Completion Sounds"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return hasattr(context.window_manager, "mixar_notifications_muted")

    @classmethod
    def description(cls, context, properties):
        if _sound_off():
            return "Task completion sounds: Off — click to enable"
        return "Task completion sounds: On — click to mute"

    def execute(self, context):
        # Read the persisted config, not the enum mirror: its index lookup can
        # miss a catalog clip when the items cache predates a catalog refresh.
        wm = context.window_manager
        if get_completion_sound() == OFF:
            set_completion_sound(CHIME)
            wm.mixar_notifications_muted = False
        else:
            wm.mixar_notifications_muted = not get_notifications_muted()
        # The mute property's update already cancelled feedback when silencing.
        if not get_notifications_muted():
            sound_feedback.show(reduce_motion=context.preferences.view.use_reduce_motion)
        return {'FINISHED'}


def _sound_off() -> bool:
    return get_notifications_muted() or get_completion_sound() == OFF


classes = (
    MIXIE_CHAT_OT_toggle_completion_sound,
    MIXIE_CHAT_OT_preview_completion_sound,
)
