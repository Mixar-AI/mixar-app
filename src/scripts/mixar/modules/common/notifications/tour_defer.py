# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Toast deferral while the interactive onboarding tour runs.

A toast landing over the tour's video card or its spotlight steals the
beat, so ``NotificationStore.push`` parks new items here instead of
showing them. A 1 s poll (``bpy.app.timers``) flushes them the moment
the tour stops; ``flush_deferred()`` is also callable directly. Deferred
items re-enter the store with a fresh ``created_at`` so their TTL starts
when they are actually shown, not when they were pushed.

Thread-safe: ``push`` may run on the WebSocket thread, and timer
registration is the same main-thread hand-off ``toast_timer`` uses.
"""

import threading
from typing import List

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.utils.tour import tour_running

logger = get_logger(__name__)

FLUSH_POLL_S = 1.0

_lock = threading.Lock()
_deferred: List = []


def defer(item) -> None:
    """Park ``item`` until the tour stops (dedupes by id like the store)."""
    with _lock:
        _deferred[:] = [i for i in _deferred if i.id != item.id]
        _deferred.append(item)
    logger.info("notifications: toast %r deferred until the tour ends", item.title)
    try:
        bpy.app.timers.register(_ensure_poll_on_main, first_interval=0)
    except Exception as exc:  # noqa: BLE001 — timers unavailable at shutdown
        logger.debug("notifications: deferral poll not scheduled: %s", exc)


def deferred_count() -> int:
    with _lock:
        return len(_deferred)


def is_deferred(nid: str) -> bool:
    """True when a toast with this id is parked (still owed a showing)."""
    with _lock:
        return any(i.id == nid for i in _deferred)


def drop(nid: str):
    """Discard a parked toast so it is never shown. Returns the dropped
    item, or ``None`` when nothing with that id was parked."""
    with _lock:
        for idx, item in enumerate(_deferred):
            if item.id == nid:
                return _deferred.pop(idx)
    return None


def flush_deferred() -> int:
    """Move every parked toast into the live store. Returns the count."""
    from .store import get_notification_store

    with _lock:
        items = list(_deferred)
        _deferred.clear()
    if not items:
        return 0
    store = get_notification_store()
    for item in items:
        store.admit(item)
    logger.info("notifications: %d deferred toast(s) shown", len(items))
    return len(items)


def _ensure_poll_on_main() -> None:
    try:
        if not bpy.app.timers.is_registered(_flush_tick):
            bpy.app.timers.register(_flush_tick, first_interval=FLUSH_POLL_S)
    except Exception as exc:  # noqa: BLE001
        logger.debug("notifications: deferral poll registration failed: %s", exc)
    return None


def _flush_tick():
    """Main-thread poll: keep waiting while the tour runs, then flush."""
    try:
        if tour_running():
            return FLUSH_POLL_S
        flush_deferred()
    except Exception as exc:  # noqa: BLE001 — a timer must never raise
        logger.warning("notifications: deferred flush failed: %s", exc)
    return None


def reset() -> None:
    """Drop parked toasts (store reset / tests)."""
    with _lock:
        _deferred.clear()
