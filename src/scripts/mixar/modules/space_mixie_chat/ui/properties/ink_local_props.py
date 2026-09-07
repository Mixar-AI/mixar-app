# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scribble on-device recognition result slot.

Four WindowManager properties the C++ operator ``mixie_chat.ink_local_poll``
fills with ONE finished on-device recognition result at a time (see
``mixie_chat_ink_local.cc`` and ``core/scribble_local.py``). Recognition
runs on a system queue; a property slot filled from a main-thread operator
is how its result crosses into Blender without a callback ever running off
the main thread. Read immediately after the poll operator returns FINISHED,
never as a persistent state.

SKIP_SAVE: a result in transit is not scene data.
"""

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty

_ATTRS = (
    'mixie_chat_ink_local_job',
    'mixie_chat_ink_local_text',
    'mixie_chat_ink_local_confidence',
    'mixie_chat_ink_local_ok',
)


def register():
    bpy.types.WindowManager.mixie_chat_ink_local_job = IntProperty(
        name="Local Recognition Job",
        description="Batch id of the last popped on-device recognition result",
        default=0,
        min=0,
        options={'SKIP_SAVE'},
    )
    bpy.types.WindowManager.mixie_chat_ink_local_text = StringProperty(
        name="Local Recognition Text",
        description="Text of the last popped on-device recognition result",
        default="",
        options={'SKIP_SAVE'},
    )
    bpy.types.WindowManager.mixie_chat_ink_local_confidence = FloatProperty(
        name="Local Recognition Confidence",
        description="Recogniser confidence (0-1) of the last popped result",
        default=0.0,
        min=0.0,
        max=1.0,
        options={'SKIP_SAVE'},
    )
    bpy.types.WindowManager.mixie_chat_ink_local_ok = BoolProperty(
        name="Local Recognition Succeeded",
        description="False when the recogniser failed on that batch",
        default=False,
        options={'SKIP_SAVE'},
    )


def unregister():
    for attr in _ATTRS:
        if hasattr(bpy.types.WindowManager, attr):
            delattr(bpy.types.WindowManager, attr)
