# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crash-safe sessions: register the journal, the save points and the
restore prompt (``mixar.modules.session_recovery``)."""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


class MIXAR_OT_restore_crashed_session(Operator):
    """Open the work Mixar saved before it closed unexpectedly"""

    bl_idname = "mixar.restore_crashed_session"
    bl_label = "Restore"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        from mixar.modules.session_recovery import runtime
        if not runtime.restore_deferred():
            self.report({'WARNING'}, "Nothing to restore")
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_OT_discard_crashed_session(Operator):
    """Start with a new file; the saved work is kept for 7 days but not offered again"""

    bl_idname = "mixar.discard_crashed_session"
    bl_label = "Start fresh"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        from mixar.modules.session_recovery import runtime
        runtime.discard_offer()
        return {'FINISHED'}


class MIXAR_OT_crashed_session_prompt(Operator):
    """Mixar closed unexpectedly: restore the work it saved"""

    bl_idname = "mixar.crashed_session_prompt"
    bl_label = "Restore your work"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        from mixar.modules.session_recovery import runtime
        offer = runtime.current_offer()
        if offer is None:
            return {'CANCELLED'}
        return context.window_manager.invoke_props_dialog(
            self, width=460, title=runtime.describe(offer)["title"],
            confirm_text="Restore", cancel_default=False,
        )

    def draw(self, context):
        from mixar.modules.session_recovery import runtime
        offer = runtime.current_offer()
        if offer is None:
            self.layout.label(text="Nothing to restore")
            return
        col = self.layout.column()
        col.label(text=runtime.describe(offer)["detail"])
        col.label(text="Nothing is written to your project until you save.")
        col.separator()
        col.operator("mixar.discard_crashed_session", text="Start fresh instead", emboss=False)

    def execute(self, context):
        from mixar.modules.session_recovery import runtime
        if not runtime.restore_deferred():
            return {'CANCELLED'}
        return {'FINISHED'}

    def cancel(self, context):
        # Escape or a click outside is not a choice: nothing is resolved, and
        # the next launch offers the same work again.
        pass


classes = (
    MIXAR_OT_restore_crashed_session,
    MIXAR_OT_discard_crashed_session,
    MIXAR_OT_crashed_session_prompt,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    try:
        from mixar.modules.session_recovery import runtime
        runtime.register()
    except Exception as e:  # noqa: BLE001 — recovery must never stop the app starting
        logger.error(f"[RECOVERY] not started: {e}", exc_info=True)


def unregister():
    try:
        from mixar.modules.session_recovery import runtime
        runtime.unregister()
    except Exception:  # noqa: BLE001
        pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
