# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Viewport toast that tracks unified-queue activity from enqueue to drain.

One toast, one stable id, three phases:

  * work outstanding  -> STICKY "N generations in progress" + View Queue
  * queue drained     -> transient "N generations ready" + View Queue
  * nothing succeeded -> dismissed (each failure already toasted itself)

This used to be an 8 s auto-fading "generation queued" confirmation, which
covered the enqueue instant and nothing after it. The failure mode it left
behind is the reason this file exists: the agent enqueues a generation,
answers in chat, and drops to IDLE — so seconds later every surface in the
app says nothing is happening, while a multi-minute paid job is running. The
sticky phase keeps both the fact and the way to check it on screen for the
whole wait.

Counts are DERIVED from the live queue snapshots on every refresh, not
accumulated in a burst counter. That is what makes the number self-correcting
across the paths a counter got wrong: jobs enqueued minutes apart, jobs that
fail while others still run, and a queue cleared underneath the toast.

Re-push discipline: ``FeatureQueue._notify()`` fires on every state change
AND on the 0.5 s download-progress tick, so the toast is only re-pushed when
its rendered text actually changes — a push replaces the store item wholesale
and would otherwise restart the renderer's fade bookkeeping twice a second.
"""

from ..constants import (
    QUEUE_ACTIVE_TOAST_TTL_MS,
    QUEUE_READY_TOAST_TTL_MS,
    QUEUE_TOAST_ID,
)

# Job ids seen active since the queue last drained — the batch the completion
# summary reports on. Ids (not counts) because a job's outcome is only known
# later, and the batch must not double-count a job that _notify() visits many
# times.
_batch_ids: set = set()

# Label of the most recently enqueued job, used as the toast body.
_latest_label = ""

# Rendered text of the last push, so an unchanged state is a no-op.
_last_key = ""

# True once the sticky toast has been pushed and not yet superseded.
_showing_active = False

# The user dismissed the sticky toast — stay silent until the next enqueue.
# A dismissal is not a request to never hear about this batch again, but it
# IS a request to stop re-showing the same toast; the next submit re-shows it
# (consistent with the previous burst behaviour).
_suppressed = False

# Terminal job ids whose success/failure already triggered a usage refresh.
# Overlapping jobs used to leave the account meter stale until the *whole*
# queue drained; refreshing on each newly-terminal id (behind the poller's
# rate floor) keeps the bar in step with spend.
_usage_refreshed_ids: set = set()


def reset_state() -> None:
    """Forget all toast state (tests / defensive re-init)."""
    global _batch_ids, _latest_label, _last_key, _showing_active, _suppressed
    global _usage_refreshed_ids
    _batch_ids = set()
    _latest_label = ""
    _last_key = ""
    _showing_active = False
    _suppressed = False
    _usage_refreshed_ids = set()


def _store():
    from mixar.modules.common.notifications.store import get_notification_store
    return get_notification_store()


def _view_queue_action():
    from mixar.modules.common.notifications.store import NotificationAction
    return NotificationAction(
        label="View Queue",
        operator="mixie.queue_view",
        style="primary",
    )


def _request_usage_refresh() -> None:
    """Ask the account-card poller to refetch. Fail-open: toast must not
    depend on billing."""
    try:
        from mixar.modules.common.usage.core import poller as _usage_poller

        _usage_poller.request_refresh()
    except Exception:  # noqa: BLE001
        pass


def _job_label(job) -> str:
    # display_label strips the agent-batch prefix + dedup hash the raw label
    # carries ("ImageGen: a hero [3f2a]") — same choice as the failure toast.
    return getattr(job, "display_label", "") or getattr(job, "label", "") or ""


def notify_job_enqueued(job) -> None:
    """Record an accepted submit and refresh the toast.

    Called from ``FeatureQueue.submit()`` after the job is appended, so the
    refresh below already counts it.
    """
    global _latest_label, _suppressed
    _latest_label = _job_label(job)
    # A new job is new information — undo an earlier dismissal.
    _suppressed = False
    refresh_from_queues()


def refresh_from_queues() -> None:
    """Recompute the toast from live queue state. Safe to call often."""
    global _showing_active, _suppressed

    try:
        from .job import TERMINAL_STATES
        from .queue_manager import ACTIVE_JOB_STATES, all_queues
    except Exception:
        return

    active = 0
    newly_terminal = []
    live_ids = set()
    for queue in all_queues():
        for job in queue.snapshot():
            live_ids.add(job.id)
            if job.state in ACTIVE_JOB_STATES:
                active += 1
                _batch_ids.add(job.id)
            elif job.state in TERMINAL_STATES and job.id not in _usage_refreshed_ids:
                newly_terminal.append(job.id)
    _usage_refreshed_ids.intersection_update(live_ids)
    if newly_terminal:
        _usage_refreshed_ids.update(newly_terminal)
        _request_usage_refresh()

    if active:
        # A sticky toast never expires, so if ours is gone the user closed it.
        if _showing_active and not _store().contains(QUEUE_TOAST_ID):
            _suppressed = True
            _showing_active = False
        if not _suppressed:
            _push_active(active)
        return

    if _batch_ids:
        _push_summary()


def _push_active(count: int) -> None:
    global _last_key, _showing_active

    title = (
        "Generation in progress"
        if count == 1
        else f"{count} generations in progress"
    )
    key = f"active\x1f{title}\x1f{_latest_label}"
    if key == _last_key and _showing_active:
        return
    _last_key = key
    _showing_active = True
    _store().push(
        "info",
        title,
        body=_latest_label,
        ttl_ms=QUEUE_ACTIVE_TOAST_TTL_MS,
        id=QUEUE_TOAST_ID,
        actions=[_view_queue_action()],
    )


def _push_summary() -> None:
    """Queue drained — replace the sticky toast with a completion summary."""
    global _batch_ids, _last_key, _latest_label, _showing_active, _suppressed

    from .job import JobState, TERMINAL_STATES
    from .queue_manager import all_queues

    # Drain is a second chance for the meter (including all-failed batches —
    # a partial charge still moves the balance). Per-job refreshes already
    # ran as each job went terminal; the poller's rate floor absorbs bursts.
    _request_usage_refresh()

    succeeded = 0
    failed = 0
    for queue in all_queues():
        for job in queue.snapshot():
            if job.id not in _batch_ids:
                continue
            if job.state == JobState.SUCCESS:
                succeeded += 1
            elif job.state in TERMINAL_STATES:
                failed += 1

    body = _latest_label
    _batch_ids = set()
    _latest_label = ""
    _last_key = ""
    _showing_active = False
    # A dismissal applied to the in-progress toast, not to the whole batch —
    # the completion summary is new information and clears the suppression.
    _suppressed = False

    if not succeeded:
        # Nothing to celebrate. Failures raised their own high-priority
        # toasts in _notify_failure_toasts(); repeating them here would
        # double-report, and cancellations are self-explanatory.
        _store().dismiss(QUEUE_TOAST_ID)
        return

    title = "Generation ready" if succeeded == 1 else f"{succeeded} generations ready"
    if failed:
        body = f"{failed} failed"
    _store().push(
        "success",
        title,
        body=body,
        ttl_ms=QUEUE_READY_TOAST_TTL_MS,
        id=QUEUE_TOAST_ID,
        actions=[_view_queue_action()],
    )
