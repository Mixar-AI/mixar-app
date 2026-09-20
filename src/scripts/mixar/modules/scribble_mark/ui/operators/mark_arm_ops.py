# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Viewport annotation controls; prompt input methods remain independent."""

from __future__ import annotations

from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.scribble_mark.core import marks as mark_store
from mixar.modules.scribble_mark.core import overlay, scribble_mode

logger = get_logger(__name__)


class MIXAR_OT_scribble_toggle(Operator):
    """Draw on the viewport while typing or dictating the prompt."""

    bl_idname = "mixar.scribble_toggle"
    bl_label = "Sketch Viewport"
    bl_description = (
        "Freeze the 3D viewport and draw marks or a sketch. "
        "Type or use Voice in chat; your annotations accompany the next message"
    )
    bl_options = {"REGISTER"}

    def execute(self, context):
        wm = context.window_manager
        if scribble_mode.is_armed(wm):
            scribble_mode.disarm_marks(wm)
            overlay.tag_redraw()
            return {"FINISHED"}

        if not scribble_mode.arm(context, report=self.report):
            return {"CANCELLED"}
        return {"FINISHED"}


class MIXAR_OT_scribble_mark_undo(Operator):
    """Remove the most recent mark"""

    bl_idname = "mixar.scribble_mark_undo"
    bl_label = "Undo Last Mark"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        # Drafts only: undo takes back what the user drew this turn. With a
        # SENT mark under the cursor this button would delete something the
        # conversation still refers to.
        return mark_store.count(context.scene, drafts_only=True) > 0

    def execute(self, context):
        if not mark_store.remove_last(context.scene, keep_view=_live_view_name()):
            return {"CANCELLED"}
        overlay.pop_settled()
        mark_store.refresh_reading(context.scene, context.window_manager)
        overlay.tag_redraw()
        return {"FINISHED"}


class MIXAR_OT_scribble_mark_clear(Operator):
    """Discard the queued marks and release what they created

    QUEUED, not every mark. Both surfaces that offer this — the chat header
    and the island chip — show the DRAFT count beside it and the island's
    tooltip says "Discard the queued marks", so a user looking at "2" and
    clicking the X means those two. Removing the SENT marks of earlier turns
    as well would take with them the vertex groups and cameras the
    conversation still names, which is the same thing ``remove_last`` used to
    do through the adjacent button.
    """

    bl_idname = "mixar.scribble_mark_clear"
    bl_label = "Clear Marks"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return mark_store.count(context.scene, drafts_only=True) > 0

    def execute(self, context):
        removed = mark_store.clear(context.scene, drafts_only=True)
        overlay.reset()
        wm = context.window_manager
        # The reading override described ink that no longer exists.
        if getattr(wm, "mixar_mark_intent", "AUTO") != "AUTO":
            wm.mixar_mark_intent = "AUTO"
        overlay.tag_redraw()
        self.report({"INFO"}, f"Cleared {removed} mark(s)")
        return {"FINISHED"}


def _live_view_name():
    """The baked camera of the freeze currently on screen, or ``""``.

    The header Undo is reachable while the viewport half is running (the
    freeze blocks the viewport, not the chat header), and the camera of a
    live freeze belongs to the freeze, not to the mark being undone.
    Imported late so arming stays the only thing that pulls the modal in.
    """
    from mixar.modules.scribble_mark.ui.operators import mark_draw_ops

    return mark_draw_ops.live_view_name()


classes = (
    MIXAR_OT_scribble_toggle,
    MIXAR_OT_scribble_mark_undo,
    MIXAR_OT_scribble_mark_clear,
)
