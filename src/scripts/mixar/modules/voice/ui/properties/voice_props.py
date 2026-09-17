# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""WindowManager mirror of the voice session, for the surfaces that draw it.

RNA is the only channel the C++ mic buttons have — they cannot read a Python
module's state — so the session projects itself onto these properties and the
chat footer, the node tile and the N-panel drawer all read the same three
values. Nothing writes them except `core/session.py`.

WindowManager, never Scene: a half-finished recording belongs to this running
app, not to a `.blend` someone else will open.

The three capture readings a meter needs — `mixar_audio_recording`,
`mixar_audio_level`, `mixar_audio_duration` — are NOT here. They are C++ RNA
(`makesrna/intern/rna_wm_mixar.cc`) reading the capture engine's atomics
directly, because a draw pass must be able to sample the live level without a
Python round trip.
"""

import bpy
from bpy.props import EnumProperty, StringProperty

from ...constants import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_RECORDING,
    STATE_TRANSCRIBING,
)

_STATE_ITEMS = [
    (STATE_IDLE, "Idle", "Not recording"),
    (STATE_RECORDING, "Recording", "Capturing from the microphone"),
    (STATE_TRANSCRIBING, "Transcribing", "Waiting for the transcript"),
    (STATE_ERROR, "Error", "The last recording did not produce text"),
]


def register():
    bpy.types.WindowManager.mixar_voice_state = EnumProperty(
        name="Voice State",
        items=_STATE_ITEMS,
        default=STATE_IDLE,
        description="What voice dictation is doing right now",
        options={'SKIP_SAVE'},
    )
    bpy.types.WindowManager.mixar_voice_target = StringProperty(
        name="Voice Target",
        default="",
        description=(
            "Which text field the current recording will be written to "
            "(captured when recording starts)"
        ),
        options={'SKIP_SAVE'},
    )
    bpy.types.WindowManager.mixar_voice_message = StringProperty(
        name="Voice Message",
        default="",
        description="Transient notice from the last recording",
        options={'SKIP_SAVE'},
    )


def unregister():
    for name in (
        "mixar_voice_state",
        "mixar_voice_target",
        "mixar_voice_message",
    ):
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
