# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Arming, disarming, and tidying marks.

The toggle is the feature's one entry point, and it lives in the chat
composer next to the other ways of showing the agent something. Disarming
works by clearing ``wm.mixar_mark_armed`` — the running modal watches that
flag and stops. There is deliberately no second mechanism: a "stop the modal"
call that could disagree with the flag is exactly how a viewport ends up
blocked with nothing left running to unblock it.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.scribble_mark.core import marks as mark_store
from mixar.modules.scribble_mark.core import overlay

logger = get_logger(__name__)


class MIXAR_OT_scribble_mark_toggle(Operator):
    """Freeze the viewport and mark what you want the agent to work on"""

    bl_idname = "mixar.scribble_mark_toggle"
    bl_label = "Mark Viewport"
    bl_description = (
        "Freeze the 3D viewport and draw on it. Circle a region, point an "
        "arrow, or tap — the marks are sent with your message and resolved "
        "against the scene, so the agent knows exactly what you meant"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        wm = context.window_manager
        if getattr(wm, "mixar_mark_armed", False):
            # The modal sees the flag drop on its next event and finishes,
            # committing whatever is half-drawn.
            wm.mixar_mark_armed = False
            overlay.tag_redraw()
            return {"FINISHED"}

        try:
            result = bpy.ops.mixar.scribble_mark_draw("INVOKE_DEFAULT")
        except RuntimeError as exc:
            self.report({"ERROR"}, f"Could not start marking: {exc}")
            return {"CANCELLED"}

        if "RUNNING_MODAL" not in result:
            # The modal already reported why (no viewport, capture failed).
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
        overlay.tag_redraw()
        self.report({"INFO"}, f"Cleared {removed} mark(s)")
        return {"FINISHED"}


classes = (
    MIXAR_OT_scribble_mark_toggle,
    MIXAR_OT_scribble_mark_undo,
    MIXAR_OT_scribble_mark_clear,
)
