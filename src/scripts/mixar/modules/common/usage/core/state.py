# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cached credit-balance snapshot backing the account card.

Deliberately free of ``bpy`` so the parsing and formatting logic can be
unit-tested outside Blender. The module-level cache lives here; the
:mod:`..core.poller` owns *when* it is refreshed and the UI layer only
ever reads it.

The card shows the credit balance as a plain number — the same figures the
web dashboard prints — and never a percentage: a percentage needs a
denominator, and the app and the website picking different ones is how the
two used to disagree. Every figure is read straight off the backend's
``/subscriptions/status`` buckets and never recomputed client-side.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from mixar.modules.common.i18n import iface_

from ..constants import (
    FREE_BILLING_INTERVAL,
    TRIAL_SLUG_PREFIX,
    USAGE_TTL_SECONDS,
)


@dataclass(frozen=True)
class UsageSnapshot:
    """One reading of the user's credit balance.

    ``has_subscription`` False is the backend's 404: a free-tier account
    that was never granted a credit.
    """

    has_subscription: bool = False
    plan_slug: str = ""
    plan_name: str = ""
    #: ``"monthly"`` / ``"yearly"`` / ``"trial"`` / ``"free"`` — the backend's
    #: reading of what the allocation is. ``"free"`` is a free-tier account
    #: holding bonus credits, with no allowance behind them.
    billing_interval: str = ""
    #: Total credits available (``balance_cents``: monthly + bonus, net of
    #: holds) — the number the card leads with.
    credits_remaining: int = 0
    #: Plan / trial / team-pool allowance left (``monthly_credits_remaining``).
    monthly_remaining: int = 0
    #: Top-ups, referral rewards, sign-up bonus left
    #: (``bonus_credits_remaining``).
    bonus_remaining: int = 0
    #: The plan's monthly allowance (``credits_per_month``); 0 for none.
    credits_per_month: int = 0
    days_left: int = 0
    #: Set when the subscription is cancelling — ``days_left`` then counts
    #: down to expiry rather than to the next cycle.
    is_cancelling: bool = False
    #: Monotonic timestamp of the fetch that produced this snapshot.
    fetched_at: float = 0.0
    #: Populated when the last fetch failed; the previous snapshot's
    #: figures are kept so the meter degrades to stale rather than blank.
    error: str = ""

    @property
    def is_trial(self) -> bool:
        return (self.plan_slug or "").lower().startswith(TRIAL_SLUG_PREFIX)

    @property
    def is_free(self) -> bool:
        """A free-tier account holding credits, with no plan behind them."""
        return self.has_subscription and self.billing_interval == FREE_BILLING_INTERVAL

    @property
    def has_allowance(self) -> bool:
        """Whether a monthly allowance backs part of the balance — the only
        case where splitting it into monthly and bonus says anything."""
        return self.has_subscription and not self.is_free and self.credits_per_month > 0

    @property
    def can_top_up(self) -> bool:
        """Whether "Buy credits" applies — mirrors the web dashboard's
        ``canTopUpCredits`` and the server rule behind ``/subscriptions
        /credit-topup``: every signed-in account, no subscription needed —
        free, trial and cancelling included. The server also refuses an
        enterprise team member, which no usage reading reveals; the buy page
        tells them why."""
        return self.fetched_at > 0.0


#: The empty snapshot — also what a logged-out client reads.
EMPTY = UsageSnapshot()

_lock = threading.Lock()
_snapshot: UsageSnapshot = EMPTY


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------


def get_snapshot() -> UsageSnapshot:
    """Current cached snapshot. Never None; ``EMPTY`` before first fetch."""
    with _lock:
        return _snapshot


def set_snapshot(snapshot: UsageSnapshot) -> None:
    with _lock:
        global _snapshot
        _snapshot = snapshot


def clear() -> None:
    """Drop the cache — called on logout so the next user starts clean."""
    set_snapshot(EMPTY)


def tier_changed(previous: UsageSnapshot, current: UsageSnapshot) -> bool:
    """True when the account moved between plans in a way the backend derives from.

    The agent models catalog carries a per-caller ``eligible`` flag computed
    against the subscription tier, so an upgrade or downgrade silently
    invalidates a catalog that is otherwise still ETag-fresh (the tag hashes the
    rendered body, so it WILL differ — nothing else is watching for the change).

    Deliberately conservative:

    * a FAILED fetch (``current.error``) proves nothing — ``snapshot_error``
      copies the previous figures forward, and a flap must not trigger a refetch
      storm;
    * an unfilled ``previous`` (``fetched_at <= 0``) is the first reading of the
      session, which login already refreshes.

    Pure, and free of ``bpy`` like the rest of this module — :mod:`..core.poller`
    owns acting on it.
    """
    if current.error:
        return False
    if previous.fetched_at <= 0.0:
        return False
    return (
        previous.has_subscription != current.has_subscription
        or previous.plan_slug != current.plan_slug
    )


