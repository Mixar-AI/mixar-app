# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cloud dictation toggle; compiled microphone support owns availability."""

from __future__ import annotations

import bpy
from bpy.types import Operator

from ...constants import VOICE_INPUT_SUPPORTED


class MIXIE_CHAT_OT_voice_toggle(Operator):
    """Dictate into the chat composer (click again to stop)"""

    bl_idname = "mixie_chat.voice_toggle"
    bl_label = "Voice"
    bl_description = "Dictate in English; click again to finish, Shift-click to cancel"
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        from ...core import voice
        return (context.scene is not None
                and getattr(context.scene, 'mixie_chat_mode', '') == 'AGENT'
                and voice.available())

    def invoke(self, context, event):
        if event.shift:
            from ...core import voice
            voice.cancel()
            return {'FINISHED'}
        return self.execute(context)

    def execute(self, context):
        from ...core import voice

        outcome = voice.toggle(context)
        if outcome == "unavailable":
            self.report({'WARNING'}, "Voice input is not available on this system")
            return {'CANCELLED'}
        if outcome == "no_scene":
            return {'CANCELLED'}
        return {'FINISHED'}


# Registered only on supported capture platforms: every surface gates
# its Voice control on this operator existing.
classes = (MIXIE_CHAT_OT_voice_toggle,) if VOICE_INPUT_SUPPORTED else ()
