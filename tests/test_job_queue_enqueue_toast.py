# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Queue-activity toast — sticky while work is outstanding, summary on drain.

The contract these pin, in order of why they exist:

  * the in-progress toast is STICKY. An auto-fading confirmation was the
    original bug: the agent enqueues, goes IDLE, and nothing on screen says
    a paid multi-minute job is still running.
  * its count is DERIVED from live queue snapshots, so it follows jobs
    completing and failing, not just arriving.
  * it is not re-pushed when nothing changed (``_notify`` fires twice a
    second during downloads).
  * a user dismissal is respected until the next enqueue.
  * draining the queue replaces it with a transient completion summary, and
    an all-failed batch dismisses instead (failures self-toast already).

Also covers the toast's "View Queue" action working without area context
(toast buttons fire from a bpy.app.timers callback where context.area is
None).
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
    QUEUE_ACTIVE_TOAST_TTL_MS,
    QUEUE_READY_TOAST_TTL_MS,
    QUEUE_TOAST_ID,
)
from mixar.modules.common.job_queue.core import enqueue_toast as ET
from mixar.modules.common.job_queue.core import labels as QM_LABELS
from mixar.modules.common.job_queue.core import queue_manager as QM
from mixar.modules.common.job_queue.core.job import Job, JobState
from mixar.modules.common.job_queue.ui.operators import queue_ops as QO
from mixar.modules.common.notifications.store import get_notification_store


class _InertJob(Job):
    """Job whose submit never resolves — stays PENDING, starts no timers."""

    def submit(self, on_success, on_error):
        pass


def _setup(monkeypatch, *, queues=()):
    """Isolate toast + queue state; ``queues`` become the only live queues."""
    ET.reset_state()
    store = get_notification_store()
    store.clear_all()
    monkeypatch.setattr(QM, "_queues", {q.feature_key: q for q in queues})
    return store


def _queue(name="test_queue_toast"):
    return QM.FeatureQueue(name)


def _toast(store):
    items = [i for i in store.get_visible() if i.id == QUEUE_TOAST_ID]
    assert len(items) <= 1
    return items[0] if items else None


def _job(label="ImageGen: a hero"):
    return _InertJob(label=label)


# ---------------------------------------------------------------------------
# In-progress phase
# ---------------------------------------------------------------------------


def test_single_enqueue_shows_sticky_toast(monkeypatch):
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])

    assert queue.submit(_job()) is True

    item = _toast(store)
    assert item is not None
    assert item.title == "Generation in progress"
    assert item.body == "ImageGen: a hero"
    assert item.ttl_ms == QUEUE_ACTIVE_TOAST_TTL_MS
    assert item.is_sticky
    action = item.actions[0]
    assert (action.label, action.operator, action.style) == (
        "View Queue", "mixie.queue_view", "primary",
    )


def test_display_label_preferred_over_raw_label(monkeypatch):
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])

    job = _job("ImageGen: a hero [3f2a]")
    job.display_label = "ImageGen: a hero"
    queue.submit(job)

    assert _toast(store).body == "ImageGen: a hero"


def test_count_aggregates_across_queues(monkeypatch):
    a, b = _queue("feat_a"), _queue("feat_b")
    store = _setup(monkeypatch, queues=[a, b])

    a.submit(_job("Retopo: mesh_0"))
    b.submit(_job("Model: part_0"))

    assert _toast(store).title == "2 generations in progress"


def test_duplicate_submit_does_not_inflate_count(monkeypatch):
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])

    assert queue.submit(_job("job-a")) is True
    assert queue.submit(_job("job-a")) is False  # same label, still active
    assert _toast(store).title == "Generation in progress"

    assert queue.submit(_job("job-b")) is True
    assert _toast(store).title == "2 generations in progress"


def test_count_derives_from_live_state_not_a_running_total(monkeypatch):
    """A finished job leaves the count — a burst counter got this wrong."""
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])

    first, second = _job("job-a"), _job("job-b")
    queue.submit(first)
    queue.submit(second)
    assert _toast(store).title == "2 generations in progress"

    first.state = JobState.SUCCESS
    queue._notify()
    assert _toast(store).title == "Generation in progress"


def test_unchanged_state_does_not_republish(monkeypatch):
    """_notify fires on every 0.5s download tick; a re-push resets the item."""
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])

    queue.submit(_job())
    first = _toast(store)
    queue._notify()
    queue._notify()

    assert _toast(store) is first


def test_dismissal_respected_until_next_enqueue(monkeypatch):
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])

    queue.submit(_job("job-a"))
    store.dismiss(QUEUE_TOAST_ID)

    queue._notify()
    assert _toast(store) is None  # a sticky toast can only be gone if closed

    queue.submit(_job("job-b"))
    assert _toast(store).title == "2 generations in progress"


# ---------------------------------------------------------------------------
# Drain phase
# ---------------------------------------------------------------------------


