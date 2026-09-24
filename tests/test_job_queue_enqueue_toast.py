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
  * each feature's batch raises its own transient "<Feature> complete"
    toast the moment ITS jobs finish — the notification that replaced the
    "<Feature> batch complete" popup menu — and draining the queue dismisses
    the sticky toast. An all-failed batch raises no completion toast
    (failures self-toast already).

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
    QUEUE_DONE_TOAST_ID_PREFIX,
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


def _job(label="ImageGen: a hero", service=""):
    return _InertJob(label=label, service=service)


def _done_toasts(store):
    """Completion toasts, newest first."""
    return [
        i for i in store.get_visible()
        if i.id.startswith(QUEUE_DONE_TOAST_ID_PREFIX)
    ]


def _catalog(monkeypatch, labels):
    """Resolve feature labels from ``service`` the way the catalog would."""
    monkeypatch.setattr(
        QM_LABELS, "catalog_feature_label",
        lambda cap, svc: labels.get(svc, ""),
    )


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
# Completion phase
# ---------------------------------------------------------------------------


def test_drain_dismisses_sticky_and_raises_feature_completion(monkeypatch):
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])
    _catalog(monkeypatch, {"image_to_3d": "Image to 3D"})

    jobs = [_job(f"job-{n}", service="image_to_3d") for n in range(4)]
    for job in jobs:
        queue.submit(job)
    for job in jobs:
        job.state = JobState.SUCCESS
    queue._notify()

    assert _toast(store) is None  # the sticky in-progress toast is gone
    [item] = _done_toasts(store)
    assert item.title == "Image to 3D complete"
    assert item.body == "4 succeeded"
    assert item.type.value == "success"
    assert item.ttl_ms == QUEUE_READY_TOAST_TTL_MS
    assert not item.is_sticky
    assert item.actions[0].operator == "mixie.queue_view"


def test_each_feature_reports_when_its_own_jobs_finish(monkeypatch):
    """The screenshot case: Image to 3D finishes while Auto Rig still runs."""
    a, b = _queue("feat_a"), _queue("feat_b")
    store = _setup(monkeypatch, queues=[a, b])
    _catalog(monkeypatch, {"image_to_3d": "Image to 3D", "auto_rig": "Auto Rig"})

    models = [_job(f"model-{n}", service="image_to_3d") for n in range(4)]
    rig = _job("rig-0", service="auto_rig")
    for job in models:
        a.submit(job)
    b.submit(rig)

    for job in models:
        job.state = JobState.SUCCESS
    a._notify()

    [done] = _done_toasts(store)
    assert (done.title, done.body) == ("Image to 3D complete", "4 succeeded")
    assert _toast(store).title == "Generation in progress"  # rig still runs

    rig.state = JobState.SUCCESS
    b._notify()

    titles = [(i.title, i.body) for i in _done_toasts(store)]
    assert titles == [
        ("Auto Rig complete", "1 succeeded"),
        ("Image to 3D complete", "4 succeeded"),
    ]
    assert _toast(store) is None


def test_completion_reports_failed_and_cancelled_counts(monkeypatch):
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])
    _catalog(monkeypatch, {"image_to_3d": "Image to 3D"})

    ok, bad, stopped = (_job(n, service="image_to_3d") for n in "abc")
    for job in (ok, bad, stopped):
        queue.submit(job)

    ok.state = JobState.SUCCESS
    bad.state = JobState.FAILED
    stopped.state = JobState.CANCELLED
    queue._notify()

    [item] = _done_toasts(store)
    assert item.body == "1 succeeded, 1 failed, 1 cancelled"


def test_catalog_miss_falls_back_to_generic_wording(monkeypatch):
    """A raw key like ``mesh_segment`` in a title reads as a bug."""
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])
    _catalog(monkeypatch, {})

    first, second = _job("job-a"), _job("job-b")
    queue.submit(first)
    queue.submit(second)
    first.state = second.state = JobState.SUCCESS
    queue._notify()

    [item] = _done_toasts(store)
    assert (item.title, item.body) == ("2 generations ready", "2 succeeded")


def test_all_failed_batch_raises_no_completion_toast(monkeypatch):
    """Each failure already raised its own toast — don't double-report."""
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])

    job = _job("job-a")
    queue.submit(job)
    job.state = JobState.FAILED
    queue._notify()

    assert _toast(store) is None
    assert _done_toasts(store) == []
    failure = [i for i in store.get_visible() if i.type.value == "error"]
    assert len(failure) == 1


def test_completion_fires_once_then_stays_quiet(monkeypatch):
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])

    job = _job("job-a")
    queue.submit(job)
    job.state = JobState.SUCCESS
    queue._notify()
    assert _done_toasts(store)[0].title == "Generation ready"

    store.clear_all()
    queue._notify()
    assert _done_toasts(store) == []
    assert _toast(store) is None


def test_next_batch_of_a_feature_replaces_its_completion_toast(monkeypatch):
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])
    _catalog(monkeypatch, {"image_to_3d": "Image to 3D"})

    first = _job("job-a", service="image_to_3d")
    queue.submit(first)
    first.state = JobState.SUCCESS
    queue._notify()

    second, third = (_job(n, service="image_to_3d") for n in ("job-b", "job-c"))
    queue.submit(second)
    queue.submit(third)
    second.state = third.state = JobState.SUCCESS
    queue._notify()

    [item] = _done_toasts(store)
    assert item.body == "2 succeeded"  # a fresh count, not 3


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


def test_dismissed_sticky_still_gets_its_completion(monkeypatch):
    """Closing the progress toast is not a request to miss the outcome."""
    queue = _queue()
    store = _setup(monkeypatch, queues=[queue])

    job = _job("job-a")
    queue.submit(job)
    store.dismiss(QUEUE_TOAST_ID)
    queue._notify()

    job.state = JobState.SUCCESS
    queue._notify()
    assert _done_toasts(store)[0].title == "Generation ready"


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


def test_queue_view_without_area_opens_island(monkeypatch):
    context = SimpleNamespace(area=None)
    seen = []
    monkeypatch.setattr(QO, '_show_island_queue_tab', lambda ctx: seen.append(ctx) or True)
    result = QO.MIXIE_OT_queue_view.execute(SimpleNamespace(), context)
    assert result == {'FINISHED'}
    assert seen == [context]


def test_queue_view_reports_unavailable_island_without_touching_sidebar(monkeypatch):
    region = SimpleNamespace(active_panel_category='')
    space = SimpleNamespace(show_region_ui=False)
    context = SimpleNamespace(area=SimpleNamespace(
        type='MIXIE', regions=[region], spaces=SimpleNamespace(active=space)))
    reports = []
    monkeypatch.setattr(QO, '_show_island_queue_tab', lambda ctx: False)
    operator = SimpleNamespace(report=lambda severity, text: reports.append((severity, text)))
    assert QO.MIXIE_OT_queue_view.execute(operator, context) == {'CANCELLED'}
    assert reports == [({'WARNING'}, 'The Agent island Queue is unavailable')]
    assert region.active_panel_category == ''
    assert not space.show_region_ui
