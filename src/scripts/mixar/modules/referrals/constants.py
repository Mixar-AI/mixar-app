# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the profile card's Refer a Friend dialog."""

from __future__ import annotations

#: Mirrors the backend's per-request cap (``modules/referrals/invite_emails.py``
#: ``MAX_PER_REQUEST``). Checked here only so the user hears it before a round
#: trip; the backend enforces it regardless.
MAX_INVITES_PER_SEND = 5

#: Popup width in pixels. Wide enough for a full ``/auth/signup?ref=MXR-…``
#: invite link on one line at default UI scale.
DIALOG_WIDTH = 480

#: Dialog states (``WindowManager.mixar_referral_state``).
STATE_LOADING = 'LOADING'
STATE_READY = 'READY'
STATE_SENDING = 'SENDING'
STATE_ERROR = 'ERROR'

#: Notice kinds (``WindowManager.mixar_referral_notice_kind``).
NOTICE_INFO = 'INFO'
NOTICE_ERROR = 'ERROR'

#: Separators accepted between addresses in the email field.
EMAIL_SEPARATORS = ",; \t\n"

#: Share of the credits a referred friend buys on their first purchase (top-up
#: or plan) that the inviter earns. Display only; the backend computes the award.
REFERRAL_REWARD_PERCENT = 30

#: A live drop to this balance or below raises the low-credit toast, whose
#: button opens Refer a Friend (``core/low_credit.py``).
LOW_CREDIT_THRESHOLD = 200

#: Fixed toast id: a repeat replaces the toast instead of stacking another.
LOW_CREDIT_NOTIFICATION_ID = "mixar-low-credit-referral"
