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
