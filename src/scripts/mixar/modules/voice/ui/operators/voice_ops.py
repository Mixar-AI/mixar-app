# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The mic button's operators.

`mixar.voice_record_toggle` is the ONE entry point every surface uses: the C++
chat footer, the C++ moodboard node tile and the Python N-panel drawer all
invoke it with their own `target`. Behaviour has one owner (the session);
the drawing surfaces only say where the words should land — the same split the
Director keeps between its native surface and its Python operators.

`target` is `PROP_SKIP_SAVE` for the reason every REGISTER operator's
properties are: without it, `WM_operator_last_properties_init` would refill a
press that set nothing with the PREVIOUS press's target, and a mic clicked in
the chat would start dictating into the node someone recorded to an hour ago.
"""

import bpy
from bpy.props import StringProperty

from mixar.config.logging_config import get_logger

from ...constants import STATE_IDLE, STATE_RECORDING, STATE_TRANSCRIBING, TARGET_CHAT
from ...core import glyph_icons
from ...core.session import get_session

logger = get_logger(__name__)


class MIXAR_OT_voice_record_toggle(bpy.types.Operator):
    """Start or stop dictating into this field"""

    bl_idname = "mixar.voice_record_toggle"
    bl_label = "Dictate"
    bl_description = "Record your voice and insert the transcript into this field"
    bl_options = {'REGISTER', 'INTERNAL'}

    target: StringProperty(
        name="Target",
        description="Which text field the transcript is written to",
        default=TARGET_CHAT,
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        session = get_session()
        ok, message = session.toggle(context, self.target)
        if not ok and message:
            # A refusal the session can explain ("still transcribing"). A
            # refusal it cannot is one the C++ capture layer already reported
            # through `reports` with a better message than we could invent.
            self.report({'INFO'}, message)
        return {'FINISHED'}


class MIXAR_OT_voice_cancel(bpy.types.Operator):
    """Discard the current recording"""

    bl_idname = "mixar.voice_cancel"
    bl_label = "Cancel Dictation"
    bl_description = "Stop recording and throw the audio away"
    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        state = getattr(context.window_manager, "mixar_voice_state", STATE_IDLE)
        return state in {STATE_RECORDING, STATE_TRANSCRIBING}

    def execute(self, context):
        get_session().cancel()
        return {'FINISHED'}


classes = (
    MIXAR_OT_voice_record_toggle,
    MIXAR_OT_voice_cancel,
)


def unregister():
    # Registration deliberately uses the discovery fallback (the `classes`
    # tuple above); only teardown is hand-written, because `unregister()`
    # takes precedence over that fallback and the classes still have to go.
    #
    # The capture device outlives Python's module state, so a reload while
    # recording would leave the microphone open with nothing able to stop it.
    try:
        get_session().shutdown()
    except Exception:
        logger.exception("[Voice] shutdown during unregister failed")
    # Preview collections live outside Python's module state too, so the mic's
    # rasterized glyph frames are released for the same reason as the device.
    try:
        glyph_icons.unregister()
    except Exception:
        logger.exception("[Voice] releasing glyph icons during unregister failed")
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
