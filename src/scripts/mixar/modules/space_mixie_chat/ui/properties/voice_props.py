# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Voice input properties.

WindowManager state shared between ``core/voice.py`` (the owner), the C++
operator ``mixie_chat.voice_poll`` (``mixie_chat_voice.cc``) and the
surfaces that draw the Voice control (island chip, chat and bubble
headers):

  - mixie_chat_voice_listening: a dictation session is up. Read-only for
    the painters; Python flips it on the recogniser's own LISTENING/STOPPED
    events, never optimistically.
  - mixie_chat_voice_status: one short line for the UI ("Listening…",
    "Microphone access denied").
  - mixie_chat_voice_event_kind / _text: the ONE-event slot the poll
    operator fills (kinds are VOICE_EVENT_* in constants.py). Read right
    after the poll returns FINISHED, never as persistent state.

All SKIP_SAVE: an in-progress dictation is not scene data.
"""

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

_ATTRS = (
    'mixie_chat_voice_listening',
    'mixie_chat_voice_status',
    'mixie_chat_voice_event_kind',
    'mixie_chat_voice_event_text',
)


def register():
    bpy.types.WindowManager.mixie_chat_voice_listening = BoolProperty(
        name="Voice Listening",
        description="A voice dictation session is running",
        default=False,
        options={'SKIP_SAVE'},
    )
    bpy.types.WindowManager.mixie_chat_voice_status = StringProperty(
        name="Voice Status",
        description="Short status line for the voice control",
        default="",
        options={'SKIP_SAVE'},
    )
    bpy.types.WindowManager.mixie_chat_voice_event_kind = IntProperty(
        name="Voice Event Kind",
        description="Kind of the last popped speech recogniser event",
        default=0,
        min=0,
        options={'SKIP_SAVE'},
    )
    bpy.types.WindowManager.mixie_chat_voice_event_text = StringProperty(
        name="Voice Event Text",
        description="Text of the last popped speech recogniser event",
        default="",
        options={'SKIP_SAVE'},
    )


def unregister():
    for attr in _ATTRS:
        if hasattr(bpy.types.WindowManager, attr):
            delattr(bpy.types.WindowManager, attr)
