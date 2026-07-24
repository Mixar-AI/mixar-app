# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transient "generation queued" toast raised by FeatureQueue.submit().

Covers burst aggregation: jobs enqueued rapidly OR at ~1s intervals must
collapse into one counting toast (each re-push restarts the TTL), while a
gap longer than the toast lifetime starts a fresh burst. Also covers the
toast's "View Queue" action working without area context (toast buttons
fire from a bpy.app.timers callback where context.area is None).
"""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.job_queue.constants import (
    ENQUEUE_TOAST_ID,
    ENQUEUE_TOAST_TTL_MS,
)
from mixar.modules.common.job_queue.core import enqueue_toast as ET
from mixar.modules.common.job_queue.core import queue_manager as QM
from mixar.modules.common.job_queue.core.job import Job
from mixar.modules.common.job_queue.ui.operators import queue_ops as QO
from mixar.modules.common.notifications.store import get_notification_store


class _Clock:
    """Injectable monotonic clock for enqueue_toast."""

    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t


def _setup(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(ET, "time", clock)
    ET.reset_burst()
    store = get_notification_store()
    store.clear_all()
    return clock, store


def _toast(store):
    items = [i for i in store.get_visible() if i.id == ENQUEUE_TOAST_ID]
    assert len(items) <= 1
    return items[0] if items else None


def _job(label="ImageGen: a hero"):
    return Job(label=label)


def test_single_enqueue_shows_transient_toast(monkeypatch):
    _, store = _setup(monkeypatch)
    ET.notify_job_enqueued(_job())
    item = _toast(store)
    assert item is not None
    assert item.title == "Generation queued"
    assert item.body == "ImageGen: a hero"
    assert item.ttl_ms == ENQUEUE_TOAST_TTL_MS
    assert not item.is_sticky
    assert len(item.actions) == 1
    action = item.actions[0]
    assert action.label == "View Queue"
    assert action.operator == "mixie.queue_view"
    assert action.style == "primary"


def test_display_label_preferred_over_raw_label(monkeypatch):
    _, store = _setup(monkeypatch)
    job = _job("ImageGen: a hero [3f2a]")
    job.display_label = "ImageGen: a hero"
    ET.notify_job_enqueued(job)
    assert _toast(store).body == "ImageGen: a hero"


def test_rapid_burst_aggregates_into_one_counting_toast(monkeypatch):
    _, store = _setup(monkeypatch)
    for i in range(3):
        ET.notify_job_enqueued(_job(f"Retopo: mesh_{i}"))
    item = _toast(store)
    assert item.title == "3 generations queued"
    assert item.body == "Latest: Retopo: mesh_2"


def test_one_second_interval_burst_still_aggregates(monkeypatch):
    clock, store = _setup(monkeypatch)
    for i in range(5):
        ET.notify_job_enqueued(_job(f"Model: part_{i}"))
        clock.t += 1.0  # slower than "instant", faster than the TTL window
    item = _toast(store)
    assert item.title == "5 generations queued"


def test_gap_longer_than_ttl_starts_fresh_burst(monkeypatch):
    clock, store = _setup(monkeypatch)
    ET.notify_job_enqueued(_job("first"))
    ET.notify_job_enqueued(_job("second"))
    assert _toast(store).title == "2 generations queued"

    clock.t += (ENQUEUE_TOAST_TTL_MS / 1000.0) + 0.5
    ET.notify_job_enqueued(_job("third"))
    item = _toast(store)
    assert item.title == "Generation queued"
    assert item.body == "third"


def test_repush_restarts_toast_lifetime(monkeypatch):
    clock, store = _setup(monkeypatch)
    ET.notify_job_enqueued(_job("first"))
    first = _toast(store)
    clock.t += 3.0
    ET.notify_job_enqueued(_job("second"))
    second = _toast(store)
    # The store replaces the item wholesale, so created_at (and with it the
    # TTL countdown) restarts on every push within a burst.
    assert second is not first
    assert second.created_at >= first.created_at


class _InertJob(Job):
    """Job whose submit never resolves — stays non-terminal, no timers."""

    def submit(self, on_success, on_error):
        pass


def test_feature_queue_submit_raises_toast_once_per_accepted_job(monkeypatch):
    _, store = _setup(monkeypatch)
    queue = QM.FeatureQueue("test_enqueue_toast")

    assert queue.submit(_InertJob(label="job-a")) is True
    assert _toast(store).title == "Generation queued"

    # Duplicate (same label, still active) is rejected — no second count.
    assert queue.submit(_InertJob(label="job-a")) is False
    assert _toast(store).title == "Generation queued"

    assert queue.submit(_InertJob(label="job-b")) is True
    assert _toast(store).title == "2 generations queued"


# ---------------------------------------------------------------------------
# "View Queue" without area context
# ---------------------------------------------------------------------------


def _fake_area(area_type=None, width=100, height=100):
    # Default to the space type the Queue panel actually registers in
    # (MIXIE when the Mixar space exists, VIEW_3D otherwise).
    if area_type is None:
        area_type = QO.QUEUE_AREA_TYPE
    return SimpleNamespace(
        type=area_type,
        width=width,
        height=height,
        spaces=SimpleNamespace(active=SimpleNamespace(show_region_ui=False)),
        regions=[SimpleNamespace(type='UI', active_panel_category="")],
        tag_redraw=lambda: None,
    )


def _fake_context(area, windows):
    return SimpleNamespace(
        area=area,
        window_manager=SimpleNamespace(
            windows=[
                SimpleNamespace(screen=SimpleNamespace(areas=areas))
                for areas in windows
            ],
        ),
    )


def test_find_largest_queue_area_picks_biggest_of_right_type():
    small = _fake_area(width=10, height=10)
    big = _fake_area(width=200, height=100)
    other = _fake_area(area_type="OTHER_SPACE", width=500, height=500)
    ctx = _fake_context(None, [[small, other], [big]])
    assert QO.find_largest_queue_area(ctx) is big


def test_queue_view_falls_back_when_no_area_context():
    area = _fake_area()
    ctx = _fake_context(None, [[area]])
    result = QO.MIXIE_OT_queue_view.execute(SimpleNamespace(), ctx)
    assert result == {'FINISHED'}
    assert area.spaces.active.show_region_ui is True
    assert area.regions[0].active_panel_category == "Queue"


def test_queue_view_redirects_wrong_area_type_to_queue_area():
    # A toast clicked in a 3D viewport must not touch that viewport's
    # sidebar — the "Queue" category only exists in the queue area type.
    clicked = _fake_area(area_type="OTHER_SPACE")
    target = _fake_area()
    ctx = _fake_context(clicked, [[clicked, target]])
    result = QO.MIXIE_OT_queue_view.execute(SimpleNamespace(), ctx)
    assert result == {'FINISHED'}
    assert clicked.regions[0].active_panel_category == ""
    assert target.regions[0].active_panel_category == "Queue"


def test_queue_view_uses_context_area_when_already_right_type():
    area = _fake_area()
    bigger_elsewhere = _fake_area(width=999, height=999)
    ctx = _fake_context(area, [[area, bigger_elsewhere]])
    result = QO.MIXIE_OT_queue_view.execute(SimpleNamespace(), ctx)
    assert result == {'FINISHED'}
    assert area.regions[0].active_panel_category == "Queue"
    assert bigger_elsewhere.regions[0].active_panel_category == ""


def test_queue_view_cancels_when_no_queue_area_anywhere():
    ctx = _fake_context(None, [[]])
    result = QO.MIXIE_OT_queue_view.execute(SimpleNamespace(), ctx)
    assert result == {'CANCELLED'}
