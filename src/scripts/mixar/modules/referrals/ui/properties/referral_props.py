# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""WindowManager state for the Refer a Friend dialog.

WindowManager, never Scene: an invite link and a friend list are one
account's session data and must not travel inside a shared ``.blend``.
"""

from __future__ import annotations

import bpy
from bpy.props import EnumProperty, IntProperty, StringProperty

from ...constants import (
    NOTICE_ERROR,
    NOTICE_INFO,
    STATE_ERROR,
    STATE_LOADING,
    STATE_READY,
    STATE_SENDING,
)

_PROP_NAMES = (
    "mixar_referral_state",
    "mixar_referral_url",
    "mixar_referral_emails",
    "mixar_referral_error",
    "mixar_referral_notice",
    "mixar_referral_notice_kind",
    "mixar_referral_details",
    "mixar_referral_invitee_award",
    "mixar_referral_inviter_award",
    "mixar_referral_paid_total",
    "mixar_referral_count",
)


def register() -> None:
    wm = bpy.types.WindowManager
    wm.mixar_referral_state = EnumProperty(
        name="Referral State",
        items=[
            (STATE_LOADING, "Loading", ""),
            (STATE_READY, "Ready", ""),
            (STATE_SENDING, "Sending", ""),
            (STATE_ERROR, "Error", ""),
        ],
        default=STATE_LOADING,
        options={'SKIP_SAVE'},
    )
    wm.mixar_referral_url = StringProperty(
        name="Invite Link", default="", options={'SKIP_SAVE'})
    wm.mixar_referral_emails = StringProperty(
        name="Friends' Emails",
        description="Up to 5 email addresses, separated by commas",
        default="",
        options={'SKIP_SAVE'},
    )
    wm.mixar_referral_error = StringProperty(default="", options={'SKIP_SAVE'})
    wm.mixar_referral_notice = StringProperty(default="", options={'SKIP_SAVE'})
    wm.mixar_referral_notice_kind = EnumProperty(
        items=[(NOTICE_INFO, "Info", ""), (NOTICE_ERROR, "Error", "")],
        default=NOTICE_INFO,
        options={'SKIP_SAVE'},
    )
    #: Newline-joined per-address outcomes of the last send.
    wm.mixar_referral_details = StringProperty(default="", options={'SKIP_SAVE'})
    wm.mixar_referral_invitee_award = IntProperty(default=0, options={'SKIP_SAVE'})
    wm.mixar_referral_inviter_award = IntProperty(default=0, options={'SKIP_SAVE'})
    wm.mixar_referral_paid_total = IntProperty(default=0, options={'SKIP_SAVE'})
    wm.mixar_referral_count = IntProperty(default=0, options={'SKIP_SAVE'})


def unregister() -> None:
    for name in _PROP_NAMES:
        try:
            delattr(bpy.types.WindowManager, name)
        except Exception:  # noqa: BLE001 — never registered / already gone
            pass
