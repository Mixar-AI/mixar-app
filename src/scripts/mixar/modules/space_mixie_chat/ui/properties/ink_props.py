# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scribble (stylus handwriting) Properties

Two WindowManager flags shared with the C++ ink overlay
(``editors/space_mixie_chat/mixie_chat_ink_overlay.cc``), which reads both
via RNA on every draw:

  - mixie_chat_ink_visible: whether the ink canvas is open. Written from
    Python (the header toggle) AND from C++ (ESC / close X / a stylus
    press that auto-opens the canvas) — same contract as
    ``mixie_chat_rules_visible``.
  - mixie_chat_ink_busy: a recognition request is in flight, so the
    overlay draws its "Converting…" indicator. Owned by
    ``core/scribble.py``, which re-tags the chat surfaces on every flip.

Both are SKIP_SAVE: they describe an in-progress gesture, never the saved
scene. No update callbacks — nothing derives from these but the drawing.
"""

import bpy
from bpy.props import BoolProperty


def register():
    bpy.types.WindowManager.mixie_chat_ink_visible = BoolProperty(
        name="Scribble Visible",
        description="Whether the handwriting canvas is open over the chat",
        default=False,
        options={'SKIP_SAVE'},
    )
    bpy.types.WindowManager.mixie_chat_ink_busy = BoolProperty(
        name="Scribble Converting",
        description="True while handwriting is being converted to text",
        default=False,
        options={'SKIP_SAVE'},
    )


def unregister():
    for attr in ('mixie_chat_ink_visible', 'mixie_chat_ink_busy'):
        if hasattr(bpy.types.WindowManager, attr):
            delattr(bpy.types.WindowManager, attr)
