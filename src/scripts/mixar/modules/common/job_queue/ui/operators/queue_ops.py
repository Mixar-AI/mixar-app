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


class MIXIE_OT_queue_view(Operator):
    """Switch sidebar to the Queue panel."""

    bl_idname = "mixie.queue_view"
    bl_label = "View Queue"
    bl_options = {'REGISTER'}

    def execute(self, context):
        space = context.space_data
        if hasattr(space, 'show_region_ui'):
            space.show_region_ui = True
        # Switch sidebar category to Queue
        region = next(
            (r for r in context.area.regions if r.type == 'UI'), None,
        )
        if region and hasattr(region, 'active_panel_category'):
            region.active_panel_category = "Queue"
        return {'FINISHED'}


classes = (
    MIXIE_OT_queue_cancel_job,
    MIXIE_OT_queue_copy_error,
    MIXIE_OT_queue_cancel_all,
    MIXIE_OT_queue_clear_completed,
    MIXIE_OT_queue_clear_all_completed,
    MIXIE_OT_queue_view,
)
