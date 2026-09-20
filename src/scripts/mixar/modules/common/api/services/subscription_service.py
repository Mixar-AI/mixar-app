# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Subscriptions API Service.

Handles ``/api/v1/subscriptions`` endpoints. Only the read-only billing
status is exposed here — purchase/upgrade flows deliberately stay on the
web dashboard (reached through the auth handoff URL), so the desktop
client never handles payment UI.

The status endpoint answers **404 for free-tier users** ("No active
subscription"). That is a normal account state, not a failure, so every
call here uses ``raise_for_status=False`` and the caller distinguishes
via :attr:`APIResponse.status_code`.
"""

from typing import Callable, Optional

from ..constants import APIModule
from ..response import APIResponse
from .base_service import BaseService


class SubscriptionService(BaseService):
    """
    Subscription/billing status service.

    Endpoints:
    - GET /status - Current subscription, credit balance and cycle info
    """

    @property
    def module(self) -> APIModule:
        return APIModule.SUBSCRIPTIONS

    # ========================================================================
    # SYNC METHODS
    # ========================================================================

    def get_status(self, timeout: Optional[float] = None) -> APIResponse:
        """
        Fetch the current user's subscription status.

        On success ``response.data`` is the backend envelope
        ``{"status": "success", "data": {...}}`` whose inner dict carries
        ``plan_slug``, ``plan_name``, ``billing_interval``,
        ``credits_per_month``, ``balance_cents``, ``plan_value_cents``,
        ``usage_pct``, ``cycle_start``, ``cycle_end``, ``days_left`` and
        ``subscription_expires_at``.

        Returns:
            APIResponse. ``status_code == 404`` means the user is on the
            free tier (or has no subscription payment on record) — check
            that before treating the response as an error.
        """
        return self.get("status", timeout=timeout, raise_for_status=False)

    # ========================================================================
    # ASYNC METHODS
    # ========================================================================

    def get_status_async(
        self,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        timeout: Optional[float] = None,
    ) -> str:
        """Async variant of :meth:`get_status`. Returns the request id."""
        return self.get_async(
            "status",
            on_success=on_success,
            on_error=on_error,
            timeout=timeout,
            raise_for_status=False,
        )


# ============================================================================
# Singleton accessor
# ============================================================================

_subscription_service: Optional[SubscriptionService] = None


def get_subscription_service() -> SubscriptionService:
    """Get the shared SubscriptionService instance."""
    global _subscription_service
    if _subscription_service is None:
        _subscription_service = SubscriptionService()
    return _subscription_service
