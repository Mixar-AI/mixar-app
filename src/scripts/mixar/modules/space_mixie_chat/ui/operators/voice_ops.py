# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cloud dictation toggle; compiled microphone support owns availability."""

import bpy
from bpy.types import Operator

from ...constants import VOICE_INPUT_SUPPORTED


class MIXIE_CHAT_OT_voice_toggle(Operator):
    """Dictate into the chat composer (click again to stop)"""

    bl_idname = "mixie_chat.voice_toggle"
    bl_label = "Voice"
    bl_description = (
        "Focus a text field and hold left Option (Mac) or left Alt (Windows) to dictate; release to insert at the caret. "
        "Click to start or stop; Shift-click cancels"
    )
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


class MIXIE_CHAT_OT_voice_push_to_talk(Operator):
    """Hold Option/Alt to dictate; release finishes."""

    bl_idname = "mixie_chat.voice_push_to_talk"
    bl_label = "Push to Talk"
    bl_description = (
        "Focus a text field and hold left Option (Mac) or left Alt (Windows) to dictate; release to insert at the caret. "
        "Click to start or stop; Shift-click cancels"
    )
    bl_options = {'INTERNAL'}

    field_token: bpy.props.StringProperty(options={'SKIP_SAVE', 'HIDDEN'})
    chat_target: bpy.props.BoolProperty(options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        from ...core import voice
        return (context.scene is not None
                and voice.available())

    def execute(self, context):
        """Composer path. ExecDefault only — a modal from the text handler
        re-enters UI cancel and frees the button while it is still on the stack.
        """
        from ...core import voice
        outcome = voice.push_to_talk_begin(context, self.field_token, self.chat_target)
        if outcome in {'started', 'holding'}:
            return {'FINISHED'}
        return {'CANCELLED'}



class MIXIE_CHAT_OT_voice_push_to_talk_release(Operator):
    """Stop a held Option/Alt session once the key comes up."""

    bl_idname = "mixie_chat.voice_push_to_talk_release"
    bl_label = "Finish Push to Talk"
    bl_description = "Release Option/Alt to finish dictating"
    bl_options = {'INTERNAL'}

    discard: bpy.props.BoolProperty(
        name="Discard",
        description="Drop the dictated words instead of keeping them",
        default=False,
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        from ...core import voice
        return voice.push_to_talk_owned()

    def execute(self, context):
        from ...core import voice
        voice.push_to_talk_end(discard=bool(self.discard))
        return {'FINISHED'}


class MIXIE_CHAT_OT_voice_field_cancel(Operator):
    """Cancel only the native edit lifetime that owns this token."""

    bl_idname = "mixie_chat.voice_field_cancel"
    bl_label = "Cancel Field Dictation"
    bl_options = {'INTERNAL'}

    field_token: bpy.props.StringProperty(options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        from ...core import voice
        voice.cancel_field(context, self.field_token)
        return {'FINISHED'}


# Registered only on supported capture platforms: every surface gates
# its Voice control on this operator existing. Linux has no recogniser,
# so the shortcut is absent there too.
classes = (
    MIXIE_CHAT_OT_voice_toggle,
    MIXIE_CHAT_OT_voice_push_to_talk,
    MIXIE_CHAT_OT_voice_push_to_talk_release,
    MIXIE_CHAT_OT_voice_field_cancel,
) if VOICE_INPUT_SUPPORTED else ()
