# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The ONLY way a public publish starts: the user approves it here.

``invoke`` (toast button, Game tab button) issues a one-time token into a
hidden property and shows a confirm dialog; ``execute`` — reached when the
user clicks the dialog's Publish — claims the request with that token.
A script calling ``EXEC_DEFAULT`` has no token; one calling
``INVOKE_DEFAULT`` only opens the dialog for the user; and ``execute``
refuses outright while an agent script is on the call stack.
"""

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from mixar.config.agent_guard import called_from_agent_script
from mixar.modules.common.i18n import iface_, rpt_
from mixar.modules.game_studio.constants import platform_list
from mixar.modules.game_studio.core import approvals, launch



def _agent_frame_on_stack() -> bool:
    return called_from_agent_script()


def _dismiss_toast(request_id: str) -> None:
    try:
        from mixar.modules.common.notifications import get_notification_store
        get_notification_store().dismiss(f"game-publish-{request_id}")
    except Exception:
        pass


class MIXAR_OT_game_publish_approve(Operator):
    """Approve publishing this game to the Mixar Store"""
    bl_idname = "mixar.game_publish_approve"
    bl_label = "Publish to Mixar Store"
    bl_options = {'INTERNAL'}

    request_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})
    token: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def invoke(self, context, event):
        request = approvals.get(self.request_id) if self.request_id else approvals.pending()
        if request is None or request["state"] != approvals.AWAITING:
            self.report({'WARNING'}, rpt_("No publish is waiting for approval."))
            return {'CANCELLED'}
        self.request_id = request["request_id"]
        self.token = approvals._issue_token(self.request_id)
        summary = request["summary"]
        return context.window_manager.invoke_confirm(
            self, event,
            title=iface_("Publish \"{title}\" to the Mixar Store?").format(title=summary["title"]),
            message=iface_("{platforms} build(s). The store page goes public now; builds are "
                           "playable after moderator review.").format(
                platforms=platform_list(summary["platforms"])),
            confirm_text=iface_("Publish"), translate=False)

    def execute(self, context):
        if bpy.app.background or _agent_frame_on_stack():
            self.report({'ERROR'}, rpt_("Only you can approve a publish, from the Mixar window."))
            return {'CANCELLED'}
        payload = approvals._claim(self.request_id, self.token)
        if payload is None:
            self.report({'ERROR'}, rpt_("This publish request is no longer waiting for approval."))
            return {'CANCELLED'}
        _dismiss_toast(self.request_id)
        reply = launch.start_approved_publish(self.request_id, payload)
        if not reply.get("ok"):
            approvals.mark_failed(self.request_id, reply.get("error") or "", reply.get("error_code") or "failed")
            self.report({'ERROR'}, reply.get("error") or rpt_("Could not start."))
            return {'CANCELLED'}
        self.report({'INFO'}, rpt_("Publishing…"))
        return {'FINISHED'}


class MIXAR_OT_game_publish_decline(Operator):
    """Cancel the waiting publish request"""
    bl_idname = "mixar.game_publish_decline"
    bl_label = "Cancel Publish"
    bl_options = {'INTERNAL'}

    request_id: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        request = approvals.get(self.request_id) if self.request_id else approvals.pending()
        if request is not None:
            approvals.cancel(request["request_id"], "The user declined the publish.", "user_declined")
            _dismiss_toast(request["request_id"])
        return {'FINISHED'}


classes = (MIXAR_OT_game_publish_approve, MIXAR_OT_game_publish_decline)
