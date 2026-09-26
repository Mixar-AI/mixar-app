# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Preview the task-completion sound from the Preferences picker."""

from __future__ import annotations

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from ...core.completion_sound import play_sound


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


classes = (
    MIXIE_CHAT_OT_preview_completion_sound,
)
