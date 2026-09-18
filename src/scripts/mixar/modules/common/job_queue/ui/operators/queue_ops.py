# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operators for the job queue UIList."""

from bpy.props import StringProperty
from bpy.types import Operator

from mixar.modules.common.job_queue.core.queue_manager import get_queue
from mixar.modules.common.utils.mixie_space_utils import MIXIE_SPACE_AVAILABLE


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


# The unified Queue panel registers under bl_space_type MIXIE when the
# Mixar space exists (moodboard_sidebar_panels.py) — the "Queue" sidebar
# category does NOT exist in plain VIEW_3D areas, so the operator must
# target the same space type the panels registered in.
QUEUE_AREA_TYPE = 'MIXIE' if MIXIE_SPACE_AVAILABLE else 'VIEW_3D'


def find_largest_queue_area(context):
    """Return the biggest area hosting the Queue panel's space type, or None.

    Fallback target for callers whose context can't reach the Queue tab —
    toast action buttons fire from a ``bpy.app.timers`` callback where
    ``context.area`` is None, and a toast clicked in a 3D viewport still
    needs the MIXIE sidebar.
    """
    wm = getattr(context, "window_manager", None)
    best = None
    best_size = -1
    for window in getattr(wm, "windows", None) or []:
        screen = getattr(window, "screen", None)
        for area in getattr(screen, "areas", None) or []:
            if area.type == QUEUE_AREA_TYPE:
                size = area.width * area.height
                if size > best_size:
                    best, best_size = area, size
    return best


def _show_island_queue_tab(context) -> bool:
    """Open the agent island on its Queue tab. True when it actually opened.

    The island's Queue tab lists the same ``wm.mixie_queue`` mirror the
    sidebar panel does, and it is where the user is already watching the
    status pill tick, so that is where "View Queue" should land. The tab is
    plain RNA (``wm.mixar_bubble_tab``) and opening is a plain operator call,
    so nothing here imports the agent_bubble module.

    Returns False — leaving the caller to fall back to the sidebar — when the
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
    """Show the job queue — the agent island's Queue tab, else the sidebar."""

    bl_idname = "mixie.queue_view"
    bl_label = "View Queue"
    bl_options = {'REGISTER'}

    def execute(self, context):
        if _show_island_queue_tab(context):
            return {'FINISHED'}

        area = getattr(context, "area", None)
        if area is None or area.type != QUEUE_AREA_TYPE:
            area = find_largest_queue_area(context)
        if area is None:
            return {'CANCELLED'}
        space = area.spaces.active
        if hasattr(space, 'show_region_ui'):
            space.show_region_ui = True
        # Switch sidebar category to Queue
        region = next(
            (r for r in area.regions if r.type == 'UI'), None,
        )
        try:
            if region and hasattr(region, 'active_panel_category'):
                from mixar.bootstrap.analytics_module import note_programmatic_panel_change
                note_programmatic_panel_change(region, "Queue")
                region.active_panel_category = "Queue"
        except Exception:
            pass  # sidebar just opened — category list not built yet
        area.tag_redraw()
        return {'FINISHED'}


classes = (
    MIXIE_OT_queue_cancel_job,
    MIXIE_OT_queue_copy_error,
    MIXIE_OT_queue_cancel_all,
    MIXIE_OT_queue_clear_completed,
    MIXIE_OT_queue_clear_all_completed,
    MIXIE_OT_queue_view,
)
