# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Background refresher for the account card's usage figures.

Follows the house handler pattern: a light repeating ``bpy.app.timers``
tick decides *whether* to fetch, a daemon thread does the HTTP call and
touches no ``bpy``, and the result is written back through a one-shot
timer on the main thread. The draw path never triggers work — it only
reads :mod:`.state`.

Refresh triggers, in order of how much they matter:

* the TTL tick (the meter must not go stale while the app sits open),
* login (a fresh account must not inherit the previous user's figures),
* each terminal queue job (generations are what actually spend credits,
  so overlapping jobs must not leave the meter stale until drain),
* queue drain (a second chance, including all-failed batches).
"""

from __future__ import annotations

import threading
import time
from typing import Optional

import bpy

from mixar.config.logging_config import get_logger

from ..constants import (
    USAGE_INITIAL_DELAY_SECONDS,
    USAGE_MIN_FETCH_GAP_SECONDS,
    USAGE_REQUEST_TIMEOUT_SECONDS,
)
from . import account, state

logger = get_logger(__name__)

#: How often the supervising timer wakes to re-evaluate staleness. Cheap
#: relative to the TTL, so a login-triggered refresh lands promptly.
_TICK_SECONDS = 5.0

_timer_registered = False
_fetch_in_flight = False
_last_fetch_started = 0.0
_force_next = False
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Redraw
# ---------------------------------------------------------------------------


def _tag_topbar_redraw() -> None:
    """Repaint the top bar so an open account card picks up new figures.

    The top bar lives in ``Window.global_areas``, not ``screen.areas`` —
    tagging only the latter leaves a card that is open during a refresh
    showing the previous numbers until the pointer moves.
    """
    try:
        for window in bpy.context.window_manager.windows:
            for area in getattr(window, "global_areas", []) or []:
                if area.type in {'TOPBAR', 'STATUSBAR'}:
                    area.tag_redraw()
            screen = getattr(window, "screen", None)
            if screen is None:
                continue
            for area in screen.areas:
                if area.type == 'TOPBAR':
                    area.tag_redraw()
    except Exception as exc:  # noqa: BLE001 — redraw is best-effort
        logger.debug("usage meter: redraw tag failed: %s", exc)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def _mirror_to_rna(snapshot: state.UsageSnapshot) -> None:
    """Project the snapshot onto WindowManager properties.

    The profile card is drawn in C++ and cannot reach this module's
    cache, so RNA is the only channel. Main thread only.
    """
    try:
        wm = bpy.context.window_manager
    except Exception:  # noqa: BLE001 — no window manager during shutdown
        return

    try:
        wm.mixar_usage_ready = snapshot.fetched_at > 0.0
        wm.mixar_usage_has_subscription = snapshot.has_subscription
        wm.mixar_usage_plan_name = snapshot.plan_name
        wm.mixar_usage_remaining_pct = snapshot.remaining_pct
        wm.mixar_usage_credits_remaining = snapshot.credits_remaining
        wm.mixar_usage_credits_total = snapshot.credits_total
        wm.mixar_usage_can_top_up = snapshot.can_top_up
        wm.mixar_usage_stale = bool(snapshot.error)
    except AttributeError:
        # Properties not registered yet (UI auto-discovery is time-budgeted
        # and can lag the first fetch); the next refresh mirrors them.
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("usage meter: RNA mirror failed: %s", exc)


def _apply_snapshot(snapshot: state.UsageSnapshot) -> None:
    """Main-thread write-back. Registered as a one-shot timer."""
    state.set_snapshot(snapshot)
    _mirror_to_rna(snapshot)
    _tag_topbar_redraw()


def _schedule_apply(snapshot: state.UsageSnapshot) -> None:
    """Hand a snapshot from the worker thread to the main thread."""

    def _run() -> None:
        _apply_snapshot(snapshot)
        return None

    try:
        bpy.app.timers.register(_run, first_interval=0.0)
    except Exception as exc:  # noqa: BLE001 — shutdown race
        logger.debug("usage meter: apply scheduling failed: %s", exc)


def _fetch_worker() -> None:
    """Daemon-thread body: one status fetch, no ``bpy`` access."""
    global _fetch_in_flight

    try:
        from mixar.modules.common.api.services import get_subscription_service

        response = get_subscription_service().get_status(
            timeout=USAGE_REQUEST_TIMEOUT_SECONDS
        )

        if response.status_code == 404:
            # Free tier / no subscription payment on record. A normal
            # account state — surface it as such, not as an error.
            snapshot = state.snapshot_free_tier()
        elif response.success:
            snapshot = state.snapshot_from_payload(response.data)
        else:
            snapshot = state.snapshot_error(
                response.message or "HTTP %s" % response.status_code
            )
    except Exception as exc:  # noqa: BLE001 — offline / auth / parse
        snapshot = state.snapshot_error(str(exc))
        logger.debug("usage meter: fetch failed: %s", exc)

    _schedule_apply(snapshot)

    with _lock:
        _fetch_in_flight = False


def _start_fetch() -> None:
    """Kick the worker thread if one is not already running."""
    global _fetch_in_flight, _last_fetch_started, _force_next

    with _lock:
        if _fetch_in_flight:
            return
        _fetch_in_flight = True
        _last_fetch_started = time.monotonic()
        _force_next = False

    thread = threading.Thread(
        target=_fetch_worker, name="mixar-usage-meter", daemon=True
    )
    thread.start()


# ---------------------------------------------------------------------------
# Timer
# ---------------------------------------------------------------------------


def _is_logged_in() -> bool:
    try:
        return bool(
            getattr(bpy.context.window_manager, "mixie_chat_is_logged_in", False)
        )
    except Exception:  # noqa: BLE001 — no window manager yet
        return False


def _should_fetch() -> bool:
    """Whether this tick warrants a network call."""
    with _lock:
        if _fetch_in_flight:
            return False
        forced = _force_next
        since_last = time.monotonic() - _last_fetch_started

    if _last_fetch_started > 0.0 and since_last < USAGE_MIN_FETCH_GAP_SECONDS:
        # Rate floor applies to forced refreshes too — a burst of finished
        # jobs must not become a burst of status calls.
        return False

    return forced or state.is_stale()


def _tick() -> Optional[float]:
    """Repeating timer body. Returns the next interval, never None so the
    timer survives a logged-out stretch and resumes after login."""
    try:
        if not _is_logged_in():
            # Logged out: make sure a previous user's figures are gone —
            # from the cache, from RNA, and from the greeting.
            if state.get_snapshot() is not state.EMPTY:
                state.clear()
                _mirror_to_rna(state.EMPTY)
                account.clear()
                _tag_topbar_redraw()
            return _TICK_SECONDS

        if _should_fetch():
            _start_fetch()
    except Exception as exc:  # noqa: BLE001 — a timer must never die
        logger.debug("usage meter: tick failed: %s", exc)

    return _TICK_SECONDS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def request_refresh(force: bool = True) -> None:
    """Ask for a refresh on the next tick.

    Safe to call from any thread and from operator/notification callbacks.
    ``force`` bypasses the TTL but never the rate floor.
    """
    global _force_next
    with _lock:
        _force_next = _force_next or force


def on_logout() -> None:
    """Drop the cached figures so the card blanks immediately."""
    state.clear()
    _mirror_to_rna(state.EMPTY)
    account.clear()
    _tag_topbar_redraw()


def start() -> None:
    """Register the supervising timer (idempotent)."""
    global _timer_registered
    if _timer_registered:
        return
    try:
        bpy.app.timers.register(
            _tick,
            first_interval=USAGE_INITIAL_DELAY_SECONDS,
            persistent=True,
        )
        _timer_registered = True
        logger.info("Usage meter poller started")
    except Exception as exc:  # noqa: BLE001
        logger.warning("usage meter: timer registration failed: %s", exc)


def stop() -> None:
    """Unregister the supervising timer (idempotent)."""
    global _timer_registered
    try:
        if bpy.app.timers.is_registered(_tick):
            bpy.app.timers.unregister(_tick)
    except Exception:  # noqa: BLE001 — already gone
        pass
    _timer_registered = False
