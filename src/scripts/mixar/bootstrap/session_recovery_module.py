# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crash-safe sessions: register the journal, the save points, the restore
prompt and Unsaved Work (``mixar.modules.session_recovery``).

The operators live here, not in an auto-discovered ``ui/`` folder, because
the splash draws them during startup, before the time-budgeted UI discovery
has registered anything.
"""

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

# Where a recovery choice was made (telemetry ``surface``).
_SURFACES = [("SPLASH", "Splash", ""), ("DIALOG", "Dialog", ""), ("FILE_MENU", "File menu", "")]


class MIXAR_OT_restore_crashed_session(Operator):
    """Open the work Mixar saved before it closed unexpectedly"""

    bl_idname = "mixar.restore_crashed_session"
    bl_label = "Restore"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        from mixar.modules.session_recovery import runtime
        if not runtime.restore_deferred("splash"):
            self.report({'WARNING'}, "Nothing to restore")
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_OT_discard_crashed_session(Operator):
    """Start with a new file; the saved work is kept for 7 days but not offered again"""

    bl_idname = "mixar.discard_crashed_session"
    bl_label = "Start fresh"
    bl_options = {'INTERNAL'}

    surface: EnumProperty(items=_SURFACES, default='SPLASH', options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        from mixar.modules.session_recovery import runtime
        runtime.discard_offer(self.surface.lower())
        return {'FINISHED'}


class MIXAR_OT_crashed_session_prompt(Operator):
    """Mixar closed unexpectedly: restore the work it saved"""

    bl_idname = "mixar.crashed_session_prompt"
    bl_label = "Restore your work"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        from mixar.modules.session_recovery import runtime, telemetry
        offer = runtime.current_offer()
        if offer is None:
            return {'CANCELLED'}
        telemetry.note_offered("dialog", offer)
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
        col.operator("mixar.discard_crashed_session", text="Start fresh instead",
                     emboss=False).surface = 'DIALOG'

    def execute(self, context):
        from mixar.modules.session_recovery import runtime
        if not runtime.restore_deferred("dialog"):
            return {'CANCELLED'}
        return {'FINISHED'}

    def cancel(self, context):
        # Escape or a click outside is not a choice: nothing is resolved, and
        # the next launch offers the same work again.
        pass


class MIXAR_OT_restore_unsaved_session(Operator):
    """Open this work, saved before Mixar closed unexpectedly. Nothing is written to your project until you save"""

    bl_idname = "mixar.restore_unsaved_session"
    bl_label = "Restore Unsaved Work"
    bl_options = {'INTERNAL'}

    session: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})
    surface: EnumProperty(items=_SURFACES, default='FILE_MENU', options={'SKIP_SAVE', 'HIDDEN'})

    def invoke(self, context, event):
        if bpy.data.is_dirty:
            return context.window_manager.invoke_confirm(
                self, event, title="Restore Unsaved Work",
                message="The open document has unsaved changes. They are lost if you restore now.",
                confirm_text="Restore", icon='WARNING',
            )
        return self.execute(context)

    def execute(self, context):
        from mixar.modules.session_recovery import prompt, runtime, telemetry
        surface = self.surface.lower()
        if runtime.agent_scenes():
            self.report({'WARNING'}, "Wait for the agent to finish, or stop it, before restoring other work")
            return {'CANCELLED'}
        entry = prompt.find(self.session)
        if entry is None:
            telemetry.track("failed", {"session": self.session}, surface=surface,
                            failure_category="unavailable")
            self.report({'WARNING'}, "This work is no longer available. It may be open in another Mixar window")
            return {'CANCELLED'}
        if not runtime.restore_entry(entry, surface):
            self.report({'WARNING'}, "A restore is already running")
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXAR_OT_unsaved_work(Operator):
    """Work Mixar saved before it closed unexpectedly: open any of it again"""

    bl_idname = "mixar.unsaved_work"
    bl_label = "Unsaved Work"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        from mixar.modules.session_recovery import prompt, telemetry
        if prompt.scan():
            telemetry.note_offered("file_menu", None)
        return context.window_manager.invoke_popup(self, width=480)

    def draw(self, context):
        from mixar.modules.session_recovery import prompt
        prompt.draw_unsaved_list(self.layout)

    def execute(self, context):
        return {'FINISHED'}


def _draw_recover_entry(self, context):
    """File > Recover > Unsaved Work..., beside the stock Last Session and Auto Save."""
    layout = self.layout
    layout.separator()
    layout.operator_context = 'INVOKE_DEFAULT'
    layout.operator("mixar.unsaved_work", text="Unsaved Work...", icon='RECOVER_LAST')


classes = (
    MIXAR_OT_restore_crashed_session,
    MIXAR_OT_discard_crashed_session,
    MIXAR_OT_crashed_session_prompt,
    MIXAR_OT_restore_unsaved_session,
    MIXAR_OT_unsaved_work,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    try:
        from mixar.modules.session_recovery import prompt, runtime
        runtime.register()
        prompt.scan()
    except Exception as e:  # noqa: BLE001 — recovery must never stop the app starting
        logger.error(f"[RECOVERY] not started: {e}", exc_info=True)
    recover_menu = getattr(bpy.types, "TOPBAR_MT_file_recover", None)
    if recover_menu is not None:
        recover_menu.append(_draw_recover_entry)


def unregister():
    recover_menu = getattr(bpy.types, "TOPBAR_MT_file_recover", None)
    if recover_menu is not None:
        try:
            recover_menu.remove(_draw_recover_entry)
        except Exception:  # noqa: BLE001
            pass
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
