# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cached subscription/usage snapshot backing the top-bar meter.

Deliberately free of ``bpy`` so the percentage and threshold logic can be
unit-tested outside Blender. The module-level cache lives here; the
:mod:`..core.poller` owns *when* it is refreshed and the UI layer only
ever reads it.

Percentages come from the backend's ``usage_pct`` (credits **used**) and
are never recomputed from the balance — the server already handles
grandfathered per-cycle allocations, trial allocations and clamping, and
a second client-side formula would drift from the web dashboard.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..constants import (
    SEVERITY_CRITICAL,
    SEVERITY_OK,
    SEVERITY_WARNING,
    TRIAL_SLUG_PREFIX,
    USAGE_CRITICAL_PCT,
    USAGE_TTL_SECONDS,
    USAGE_WARNING_PCT,
)


@dataclass(frozen=True)
class UsageSnapshot:
    """One reading of the user's billing cycle.

    ``has_subscription`` False covers both the free tier and a subscribed
    account with no successful subscription payment on record — the
    backend answers 404 for both, and neither has a quota to meter.
    """

    has_subscription: bool = False
    plan_slug: str = ""
    plan_name: str = ""
    #: Credits consumed this cycle, as a percentage of the allocation.
    usage_pct: float = 0.0
    credits_remaining: int = 0
    credits_total: int = 0
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
    def remaining_pct(self) -> float:
        """Percentage of the cycle allocation still available."""
        return max(0.0, min(100.0, 100.0 - self.usage_pct))

    @property
    def can_top_up(self) -> bool:
        """Whether "Buy credits" applies — mirrors the web dashboard's
        ``canTopUpCredits`` and the server rule behind ``/subscriptions
        /credit-topup``: subscribed, not on trial, not cancelling."""
        return self.has_subscription and not self.is_trial and not self.is_cancelling


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


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
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

    total = _coerce_int(data.get("credits_per_month"))
    balance = _coerce_int(data.get("balance_cents"))
    if credits_remaining is not None:
        balance = _coerce_int(credits_remaining, balance)

    return UsageSnapshot(
        has_subscription=True,
        plan_slug=str(data.get("plan_slug") or ""),
        plan_name=str(data.get("plan_name") or ""),
        usage_pct=max(0.0, min(100.0, _coerce_float(data.get("usage_pct")))),
        credits_remaining=max(0, balance),
        credits_total=max(0, total),
        days_left=max(0, _coerce_int(data.get("days_left"))),
        is_cancelling=bool(data.get("subscription_expires_at")),
        fetched_at=time.monotonic() if now is None else now,
    )


def snapshot_free_tier(
    credits_remaining: int = 0, now: Optional[float] = None
) -> UsageSnapshot:
    """Snapshot for the 404 ("No active subscription") case.

    A free account has no allocation, so there is no percentage to show —
    the UI switches to an upgrade affordance instead of a meter.
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
        usage_pct=previous.usage_pct,
        credits_remaining=previous.credits_remaining,
        credits_total=previous.credits_total,
        days_left=previous.days_left,
        is_cancelling=previous.is_cancelling,
        fetched_at=stamp,
        error=str(message or "Usage unavailable"),
    )


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def usage_severity(remaining_pct: float) -> str:
    """Severity band for a *remaining* percentage (not used)."""
    if remaining_pct < USAGE_CRITICAL_PCT:
        return SEVERITY_CRITICAL
    if remaining_pct < USAGE_WARNING_PCT:
        return SEVERITY_WARNING
    return SEVERITY_OK


def format_remaining_label(snapshot: UsageSnapshot) -> str:
    """Short label for the top-bar pill, e.g. ``"68% left"``.

    Rounds toward the user's disadvantage (floor) so a meter reading
    "1% left" is never actually 0 credits, and so a truly exhausted cycle
    reads "0% left" rather than rounding up to a reassuring "1%".
    """
    if not snapshot.has_subscription:
        return "Upgrade"
    return "%d%% left" % int(snapshot.remaining_pct)


def format_credits(value: int) -> str:
    """Thousands-separated credit count."""
    return "{:,}".format(max(0, _coerce_int(value)))


def format_cycle_label(snapshot: UsageSnapshot) -> str:
    """Plan + cycle line for the popover header."""
    name = snapshot.plan_name or snapshot.plan_slug or "Subscription"
    if snapshot.days_left <= 0:
        return name
    unit = "day" if snapshot.days_left == 1 else "days"
    if snapshot.is_cancelling:
        return "%s · Expires in %d %s" % (name, snapshot.days_left, unit)
    return "%s · %d %s left in cycle" % (name, snapshot.days_left, unit)


def usage_factor(snapshot: UsageSnapshot) -> float:
    """Fill fraction (0..1) for the bar widget — the portion REMAINING.

    The bar depletes as credits are spent, which is the opposite of the
    web dashboard's "% used" fill but the far more legible reading for a
    persistent meter: a full bar means plenty left.
    """
    if not snapshot.has_subscription:
        return 0.0
    return max(0.0, min(1.0, snapshot.remaining_pct / 100.0))


def build_snapshot_dict(snapshot: Optional[UsageSnapshot] = None) -> Dict[str, Any]:
    """Flat dict of the display-ready values, for tests and diagnostics."""
    snap = snapshot if snapshot is not None else get_snapshot()
    return {
        "has_subscription": snap.has_subscription,
        "plan_name": snap.plan_name,
        "remaining_pct": snap.remaining_pct,
        "severity": usage_severity(snap.remaining_pct),
        "factor": usage_factor(snap),
        "label": format_remaining_label(snap),
        "cycle": format_cycle_label(snap),
        "credits_remaining": snap.credits_remaining,
        "credits_total": snap.credits_total,
        "can_top_up": snap.can_top_up,
        "error": snap.error,
    }
