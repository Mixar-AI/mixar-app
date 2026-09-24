# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operators for the job queue UIList."""

from bpy.props import StringProperty
from bpy.types import Operator

from mixar.modules.common.job_queue.core.queue_manager import get_queue


class MIXIE_OT_queue_cancel_job(Operator):
    """Cancel a single queued or running job."""

    bl_idname = "mixie.queue_cancel_job"
    bl_label = "Cancel Job"
    bl_options = {'REGISTER'}

    feature_key: StringProperty(default="")
    job_id: StringProperty(default="")

    def execute(self, context):
        if not self.feature_key or not self.job_id:
            return {'CANCELLED'}
        get_queue(self.feature_key).cancel(self.job_id)
        return {'FINISHED'}


class MIXIE_OT_queue_copy_error(Operator):
    """Copy the full error details to clipboard"""

    bl_idname = "mixie.queue_copy_error"
    bl_label = "Copy Error"
    bl_description = "Copy full error details to clipboard"
    bl_options = {'REGISTER'}

    feature_key: StringProperty(default="")
    job_id: StringProperty(default="")

    def execute(self, context):
        if not self.feature_key or not self.job_id:
            return {'CANCELLED'}
        queue = get_queue(self.feature_key)
        for job in queue.snapshot():
            if job.id == self.job_id:
                context.window_manager.clipboard = job.error or "Unknown error"
                self.report({'INFO'}, "Error copied to clipboard")
                return {'FINISHED'}
        self.report({'WARNING'}, "Job not found in queue")
        return {'CANCELLED'}


class MIXIE_OT_queue_cancel_all(Operator):
    """Cancel every non-terminal job in the queue."""

    bl_idname = "mixie.queue_cancel_all"
    bl_label = "Cancel All"
    bl_options = {'REGISTER'}

    feature_key: StringProperty(default="")

    def execute(self, context):
        if not self.feature_key:
            return {'CANCELLED'}
        get_queue(self.feature_key).cancel_all()
        return {'FINISHED'}


class MIXIE_OT_queue_clear_completed(Operator):
    """Remove all terminal (success/failed/cancelled) jobs from the queue."""

    bl_idname = "mixie.queue_clear_completed"
    bl_label = "Clear Completed"
    bl_options = {'REGISTER'}

    feature_key: StringProperty(default="")

    def execute(self, context):
        if not self.feature_key:
            return {'CANCELLED'}
        get_queue(self.feature_key).clear_completed()
        return {'FINISHED'}


class MIXIE_OT_queue_clear_all_completed(Operator):
    """Remove all terminal jobs from every feature queue."""

    bl_idname = "mixie.queue_clear_all_completed"
    bl_label = "Clear All Completed"
    bl_options = {'REGISTER'}

    def execute(self, context):
        from mixar.modules.common.job_queue.core.queue_manager import all_queues
        for q in all_queues():
            q.clear_completed()
        return {'FINISHED'}


def _show_island_queue_tab(context) -> bool:
    """Open the agent island on its Queue tab. True when it actually opened.

    The island's Queue tab lists the ``wm.mixie_queue`` mirror, and it
    is where the user is already watching the
    status pill tick, so that is where "View Queue" should land. The tab is
    plain RNA (``wm.mixar_bubble_tab``) and opening is a plain operator call,
    so nothing here imports the agent_bubble module.

    Returns False when the
    island is unavailable: a build without the spacetype, or a platform whose
    window controls are stubbed (see ``BUBBLE_WINDOW_CONTROLS_SUPPORTED``).
    """
    wm = getattr(context, "window_manager", None)
    if wm is None or not hasattr(wm, "mixar_bubble_tab"):
        return False

    import bpy

    open_op = getattr(getattr(bpy.ops, "mixar", None), "agent_bubble_open_window", None)
    if open_op is None:
        return False
    try:
        if open_op() != {'FINISHED'}:
            return False
    except Exception:  # noqa: BLE001 — never let the toast action raise
        return False

    # Set the tab AFTER opening: the open path restores from the pill, and a
    # tab set first would be repainted before the window is on screen.
    try:
        wm.mixar_bubble_tab = 'QUEUE'
    except Exception:  # noqa: BLE001
        return False
    return True


class MIXIE_OT_queue_view(Operator):
    """Show the job queue in the agent island's Queue tab."""

    bl_idname = "mixie.queue_view"
    bl_label = "View Queue"
    bl_options = {'REGISTER'}

    def execute(self, context):
        if _show_island_queue_tab(context):
            return {'FINISHED'}

        self.report({'WARNING'}, "The Agent island Queue is unavailable")
        return {'CANCELLED'}


classes = (
    MIXIE_OT_queue_cancel_job,
    MIXIE_OT_queue_copy_error,
    MIXIE_OT_queue_cancel_all,
    MIXIE_OT_queue_clear_completed,
    MIXIE_OT_queue_clear_all_completed,
    MIXIE_OT_queue_view,
)
