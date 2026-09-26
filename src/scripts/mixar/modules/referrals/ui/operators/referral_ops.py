# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Refer a Friend — opened from the profile card.

A user who runs out of credits can share their invite link or have the
backend email it to friends without leaving the app for the web dashboard.
The link, award amounts and email sending are all backend-owned
(``/api/v1/referrals``); this module only displays and forwards.
"""

from __future__ import annotations

import bpy
from bpy.types import Operator

from ... import constants as C
from ...core import flow
from ...core.invites import parse_emails
from . import referral_dialog_ui


def _dialog_host_window(context):
    """The main window to open over when invoked from the Agent Bubble.

    A props dialog opened inside the bubble's small overlay window is
    clipped to it, so prefer the non-bubble window with the most areas.
    """
    try:
        from mixar.modules.agent_bubble.core.bubble_lifecycle import (
            is_agent_bubble_window,
        )
        if not is_agent_bubble_window(context.window):
            return None
        candidates = [w for w in context.window_manager.windows
                      if not is_agent_bubble_window(w) and w.screen.areas]
    except Exception:  # noqa: BLE001 — stripped builds: stay in place
        return None
    return max(candidates, key=lambda w: len(w.screen.areas)) if candidates else None


class MIXAR_OT_refer_friend(Operator):
    """Share your invite link or email it to friends to earn bonus credits"""

    bl_idname = "mixar.refer_friend"
    bl_label = "Refer a Friend"

    @classmethod
    def poll(cls, context):
        return bool(getattr(context.window_manager, "mixie_chat_is_logged_in", False))

    def invoke(self, context, event):
        wm = context.window_manager
        flow.reset(wm)
        flow.load()
        # invoke_props_dialog (not invoke_popup) so the dialog keeps
        # redrawing while the async load/send flips the state.
        host = _dialog_host_window(context)
        if host is not None and host != context.window:
            with context.temp_override(window=host):
                return wm.invoke_props_dialog(self, width=C.DIALOG_WIDTH)
        return wm.invoke_props_dialog(self, width=C.DIALOG_WIDTH)

    def execute(self, context):
        # No-op: Copy / Send are their own operators, invoked from draw().
        return {'FINISHED'}

    def draw(self, context):
        referral_dialog_ui.draw_dialog(self.layout, context.window_manager)


class MIXAR_OT_referral_copy_link(Operator):
    """Copy your invite link to the clipboard"""

    bl_idname = "mixar.referral_copy_link"
    bl_label = "Copy Invite Link"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return bool(context.window_manager.mixar_referral_url)

    def execute(self, context):
        wm = context.window_manager
        wm.clipboard = wm.mixar_referral_url
        flow.set_notice(wm, "Invite link copied")
        self.report({'INFO'}, "Invite link copied to clipboard")
        return {'FINISHED'}


class MIXAR_OT_referral_send_invites(Operator):
    """Email your invite link to the addresses above"""

    bl_idname = "mixar.referral_send_invites"
    bl_label = "Send Invites"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.window_manager.mixar_referral_state == C.STATE_READY

    def execute(self, context):
        wm = context.window_manager
        valid, invalid = parse_emails(wm.mixar_referral_emails)
        if invalid:
            flow.set_notice(wm, f"'{invalid[0][:60]}' is not a valid email address",
                            C.NOTICE_ERROR)
            return {'CANCELLED'}
        if not valid:
            flow.set_notice(wm, "Add at least one friend's email address", C.NOTICE_ERROR)
            return {'CANCELLED'}
        if len(valid) > C.MAX_INVITES_PER_SEND:
            flow.set_notice(wm, f"Invite up to {C.MAX_INVITES_PER_SEND} friends at a time",
                            C.NOTICE_ERROR)
            return {'CANCELLED'}
        flow.send(wm, valid)
        return {'FINISHED'}


class MIXAR_OT_referral_reload(Operator):
    """Try loading your invite link again"""

    bl_idname = "mixar.referral_reload"
    bl_label = "Try Again"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        flow.reset(context.window_manager)
        flow.load()
        return {'FINISHED'}


classes = (
    MIXAR_OT_refer_friend,
    MIXAR_OT_referral_copy_link,
    MIXAR_OT_referral_send_invites,
    MIXAR_OT_referral_reload,
)
