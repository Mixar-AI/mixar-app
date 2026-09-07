# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Voice input operator — the one control every surface binds.

``mixie_chat.voice_toggle`` starts a dictation session or stops the running
one; all the work is in ``core/voice.py``. Its poll is the platform
capability (the C++ ``voice_start`` poll), so a surface that draws it only
where ``poll()`` is true never offers a dead microphone.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator

from ...constants import VOICE_INPUT_SUPPORTED


class MIXIE_CHAT_OT_voice_toggle(Operator):
    """Dictate into the chat composer (click again to stop)"""

    bl_idname = "mixie_chat.voice_toggle"
    bl_label = "Voice"
    bl_description = "Dictate into the chat composer; click again to stop"
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if not VOICE_INPUT_SUPPORTED or context.scene is None:
            return False
        start = getattr(getattr(bpy.ops, "mixie_chat", None), "voice_start", None)
        try:
            return start is not None and bool(start.poll())
        except Exception:  # noqa: BLE001
            return False

    def execute(self, context):
        from ...core import voice

        outcome = voice.toggle(context)
        if outcome == "unavailable":
            self.report({'WARNING'}, "Voice input is not available on this system")
            return {'CANCELLED'}
        if outcome == "no_scene":
            return {'CANCELLED'}
        return {'FINISHED'}


# Registered only where the platform has a recogniser: every surface gates
# its Voice control on this operator existing.
classes = (MIXIE_CHAT_OT_voice_toggle,) if VOICE_INPUT_SUPPORTED else ()
