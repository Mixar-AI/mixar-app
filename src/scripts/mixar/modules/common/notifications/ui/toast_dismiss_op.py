# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Toast Click & Hover Operators

Execute-only operators invoked by the C++ UI handler in
view3d_toast_click.cc.  Both receive region-local mouse coordinates and
check them against the per-region toast bounds built each draw pass by
toast_renderer.

* ``notification.toast_click`` — dispatches the click (dismiss, invoke
  operator with a short pressed-state flash, or open URL).
* ``notification.toast_hover`` — updates the hover highlight; returns
  FINISHED only when the hover target changed so the C++ side knows to
  redraw.
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ..constants import PRESS_FLASH_DURATION
from ..store import get_notification_store
from ..toast_renderer import (
    bounds_for_region,
    point_in_rect,
    toast_pressed_state,
    update_hover_state,
)

logger = get_logger(__name__)


def _invoke_operator(operator_idname: str) -> None:
    """Invoke a ``category.name`` operator idname, logging failures."""
    try:
        parts = operator_idname.split(".")
        if len(parts) == 2:
            category, name = parts
            op = getattr(getattr(bpy.ops, category), name)
            op('EXEC_DEFAULT')
    except Exception as e:
        logger.error("Failed to invoke %s: %s", operator_idname, e)


def _press_button(nid: str, operator_idname: str) -> None:
    """Show the pressed state, then fire the action after a short flash.

    The deferred timer lets the user actually see the button depress
    before the action (which may dismiss the toast or quit the app) runs.
    """
    toast_pressed_state["key"] = ("action", nid, operator_idname)

    def _fire():
        from ..toast_timer import _tag_redraw_view3d

        toast_pressed_state["key"] = None
        _invoke_operator(operator_idname)
        _tag_redraw_view3d()
        return None

    bpy.app.timers.register(_fire, first_interval=PRESS_FLASH_DURATION)


class NOTIFICATION_OT_toast_click(Operator):
    """Handle clicks on toast close buttons, action buttons, and URLs"""
    bl_idname = "notification.toast_click"
    bl_label = "Toast Click"
    bl_options = {'INTERNAL'}

    mouse_x: bpy.props.IntProperty()
    mouse_y: bpy.props.IntProperty()

    def execute(self, context):
        region = context.region
        bounds = bounds_for_region(region.as_pointer()) if region else None
        if not bounds:
            return {'CANCELLED'}

        mx, my = self.mouse_x, self.mouse_y
        store = get_notification_store()

        # Close buttons
        for nid, bx, by, bw, bh in bounds["close"]:
            if point_in_rect(mx, my, bx, by, bw, bh):
                store.dismiss(nid)
                return {'FINISHED'}

        # Action buttons — flash pressed state, then fire via timer
        for nid, operator_idname, bx, by, bw, bh in bounds["action"]:
            if point_in_rect(mx, my, bx, by, bw, bh):
                if toast_pressed_state["key"] is None:
                    _press_button(nid, operator_idname)
                return {'FINISHED'}

        # URL links
        for nid, url, bx, by, bw, bh in bounds["url"]:
            if point_in_rect(mx, my, bx, by, bw, bh):
                # Native opener — webbrowser.open() fails silently under
                # Blender's embedded Python.
                try:
                    bpy.ops.wm.url_open(url=url)
                except Exception as e:
                    logger.error("Failed to open URL %s: %s", url, e)
                return {'FINISHED'}

        # No hit — C++ handler will pass the event through
        return {'CANCELLED'}


class NOTIFICATION_OT_toast_hover(Operator):
    """Update toast hover highlight from mouse position"""
    bl_idname = "notification.toast_hover"
    bl_label = "Toast Hover"
    bl_options = {'INTERNAL'}

    mouse_x: bpy.props.IntProperty()
    mouse_y: bpy.props.IntProperty()

    def execute(self, context):
        region = context.region
        if region is None:
            return {'CANCELLED'}

        changed = update_hover_state(region.as_pointer(), self.mouse_x, self.mouse_y)
        # FINISHED signals the C++ handler to tag a redraw
        return {'FINISHED'} if changed else {'CANCELLED'}


classes = (
    NOTIFICATION_OT_toast_click,
    NOTIFICATION_OT_toast_hover,
)
