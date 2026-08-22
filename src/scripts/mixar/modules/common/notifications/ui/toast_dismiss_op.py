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


def _send_mark_read(server_id: str) -> None:
    """Report a server notification as read over the WebSocket.

    Fire-and-forget: read receipts are best-effort and must never break
    toast interaction (e.g. while offline). Deferred imports keep
    common/ free of an import-time dependency on space_mixie_chat.
    """
    try:
        from ....space_mixie_chat.constants import JSONRPCMethod
        from ....space_mixie_chat.core.jsonrpc_client import get_jsonrpc_client

        client = get_jsonrpc_client()
        if client:
            client.send_request(
                JSONRPCMethod.NOTIFICATIONS_MARK_READ,
                {"notification_ids": [server_id]},
            )
    except Exception as e:
        logger.debug("mark_read skipped for %s: %s", server_id, e)


def _invoke_operator(operator_idname: str) -> None:
    """Invoke a ``category.name`` operator idname, logging failures.

    Runs inside a ``bpy.app.timers`` callback, whose context carries no
    window — but ``INVOKE_DEFAULT`` is what lets a toast button's operator
    show a confirmation dialog (``mixar.restart_to_update`` needs one
    before quitting the app), so a window is borrowed from the window
    manager for the call.  Operators without an ``invoke()`` fall through
    to ``execute()`` exactly as the old ``EXEC_DEFAULT`` dispatch did.
    """
    try:
        parts = operator_idname.split(".")
        if len(parts) != 2:
            return
        category, name = parts
        op = getattr(getattr(bpy.ops, category), name)
        window = next(iter(bpy.context.window_manager.windows), None)
        if window is not None:
            with bpy.context.temp_override(window=window, screen=window.screen):
                op('INVOKE_DEFAULT')
        else:
            op('EXEC_DEFAULT')
    except Exception as e:
        logger.error("Failed to invoke %s: %s", operator_idname, e)


def _open_url_and_mark_read(nid: str, url: str) -> None:
    """Open a notification URL in the browser and report it read.

    Native opener — webbrowser.open() fails silently under Blender's
    embedded Python. Following the CTA counts as reading the notification.
    """
    try:
        bpy.ops.wm.url_open(url=url)
    except Exception as e:
        logger.error("Failed to open URL %s: %s", url, e)
    else:
        server_id = get_notification_store().get_server_id(nid)
        if server_id:
            _send_mark_read(server_id)


def _press_button(nid: str, operator_idname: str, url: str = None) -> None:
    """Show the pressed state, then fire the action after a short flash.

    The deferred timer lets the user actually see the button depress
    before the action (which may dismiss the toast or quit the app) runs.
    URL-carrying buttons (server notifications) open the URL and mark the
    notification read; the rest invoke their operator.
    """
    toast_pressed_state["key"] = ("action", nid, operator_idname or url)

    def _fire():
        from ..toast_timer import _tag_redraw_view3d

        toast_pressed_state["key"] = None
        if url:
            _open_url_and_mark_read(nid, url)
        else:
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
                server_id = store.dismiss(nid)
                if server_id:
                    _send_mark_read(server_id)
                return {'FINISHED'}

        # Action buttons — flash pressed state, then fire via timer
        for nid, operator_idname, url, bx, by, bw, bh in bounds["action"]:
            if point_in_rect(mx, my, bx, by, bw, bh):
                if toast_pressed_state["key"] is None:
                    _press_button(nid, operator_idname, url)
                return {'FINISHED'}

        # URL links
        for nid, url, bx, by, bw, bh in bounds["url"]:
            if point_in_rect(mx, my, bx, by, bw, bh):
                _open_url_and_mark_read(nid, url)
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