def is_stale(now: Optional[float] = None) -> bool:
    """True when the cache has never been filled or has aged past its TTL."""
    snap = get_snapshot()
    if snap.fetched_at <= 0.0:
        return True
    current = time.monotonic() if now is None else now
    return (current - snap.fetched_at) >= USAGE_TTL_SECONDS


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def snapshot_from_payload(
    payload: Any,
    credits_remaining: Optional[int] = None,
    now: Optional[float] = None,
) -> UsageSnapshot:
    """Build a snapshot from the ``/subscriptions/status`` response body.

    Accepts either the full envelope ``{"status": ..., "data": {...}}`` or
    the bare inner dict, since the HTTP client's JSON parsing has handed
    back both shapes historically.

    Args:
        payload: Parsed response body.
        credits_remaining: Balance to prefer over the payload's
            ``balance_cents`` — the auth ``/me`` balance is refreshed more
            often than the billing status, so it wins when supplied.
        now: Monotonic timestamp override (tests).
    """
    if not isinstance(payload, dict):
        return UsageSnapshot(
            fetched_at=time.monotonic() if now is None else now,
            error="Malformed subscription status response",
        )

    data = payload.get("data")
    if not isinstance(data, dict):
        data = payload

    balance = _coerce_int(data.get("balance_cents"))
    if credits_remaining is not None:
        balance = _coerce_int(credits_remaining, balance)

    return UsageSnapshot(
        has_subscription=True,
        plan_slug=str(data.get("plan_slug") or ""),
        plan_name=str(data.get("plan_name") or ""),
        billing_interval=str(data.get("billing_interval") or "").lower(),
        credits_remaining=max(0, balance),
        monthly_remaining=max(0, _coerce_int(data.get("monthly_credits_remaining"))),
        bonus_remaining=max(0, _coerce_int(data.get("bonus_credits_remaining"))),
        credits_per_month=max(0, _coerce_int(data.get("credits_per_month"))),
        days_left=max(0, _coerce_int(data.get("days_left"))),
        is_cancelling=bool(data.get("subscription_expires_at")),
        fetched_at=time.monotonic() if now is None else now,
    )


def snapshot_free_tier(
    credits_remaining: int = 0, now: Optional[float] = None
) -> UsageSnapshot:
    """Snapshot for the 404 ("No active subscription") case.

    A free account that was never granted a credit — its balance is zero.
    (A free account WITH a sign-up bonus or referral credits answers 200
    with ``billing_interval == "free"`` and goes through
    :func:`snapshot_from_payload` like any plan.)
    """
    return UsageSnapshot(
        has_subscription=False,
        credits_remaining=max(0, _coerce_int(credits_remaining)),
        fetched_at=time.monotonic() if now is None else now,
    )


def snapshot_error(message: str, now: Optional[float] = None) -> UsageSnapshot:
    """Snapshot recording a failed fetch, keeping the previous figures.

    Timestamped like a success so a hard-down backend is retried on the
    normal TTL cadence rather than on every redraw.
    """
    previous = get_snapshot()
    stamp = time.monotonic() if now is None else now
    return UsageSnapshot(
        has_subscription=previous.has_subscription,
        plan_slug=previous.plan_slug,
        plan_name=previous.plan_name,
        billing_interval=previous.billing_interval,
        credits_remaining=previous.credits_remaining,
        monthly_remaining=previous.monthly_remaining,
        bonus_remaining=previous.bonus_remaining,
        credits_per_month=previous.credits_per_month,
        days_left=previous.days_left,
        is_cancelling=previous.is_cancelling,
        fetched_at=stamp,
        error=str(message or "Usage unavailable"),
    )


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def format_credits(value: int) -> str:
    """Thousands-separated credit count."""
    return "{:,}".format(max(0, _coerce_int(value)))


def format_balance_label(snapshot: UsageSnapshot) -> str:
    """The card's headline, e.g. ``"6,800 credits"``."""
    count = max(0, snapshot.credits_remaining)
    if count == 1:
        return iface_("{count} credit").format(count=format_credits(count))
    return iface_("{count} credits").format(count=format_credits(count))


def format_breakdown_label(snapshot: UsageSnapshot) -> str:
    """Where the balance comes from, e.g. ``"4,800 monthly · 2,000 bonus"``.

    Empty unless a monthly allowance AND bonus credits both make up the
    balance — otherwise the headline already says everything. Same rule
    as the web dashboard's credit card.
    """
    if not snapshot.has_allowance or snapshot.bonus_remaining <= 0:
        return ""
    return iface_("{monthly} monthly · {bonus} bonus").format(
        monthly=format_credits(snapshot.monthly_remaining),
        bonus=format_credits(snapshot.bonus_remaining),
    )


def format_cycle_label(snapshot: UsageSnapshot) -> str:
    """Plan + cycle line for the popover header."""
    name = snapshot.plan_name or snapshot.plan_slug or iface_("Subscription")
    days = snapshot.days_left
    if days <= 0:
        return name
    if snapshot.is_cancelling:
        if days == 1:
            return iface_("{plan} · Expires in {count} day").format(plan=name, count=days)
        return iface_("{plan} · Expires in {count} days").format(plan=name, count=days)
    if days == 1:
        return iface_("{plan} · {count} day left in cycle").format(plan=name, count=days)
    return iface_("{plan} · {count} days left in cycle").format(plan=name, count=days)


def build_snapshot_dict(snapshot: Optional[UsageSnapshot] = None) -> Dict[str, Any]:
    """Flat dict of the display-ready values, for tests and diagnostics."""
    snap = snapshot if snapshot is not None else get_snapshot()
    return {
        "has_subscription": snap.has_subscription,
        "plan_name": snap.plan_name,
        "label": format_balance_label(snap),
        "breakdown": format_breakdown_label(snap),
        "cycle": format_cycle_label(snap),
        "credits_remaining": snap.credits_remaining,
        "monthly_remaining": snap.monthly_remaining,
        "bonus_remaining": snap.bonus_remaining,
        "can_top_up": snap.can_top_up,
        "error": snap.error,
    }
