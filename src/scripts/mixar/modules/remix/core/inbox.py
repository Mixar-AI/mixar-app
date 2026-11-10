# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Remixes started on the web, waiting for this app to pick them up.

A web page can launch or focus Mixar with a ``mixar://`` link but cannot
hand it a payload, so the store keeps the request under the signed-in user
and the app asks for it: a few seconds after start, every 10 s for the
first three minutes, then once a minute. Each new one becomes a toast with
a Start remix button. The fetch runs on a worker thread (the token read
may touch the keychain); ``Inbox`` itself is plain state under a lock.
"""

from __future__ import annotations

import threading
import time

from ..constants import POLL_FAST_S, POLL_FAST_WINDOW_S, POLL_SIGNED_OUT_S, POLL_SLOW_S


class Inbox:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._started = clock()
        self._items: list[dict] = []
        self._announced: set[str] = set()
        self._fetching = False
        self._signed_out = False

    def interval(self) -> float:
        if self._signed_out:
            return POLL_SIGNED_OUT_S  # nothing can be waiting for nobody
        return POLL_FAST_S if self._clock() - self._started < POLL_FAST_WINDOW_S else POLL_SLOW_S

    def note_signed_out(self, signed_out: bool) -> None:
        with self._lock:
            self._signed_out = bool(signed_out)

    def begin_fetch(self) -> bool:
        """False while a fetch is still out (never two at once)."""
        with self._lock:
            if self._fetching:
                return False
            self._fetching = True
            return True

    def end_fetch(self, items=None) -> list[dict]:
        """Store the store's answer; returns the ones not announced before.
        ``items=None`` (the fetch failed) keeps what was known."""
        with self._lock:
            self._fetching = False
            if items is None:
                return []
            self._items = [dict(item) for item in items if item.get("intent_id")]
            fresh = [item for item in self._items if item["intent_id"] not in self._announced]
            self._announced.update(item["intent_id"] for item in fresh)
            return fresh

    def newest(self) -> dict | None:
        with self._lock:
            return dict(self._items[0]) if self._items else None

    def take(self, intent_id: str) -> dict | None:
        """Remove and return a waiting remix (it is being started)."""
        with self._lock:
            for index, item in enumerate(self._items):
                if item["intent_id"] == intent_id:
                    return self._items.pop(index)
        return None

    def count(self) -> int:
        with self._lock:
            return len(self._items)


_inbox = Inbox()


def get_inbox() -> Inbox:
    return _inbox


def _announce(item: dict) -> None:
    from mixar.modules.common.i18n import n_, rpt_
    from mixar.modules.common.notifications import get_notification_store
    from mixar.modules.common.notifications.store import NotificationAction
    from . import lineage
    origin = lineage.clean_origin(item.get("origin")) or {}
    get_notification_store().push(
        "info", rpt_("Remix \"{title}\"?").format(title=origin.get("title") or ""),
        body=rpt_("You pressed Remix in Mixar on the web. Start it to open your own copy."),
        actions=[NotificationAction(label=n_("Start remix"), operator="mixar.remix_start",
                                    style="primary")],
        ttl_ms=120_000, id=f"remix-{item['intent_id']}")


def fetch_once(inbox: Inbox | None = None, client_factory=None, announce=None) -> list[dict]:
    """Worker thread: one round trip to the store. Never raises."""
    inbox = inbox or _inbox
    announce = announce or _announce_on_main
    if not inbox.begin_fetch():
        return []
    items = None
    try:
        if client_factory is None:
            from mixar.config.config import get_community_api_url
            from .client import RemixClient
            client = RemixClient(get_community_api_url())
        else:
            client = client_factory()
        items = client.pending()
        inbox.note_signed_out(False)
    except Exception as exc:  # noqa: BLE001 — signed out, offline, store down: try again later
        items = None
        inbox.note_signed_out(getattr(exc, "code", "") == "login_required")
    fresh = inbox.end_fetch(items)
    for item in fresh:
        try:
            announce(item)
        except Exception:  # noqa: BLE001 — a toast must never break the poll
            pass
    return fresh


def _announce_on_main(item: dict) -> None:
    """Toasts translate their text, which needs the main thread."""
    import bpy

    def show():
        _announce(item)
        return None

    bpy.app.timers.register(show, first_interval=0.0)


def tick() -> float:
    """``bpy.app.timers`` callback (main thread): start a fetch, reschedule."""
    threading.Thread(target=fetch_once, name="mixar-remix-inbox", daemon=True).start()
    return _inbox.interval()
