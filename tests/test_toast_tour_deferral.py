# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Toasts pushed while the interactive onboarding tour runs are parked
(``notifications.tour_defer``) and shown, with a fresh TTL, once it stops."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock  # noqa: E402

install_bpy_mock()

from mixar.modules.common.notifications import tour_defer  # noqa: E402
from mixar.modules.common.notifications.store import get_notification_store  # noqa: E402


def _ids(store):
    return {i.id for i in store.get_visible()}


def test_push_during_tour_is_parked_then_flushed(monkeypatch):
    store = get_notification_store()
    store.reset()
    monkeypatch.setattr(tour_defer, "tour_running", lambda: True)
    nid = store.push("info", "Later", id="t1", ttl_ms=5000)
    assert nid == "t1"
    assert "t1" not in _ids(store)
    assert tour_defer.deferred_count() == 1
    # Re-pushing the same id while parked dedupes, like the live store.
    store.push("info", "Later again", id="t1", ttl_ms=5000)
    assert tour_defer.deferred_count() == 1

    monkeypatch.setattr(tour_defer, "tour_running", lambda: False)
    assert tour_defer._flush_tick() is None
    assert tour_defer.deferred_count() == 0
    item = next(i for i in store.get_visible() if i.id == "t1")
    assert item.title == "Later again"
    assert item.age_ms < 1000          # TTL restarted at flush time


def test_flush_tick_keeps_polling_while_tour_runs(monkeypatch):
    store = get_notification_store()
    store.reset()
    monkeypatch.setattr(tour_defer, "tour_running", lambda: True)
    store.push("info", "Parked", id="t2")
    assert tour_defer._flush_tick() == tour_defer.FLUSH_POLL_S
    assert tour_defer.deferred_count() == 1
    store.reset()
    assert tour_defer.deferred_count() == 0


def test_push_outside_tour_is_unchanged(monkeypatch):
    store = get_notification_store()
    store.reset()
    monkeypatch.setattr(tour_defer, "tour_running", lambda: False)
    store.push("info", "Now", id="t3")
    assert "t3" in _ids(store) and tour_defer.deferred_count() == 0


def test_parked_toast_is_held_and_dismissable(monkeypatch):
    """A toast parked by the tour still counts as held (not user-dismissed),
    and dismissing it drops the parked copy so it never shows later."""
    store = get_notification_store()
    store.reset()
    monkeypatch.setattr(tour_defer, "tour_running", lambda: True)
    store.push("info", "Queued", id="t4", ttl_ms=0)
    assert store.contains("t4")
    assert store.dismiss("t4") is None
    assert not store.contains("t4")
    assert tour_defer.deferred_count() == 0

    monkeypatch.setattr(tour_defer, "tour_running", lambda: False)
    tour_defer.flush_deferred()
    assert "t4" not in _ids(store)


def test_dismiss_returns_parked_server_id(monkeypatch):
    store = get_notification_store()
    store.reset()
    monkeypatch.setattr(tour_defer, "tour_running", lambda: True)
    store.push_from_server({"id": 42, "title": "Hello"})
    assert store.dismiss("42") == "42"
    assert tour_defer.deferred_count() == 0
