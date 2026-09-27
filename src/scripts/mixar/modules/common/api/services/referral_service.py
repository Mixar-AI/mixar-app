# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Referral rewards — ``/api/v1/referrals``.

Two calls back the profile card's Refer a Friend dialog:

* ``GET dashboard`` — the user's personal invite link plus the award amounts
  and qualified-referral count the dialog shows.
* ``POST invite-emails`` — the backend emails that link to friends. The client
  never sends mail itself and never builds the link: both are the backend's.

Async only; the shared request queue delivers callbacks on the main thread.
"""

from typing import Callable, List, Optional

from ..constants import APIModule
from ..response import APIResponse
from .base_service import BaseService


class ReferralService(BaseService):
    """Client for the referral endpoints the desktop app uses."""

    @property
    def module(self) -> APIModule:
        return APIModule.REFERRALS

    def dashboard_async(
        self,
        *,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        timeout: float = 20.0,
    ) -> str:
        return self.get_async(
            "dashboard", timeout=timeout, on_success=on_success, on_error=on_error,
        )

    def invite_emails_async(
        self,
        emails: List[str],
        *,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        timeout: float = 45.0,
    ) -> str:
        """Ask the backend to email the invite link to *emails*.

        The timeout covers one SMTP send per recipient on the backend.
        """
        return self.post_async(
            "invite-emails",
            json={"emails": list(emails)},
            timeout=timeout,
            on_success=on_success,
            on_error=on_error,
        )


_instance: Optional[ReferralService] = None


def get_referral_service() -> ReferralService:
    """Cached singleton."""
    global _instance
    if _instance is None:
        _instance = ReferralService()
    return _instance
