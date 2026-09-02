# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Arming, disarming, and tidying Scribble.

The toggle is the feature's one entry point, and it lives in the chat
composer next to the other ways of showing the agent something. It arms
BOTH surfaces at once — handwriting over the chat, marks over the frozen
viewport — through ``core/scribble_mode.py``, which is also what every
other exit (Esc, send) goes through, so the two halves cannot drift apart.

Disarming the viewport half works by clearing ``wm.mixar_mark_armed`` — the
running modal watches that flag and stops. There is deliberately no second
mechanism: a "stop the modal" call that could disagree with the flag is
exactly how a viewport ends up blocked with nothing left running to
unblock it.
"""

from __future__ import annotations

from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.scribble_mark.core import marks as mark_store
from mixar.modules.scribble_mark.core import overlay, scribble_mode

logger = get_logger(__name__)


class MIXAR_OT_scribble_toggle(Operator):
    """Scribble: write in the chat to type, draw on the viewport to point"""

    bl_idname = "mixar.scribble_toggle"
    bl_label = "Scribble"
    bl_description = (
        "Scribble with a stylus or the mouse. Writing over the chat is "
        "converted to text in the message box; drawing on the frozen 3D "
        "viewport marks what you mean, and the marks are sent with your "
        "message already resolved against the scene"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        wm = context.window_manager
        if scribble_mode.is_armed(wm):
            # One exit for both halves: the canvas converts what is still
            # on it and lowers; the freeze modal sees the flag drop on its
            # next event and finishes, committing anything half-drawn.
            scribble_mode.disarm(wm)
            overlay.tag_redraw()
            return {"FINISHED"}

        if not scribble_mode.arm(context, report=self.report):
            self.report({"WARNING"},
                        "Nothing to scribble on — open a 3D viewport or the chat")
            return {"CANCELLED"}
        return {"FINISHED"}


class MIXAR_OT_scribble_mark_undo(Operator):
    """Remove the most recent mark"""

    bl_idname = "mixar.scribble_mark_undo"
    bl_label = "Undo Last Mark"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return mark_store.count(context.scene) > 0

    def execute(self, context):
        if not mark_store.remove_last(context.scene):
            return {"CANCELLED"}
        overlay.pop_settled()
        mark_store.refresh_reading(context.scene, context.window_manager)
        overlay.tag_redraw()
        return {"FINISHED"}


class MIXAR_OT_scribble_mark_clear(Operator):
    """Remove every mark and release what they created"""

    bl_idname = "mixar.scribble_mark_clear"
    bl_label = "Clear Marks"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return mark_store.count(context.scene) > 0

    def execute(self, context):
        removed = mark_store.clear(context.scene)
        overlay.reset()
        wm = context.window_manager
        # The reading override described ink that no longer exists.
        if getattr(wm, "mixar_mark_intent", "AUTO") != "AUTO":
            wm.mixar_mark_intent = "AUTO"
        overlay.tag_redraw()
        self.report({"INFO"}, f"Cleared {removed} mark(s)")
        return {"FINISHED"}


classes = (
    MIXAR_OT_scribble_toggle,
    MIXAR_OT_scribble_mark_undo,
    MIXAR_OT_scribble_mark_clear,
)