def test_drain_replaces_sticky_toast_with_transient_summary(monkeypatch):
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])

    first, second = _job("job-a"), _job("job-b")
    queue.submit(first)
    queue.submit(second)

    first.state = JobState.SUCCESS
    second.state = JobState.SUCCESS
    queue._notify()

    item = _toast(store)
    assert item.title == "2 generations ready"
    assert item.ttl_ms == QUEUE_READY_TOAST_TTL_MS
    assert not item.is_sticky
    assert item.actions[0].operator == "mixie.queue_view"


def test_summary_reports_partial_failure(monkeypatch):
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])

    ok, bad = _job("job-a"), _job("job-b")
    queue.submit(ok)
    queue.submit(bad)

    ok.state = JobState.SUCCESS
    bad.state = JobState.FAILED
    queue._notify()

    item = _toast(store)
    assert item.title == "Generation ready"
    assert item.body == "1 failed"


def test_all_failed_batch_dismisses_instead_of_summarising(monkeypatch):
    """Each failure already raised its own toast — don't double-report."""
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])

    job = _job("job-a")
    queue.submit(job)
    job.state = JobState.FAILED
    queue._notify()

    assert _toast(store) is None


def test_summary_fires_once_then_stays_quiet(monkeypatch):
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])

    job = _job("job-a")
    queue.submit(job)
    job.state = JobState.SUCCESS
    queue._notify()
    assert _toast(store).title == "Generation ready"

    store.clear_all()
    queue._notify()
    assert _toast(store) is None


def test_new_batch_after_drain_starts_a_fresh_count(monkeypatch):
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])

    first = _job("job-a")
    queue.submit(first)
    first.state = JobState.SUCCESS
    queue._notify()

    queue.submit(_job("job-b"))
    item = _toast(store)
    assert item.title == "Generation in progress"
    assert item.body == "job-b"


def test_terminal_job_requests_usage_refresh_before_drain(monkeypatch):
    """Overlapping jobs must refresh the meter as each one finishes."""
    calls = []
    monkeypatch.setattr(ET, "_request_usage_refresh", lambda: calls.append(1))
    a, b = _queue("feat_a"), _queue("feat_b")
    _setup(monkeypatch, queues=[a, b])

    first, second = _job("job-a"), _job("job-b")
    a.submit(first)
    b.submit(second)
    calls.clear()

    first.state = JobState.SUCCESS
    a._notify()
    assert calls == [1], "a finished job refreshes while siblings still run"

    a._notify()
    assert calls == [1], "the same terminal job must not refresh twice"

    second.state = JobState.FAILED
    b._notify()
    assert len(calls) >= 2, "the second terminal (and drain) refresh again"


# ---------------------------------------------------------------------------
# active_job_count — the pill reads this
# ---------------------------------------------------------------------------


def test_active_job_count_spans_queues_and_ignores_terminal(monkeypatch):
    a, b = _queue("feat_a"), _queue("feat_b")
    _setup(monkeypatch, queues=[a, b])

    done, running, pending = _job("job-a"), _job("job-b"), _job("job-c")
    a.submit(done)
    a.submit(running)
    b.submit(pending)

    done.state = JobState.SUCCESS
    running.state = JobState.RUNNING_POLL

    assert QM.active_job_count() == 2


def test_active_job_count_includes_paused_auth(monkeypatch):
    """PAUSED_AUTH is stalled work the user still has outstanding."""
    queue = _queue()
    _setup(monkeypatch, queues=[queue])

    job = _job("job-a")
    queue.submit(job)
    job.state = JobState.PAUSED_AUTH

    assert QM.active_job_count() == 1


def test_activity_names_the_job_only_when_there_is_exactly_one(monkeypatch):
    queue = _queue()
    _setup(monkeypatch, queues=[queue])
    monkeypatch.setattr(
        QM_LABELS, "catalog_feature_label", lambda cap, svc: "Image Gen",
    )

    queue.submit(_job("job-a"))
    assert QM.active_queue_activity().label == "Image Gen"

    # With two active, naming either one misrepresents the other.
    queue.submit(_job("job-b"))
    assert QM.active_queue_activity().label == ""


def test_activity_clock_starts_from_the_oldest_job(monkeypatch):
    """"How long has this been going" is a question about the oldest job."""
    queue = _queue()
    _setup(monkeypatch, queues=[queue])

    old, new = _job("job-a"), _job("job-b")
    old.created_at = 100.0
    new.created_at = 500.0
    queue.submit(old)
    queue.submit(new)

    assert QM.active_queue_activity().started_at == 100.0


def test_activity_is_empty_when_the_queue_is_idle(monkeypatch):
    queue = _queue()
    _setup(monkeypatch, queues=[queue])

    job = _job("job-a")
    queue.submit(job)
    job.state = JobState.SUCCESS

    assert QM.active_queue_activity() == (0, "", 0.0)


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
