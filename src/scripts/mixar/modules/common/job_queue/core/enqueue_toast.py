# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Viewport toasts that track unified-queue activity from enqueue to drain.

One sticky toast under one stable id, plus one completion toast per feature:

  * work outstanding    -> STICKY "N generations in progress" + View Queue
  * a feature finishes  -> transient "<Feature> complete" / "4 succeeded"
                           + View Queue, in the same bottom-left lane
  * queue drained       -> the sticky toast is dismissed
  * nothing succeeded   -> no completion toast (each failure toasted itself)

This used to be an 8 s auto-fading "generation queued" confirmation, which
covered the enqueue instant and nothing after it. The failure mode it left
behind is the reason this file exists: the agent enqueues a generation,
answers in chat, and drops to IDLE — so seconds later every surface in the
app says nothing is happening, while a multi-minute paid job is running. The
sticky phase keeps both the fact and the way to check it on screen for the
whole wait.

The per-feature completion toast replaces the "<Feature> batch complete"
popup menu that used to open over the viewport: the same facts (which
feature, how many succeeded / failed / were cancelled) now arrive as a
notification the moment THAT feature's jobs are done, even while another
feature is still running. A feature is its catalog capability label, so the
wording follows the backend catalog ("Image to 3D", "Auto Rig").

Counts are DERIVED from the live queue snapshots on every refresh, not
accumulated in a burst counter. That is what makes the number self-correcting
across the paths a counter got wrong: jobs enqueued minutes apart, jobs that
fail while others still run, and a queue cleared underneath the toast.

Re-push discipline: ``FeatureQueue._notify()`` fires on every state change
AND on the 0.5 s download-progress tick, so the sticky toast is only
re-pushed when its rendered text actually changes — a push replaces the
store item wholesale and would otherwise restart the renderer's fade
bookkeeping twice a second. A completion toast is pushed exactly once, when
its feature's last job leaves the active states.
"""

from ..constants import (
    QUEUE_ACTIVE_TOAST_TTL_MS,
    QUEUE_DONE_TOAST_ID_PREFIX,
    QUEUE_READY_TOAST_TTL_MS,
    QUEUE_TOAST_ID,
)

# Job id -> feature label for every job seen active since its feature last
# reported — the batches the completion toasts report on. Ids (not counts)
# because a job's outcome is only known later, and a batch must not
# double-count a job that _notify() visits many times. The label is resolved
# once, when the job is first seen, so a feature's jobs stay one group.
_batch: dict = {}

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


def reset_state() -> None:
    """Forget all toast state (tests / defensive re-init)."""
    global _batch, _latest_label, _last_key, _showing_active, _suppressed
    _batch = {}
    _latest_label = ""
    _last_key = ""
    _showing_active = False
    _suppressed = False


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


def _job_label(job) -> str:
    # display_label strips the agent-batch prefix + dedup hash the raw label
    # carries ("ImageGen: a hero [3f2a]") — same choice as the failure toast.
    return getattr(job, "display_label", "") or getattr(job, "label", "") or ""


def _feature_label(job) -> str:
    """Catalog capability label ("Image to 3D"), "" when it can't answer.

    Same lookup as the Agent Bubble pill (``active_queue_activity``): a raw
    key like ``mesh_segment`` in a toast title reads as a bug, so a catalog
    miss falls back to generic "Generation ready" wording instead.
    """
    from .labels import catalog_feature_label
    return catalog_feature_label(
        getattr(job, "origin_capability_key", ""),
        getattr(job, "service", "") or getattr(job, "job_type", ""),
    )


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
    """Recompute the toasts from live queue state. Safe to call often."""
    global _showing_active, _suppressed

    try:
        from .queue_manager import ACTIVE_JOB_STATES, all_queues
    except Exception:
        return

    jobs = {}
    active = 0
    for queue in all_queues():
        for job in queue.snapshot():
            jobs[job.id] = job
            if job.state in ACTIVE_JOB_STATES:
                active += 1
                if job.id not in _batch:
                    _batch[job.id] = _feature_label(job)

    finished = _finished_features(jobs, ACTIVE_JOB_STATES)
    if finished:
        _request_usage_refresh()
        for label, job_ids in finished.items():
            _push_feature_summary(label, [jobs.get(i) for i in job_ids])

    if active:
        # A sticky toast never expires, so if ours is gone the user closed it.
        if _showing_active and not _store().contains(QUEUE_TOAST_ID):
            _suppressed = True
            _showing_active = False
        if not _suppressed:
            _push_active(active)
        return

    if _last_key or _showing_active:
        _drain()


def _finished_features(jobs: dict, active_states) -> dict:
    """``{feature label: [job ids]}`` for batches with no job still active.

    Pops those jobs from the batch so each feature reports exactly once; a
    later job of the same feature starts a fresh batch. A job missing from
    every snapshot (its queue was cleared) counts as finished.
    """
    still_active = {
        label for job_id, label in _batch.items()
        if job_id in jobs and jobs[job_id].state in active_states
    }
    finished: dict = {}
    for job_id, label in list(_batch.items()):
        if label not in still_active:
            finished.setdefault(label, []).append(job_id)
            del _batch[job_id]
    return finished


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


def _drain() -> None:
    """Queue drained — the completion toasts carry the outcome now."""
    global _last_key, _latest_label, _showing_active, _suppressed

    _store().dismiss(QUEUE_TOAST_ID)
    _last_key = ""
    _latest_label = ""
    _showing_active = False
    # A dismissal applied to the in-progress toast, not to future work.
    _suppressed = False


def _request_usage_refresh() -> None:
    # Generations are what actually spend credits, so a finished batch is the
    # moment the top-bar meter is most likely to be wrong. Ask for a refresh
    # on every finish (including all-failed batches — a partial charge still
    # moves the balance); the poller's rate floor absorbs bursts.
    try:
        from mixar.modules.common.usage.core import poller as _usage_poller

        _usage_poller.request_refresh()
    except Exception:  # noqa: BLE001 — the toast must not depend on billing
        pass


def _outcome_text(succeeded: int, failed: int, cancelled: int) -> str:
    parts = [f"{succeeded} succeeded"]
    if failed:
        parts.append(f"{failed} failed")
    if cancelled:
        parts.append(f"{cancelled} cancelled")
    return ", ".join(parts)


def _push_feature_summary(label: str, batch: list) -> None:
    """One feature's batch finished — raise its completion toast."""
    from .job import JobState

    succeeded = failed = cancelled = 0
    for job in batch:
        if job is None:
            continue
        if job.state == JobState.SUCCESS:
            succeeded += 1
        elif job.state == JobState.CANCELLED:
            cancelled += 1
        elif job.state == JobState.FAILED:
            failed += 1

    if not succeeded:
        # Nothing to celebrate. Failures raised their own high-priority
        # toasts in _notify_failure_toasts(); repeating them here would
        # double-report, and cancellations are self-explanatory.
        return

    if label:
        title = f"{label} complete"
    else:
        title = (
            "Generation ready" if succeeded == 1
            else f"{succeeded} generations ready"
        )
    _store().push(
        "success",
        title,
        body=_outcome_text(succeeded, failed, cancelled),
        ttl_ms=QUEUE_READY_TOAST_TTL_MS,
        id=f"{QUEUE_DONE_TOAST_ID_PREFIX}{label}",
        actions=[_view_queue_action()],
    )
