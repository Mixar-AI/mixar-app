# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Toast Click Operator

Simple execute-only operator invoked by the C++ UI handler in
view3d_toast_click.cc.  Receives mouse coordinates, checks them
against the toast bounding boxes built each frame by toast_renderer,
and dispatches the appropriate action (dismiss, invoke operator, or
open URL).
"""

import webbrowser

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ..store import get_notification_store
from ..toast_renderer import toast_action_bounds, toast_close_bounds, toast_url_bounds

logger = get_logger(__name__)


def _point_in_rect(mx, my, bx, by, bw, bh) -> bool:
    return bx <= mx <= bx + bw and by <= my <= by + bh


class NOTIFICATION_OT_toast_click(Operator):
    """Handle clicks on toast close buttons, action buttons, and URLs"""
    bl_idname = "notification.toast_click"
    bl_label = "Toast Click"
    bl_options = {'INTERNAL'}

    mouse_x: bpy.props.IntProperty()
    mouse_y: bpy.props.IntProperty()

    def execute(self, context):
        mx, my = self.mouse_x, self.mouse_y
        store = get_notification_store()

        # Close buttons
        for nid, bx, by, bw, bh in toast_close_bounds:
            if _point_in_rect(mx, my, bx, by, bw, bh):
                store.dismiss(nid)
                return {'FINISHED'}

        # Action buttons
        for nid, operator_idname, bx, by, bw, bh in toast_action_bounds:
            if _point_in_rect(mx, my, bx, by, bw, bh):
                try:
                    parts = operator_idname.split(".")
                    if len(parts) == 2:
                        category, name = parts
                        op = getattr(getattr(bpy.ops, category), name)
                        op('EXEC_DEFAULT')
                except Exception as e:
                    logger.error("Failed to invoke %s: %s", operator_idname, e)
                return {'FINISHED'}

        # URL links
        for nid, url, bx, by, bw, bh in toast_url_bounds:
            if _point_in_rect(mx, my, bx, by, bw, bh):
                try:
                    webbrowser.open(url)
                except Exception as e:
                    logger.error("Failed to open URL %s: %s", url, e)
                return {'FINISHED'}

        # No hit — C++ handler will pass the event through
        return {'CANCELLED'}


classes = (
    NOTIFICATION_OT_toast_click,
)
