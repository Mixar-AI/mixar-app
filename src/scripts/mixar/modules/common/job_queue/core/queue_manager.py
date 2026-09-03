# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""FeatureQueue — per-feature singleton that drives the job lifecycle.

Lifecycle (per job, all callbacks fire on the main thread via api/processor):

    PENDING → RUNNING_SUBMIT → RUNNING_POLL → RUNNING_DOWNLOAD → SUCCESS
                       │              │               │
                       └──── FAILED / CANCELLED / PAUSED_AUTH

All pending jobs are submitted immediately (the backend handles concurrency
and queue limits). Once submitted, jobs wait for backend ``job.update`` pushes
over the agent WebSocket; terminal success reconciles full result data via
``job.sync`` on that same socket. Download runs on a daemon thread that
schedules the import callback back on the main thread — that half of the
lifecycle lives in ``queue_download.DownloadMixin``.
"""

import time
from typing import NamedTuple

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.exceptions import (
    AuthenticationError,
    ConnectionError as APIConnectionError,
    TimeoutError as APITimeoutError,
)
from .model_io import (
    get_poll_interval,
    redraw_3d_views,
)

from ..constants import (
    DOWNLOAD_WATCHDOG_DEADLINE_S,
    LOG_PREFIX,
    MAX_CONSECUTIVE_POLL_ERRORS,
    MAX_POLL_DURATION,
)
from .error_helpers import classify_error
from .job import FAILED_BACKEND_STATUSES, Job, JobState, RUNNING_STATES, TERMINAL_STATES
from .queue_download import DownloadMixin

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Singleton registry
# ---------------------------------------------------------------------------

_queues: dict = {}
# The queue is push-driven, so this interval IS the worst-case delay a
# completed job can sit invisible when its at-most-once ``job.update`` push
# is lost: at 30 s a finished image generation stared at the user for half a
# minute. One batched ``job.sync`` RPC every 5 s while at least one job is
# active is negligible traffic, and the timer unregisters itself once no job
# needs reconciling.
_SYNC_WATCHDOG_INTERVAL = 5.0
_sync_watchdog_registered = False
_BACKEND_SYNC_STATES = frozenset(
    {
        JobState.PENDING,
        JobState.RUNNING_SUBMIT,
        JobState.RUNNING_POLL,
        JobState.PAUSED_AUTH,
    }
)
# States that must keep the watchdog ticking. RUNNING_DOWNLOAD is here but
# NOT in _BACKEND_SYNC_STATES: there is nothing left to reconcile with the
# backend (the job is already DONE there), yet the watchdog is still the only
# recurring tick that can fail a download whose worker thread died. Without
# this the watchdog unregistered itself the instant a job began downloading.
_WATCHDOG_STATES = _BACKEND_SYNC_STATES | {JobState.RUNNING_DOWNLOAD}


def get_queue(feature_key: str) -> "FeatureQueue":
    """Return (creating if necessary) the FeatureQueue for ``feature_key``."""
    q = _queues.get(feature_key)
    if q is None:
        q = FeatureQueue(feature_key)
        _queues[feature_key] = q
    return q


def all_queues() -> list:
    return list(_queues.values())


# Every state that means "this job still has work to do". PAUSED_AUTH is in
# here on purpose — the job is stalled on a re-login, not finished, and the
# user still has something outstanding to know about.
ACTIVE_JOB_STATES = frozenset(
    RUNNING_STATES | {JobState.PENDING, JobState.PAUSED_AUTH}
)


class QueueActivity(NamedTuple):
    """What the queue is doing right now, for narrow status surfaces.

    ``label`` is only populated when EXACTLY ONE job is active — with two
    the name of either is misleading, and there is no room to list both.
    It is the catalog capability label ("Image Gen"), empty when the catalog
    cannot answer; a status pill should say "Generating" rather than show a
    raw key like ``mesh_segment``.
    """

    count: int
    label: str
    started_at: float  # oldest active job's monotonic created_at, 0.0 if idle


def active_queue_activity() -> QueueActivity:
    """Summarise unfinished work across EVERY feature queue.

    Read from the canonical FeatureQueue singletons rather than the
    ``wm.mixie_queue`` mirror: the mirror only reflects the features
    hand-listed in ``queue_properties._attach_listeners()``, so a queue
    missing from that tuple runs jobs that the mirror never sees.
    """
    active = [
        job
        for queue in all_queues()
        for job in queue.snapshot()
        if job.state in ACTIVE_JOB_STATES
    ]
    if not active:
        return QueueActivity(0, "", 0.0)

    # The OLDEST job's clock, not the newest: it answers "how long has this
    # been going", which is the question a stalled queue raises.
    started_at = min(getattr(job, "created_at", 0.0) for job in active)
    label = ""
    if len(active) == 1:
        from .labels import catalog_feature_label
        job = active[0]
        label = catalog_feature_label(
            getattr(job, "origin_capability_key", ""),
            getattr(job, "service", "") or getattr(job, "job_type", ""),
        )
    return QueueActivity(len(active), label, started_at)


def active_job_count() -> int:
    """Number of unfinished jobs across every feature queue."""
    return active_queue_activity().count


_JOBQ_STATE_TO_STATUS = {
    "pending": "PENDING",
    "dispatched": "SUBMITTED",
    "running": "POLLING",
    "succeeded": "DONE",
    "failed": "FAILED",
    "dlq": "DLQ",
    "cancelled": "CANCELLED",
}


def _find_by_backend_job_id(backend_job_id: str):
    for queue in all_queues():
        for job in queue.snapshot():
            if job.backend_job_id == backend_job_id:
                return queue, job
    return None, None


def handle_backend_job_update(payload: dict) -> bool:
    """Apply a compact ``job.update`` push to the matching local queue job."""
    if not isinstance(payload, dict):
        return False
    backend_job_id = payload.get("job_id") or payload.get("id")
    if not backend_job_id:
        return False
    queue, job = _find_by_backend_job_id(str(backend_job_id))
    if job is None:
        return False

    job.apply_backend_metadata(payload)
    state = str(payload.get("state") or payload.get("status") or "").lower()
    status = _JOBQ_STATE_TO_STATUS.get(state, "")
    if status:
        job.backend_status = status
        if status in {"SUBMITTED", "POLLING"}:
            if hasattr(job, "_processing_started") and not job._processing_started:
                job._processing_started = True
                job.poll_start_time = time.time()
    if payload.get("error"):
        job.error = str(payload.get("error"))
    queue._notify()

    if status in FAILED_BACKEND_STATUSES and job.state == JobState.RUNNING_POLL:
        _apply_backend_snapshot(queue, job, payload)
    elif status == "DONE" and job.state == JobState.RUNNING_POLL:
        _request_backend_job_get(str(backend_job_id))
    return True


def _apply_backend_snapshot(queue: "FeatureQueue", job: Job, snapshot: dict) -> None:
    """Feed a job-queue snapshot through the existing result parser."""
    from mixar.modules.common.api.response import APIResponse
    from mixar.modules.common.api.services.job_queue_service import (
        JobQueueService,
    )

    response = APIResponse(
        success=True,
        status_code=200,
        data={"status": "success", "message": "ok", "data": snapshot},
    )
    queue._on_poll_success(job, JobQueueService._normalize_response(response))


def handle_backend_job_sync(result: dict) -> int:
    """Apply full ``job.sync`` snapshots to local jobs after reconnect."""
    if not isinstance(result, dict):
        return 0
    jobs = result.get("jobs", [])
    if not isinstance(jobs, list):
        return 0

    handled = 0
    for snapshot in jobs:
        if not isinstance(snapshot, dict):
            continue
        backend_job_id = snapshot.get("job_id") or snapshot.get("id")
        if not backend_job_id:
            continue
        queue, job = _find_by_backend_job_id(str(backend_job_id))
        if job is None:
            continue
        _apply_backend_snapshot(queue, job, snapshot)
        handled += 1
    return handled


def _request_backend_job_sync() -> bool:
    """Ask the WebSocket transport for full job snapshots, without REST polling."""
    try:
        from mixar.modules.space_mixie_chat.constants import JSONRPCMethod
        from mixar.modules.space_mixie_chat.core.jsonrpc_client import (
            get_jsonrpc_client,
        )
        from mixar.modules.space_mixie_chat.core.main_thread_executor import (
            run_on_main_thread,
        )

        client = get_jsonrpc_client()
        if client is None or not client.is_connected:
            return False

        def _on_sync_result(result):
            def _apply_sync():
                count = handle_backend_job_sync(result)
                if count:
                    logger.info("job.sync reconciled %d local queue jobs", count)

            run_on_main_thread(_apply_sync)

        client.send_request(JSONRPCMethod.JOB_SYNC, {}, _on_sync_result)
        return True
    except Exception as e:
        logger.debug("%s job.sync request failed: %s", LOG_PREFIX, e)
        return False


def _request_backend_job_get(backend_job_id: str) -> bool:
    """Fetch one full job snapshot after a compact terminal ``job.update``."""
    try:
        from mixar.modules.space_mixie_chat.constants import JSONRPCMethod
        from mixar.modules.space_mixie_chat.core.jsonrpc_client import (
            get_jsonrpc_client,
        )
        from mixar.modules.space_mixie_chat.core.main_thread_executor import (
            run_on_main_thread,
        )

        client = get_jsonrpc_client()
        if client is None or not client.is_connected:
            return False

        def _on_get_result(result):
            def _apply_get():
                snapshot = result.get("job") if isinstance(result, dict) else None
                if not isinstance(snapshot, dict):
                    _request_backend_job_sync()
                    return
                queue, job = _find_by_backend_job_id(str(backend_job_id))
                if job is None:
                    return
                _apply_backend_snapshot(queue, job, snapshot)
                logger.info("job.get reconciled local queue job %s", backend_job_id)

            run_on_main_thread(_apply_get)

        client.send_request(
            JSONRPCMethod.JOB_GET,
            {"job_id": backend_job_id},
            _on_get_result,
        )
        return True
    except Exception as e:
        logger.debug("%s job.get request failed: %s", LOG_PREFIX, e)
        _request_backend_job_sync()
        return False


def _ensure_sync_watchdog() -> None:
    """Keep active jobs reconciled if an at-most-once job.update push is missed."""
    global _sync_watchdog_registered
    if _sync_watchdog_registered:
        return

    def _tick():
        global _sync_watchdog_registered
        # Enforce the wall-clock deadline here: the queue is push-driven, so
        # if the backend loses a job (or the socket stays down) no terminal
        # ``job.update`` ever arrives and the job would sit in RUNNING_POLL
        # forever. The watchdog is the only recurring tick that can fail it.
        now = time.time()
        # download_started_at is monotonic (like Job.created_at); poll_start_time
        # is epoch. Two clocks, so read both rather than mixing them.
        now_mono = time.monotonic()
        for queue in all_queues():
            for job in queue.snapshot():
                if (
                    job.state == JobState.RUNNING_POLL
                    and job.poll_start_time > 0
                    and now - job.poll_start_time > MAX_POLL_DURATION
                ):
                    queue._fail_timed_out(job)
                elif (
                    job.state == JobState.RUNNING_DOWNLOAD
                    and job.download_started_at > 0
                    and now_mono - job.download_started_at
                    > DOWNLOAD_WATCHDOG_DEADLINE_S
                ):
                    queue._fail_timed_out(job)
        states = [
            job.state for queue in all_queues() for job in queue.snapshot()
        ]
        if not any(state in _WATCHDOG_STATES for state in states):
            _sync_watchdog_registered = False
            return None
        if any(state in _BACKEND_SYNC_STATES for state in states):
            _request_backend_job_sync()
        return _SYNC_WATCHDOG_INTERVAL

    _sync_watchdog_registered = True
    bpy.app.timers.register(_tick, first_interval=_SYNC_WATCHDOG_INTERVAL)


# ---------------------------------------------------------------------------
# FeatureQueue
# ---------------------------------------------------------------------------


class FeatureQueue(DownloadMixin):
    """Owner of a feature's in-flight + pending + terminal jobs.

    The RUNNING_DOWNLOAD → SUCCESS/FAILED half of the lifecycle lives in
    ``DownloadMixin`` (``queue_download.py``) — same class, separate file.
    """

    def __init__(self, feature_key: str):
        self.feature_key = feature_key
        self._jobs: list = []
        self._listeners: list = []
        self._auth_paused = False
        self._pumping = False

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def submit(self, job: Job) -> bool:
        """Submit a job. Returns False if a duplicate is already queued."""
        # Dedup: reject if same label is already active
        if job.label and any(
            j.label == job.label and j.state not in TERMINAL_STATES
            for j in self._jobs
        ):
            logger.warning("%s duplicate job rejected: %s", LOG_PREFIX, job.label)
            return False
        job.feature_key = self.feature_key
        # Stamp the originating scene (submit runs on the main thread) so the
        # scene-flag listener targets the scene that started the job, not
        # whatever is active when a later notification fires.
        if not job.scene_name:
            try:
                scene = getattr(bpy.context, "scene", None)
                if scene is not None:
                    job.scene_name = scene.name
            except Exception:
                pass
        self._jobs.append(job)
        self._notify_enqueue_toast(job)
        self._notify()
        self._pump()
        return True

    def cancel(self, job_id: str) -> None:
        job = self._find(job_id)
        if job is None or job.state in TERMINAL_STATES:
            return
        # Cancel on backend if job has a backend ID
        if job.backend_job_id:
            self._cancel_on_backend(job.backend_job_id)
        # Set descriptive error for in-flight jobs (backend can't cancel them)
        if job.state in RUNNING_STATES:
            job.error = "Cancelled (generation may still complete on server)"
        job._submit_retry_scheduled = False
        job.state = JobState.CANCELLED
        if not job.error:
            job.error = "Cancelled"
        self._notify()
        self._pump()

    def cancel_all(self) -> None:
        for job in list(self._jobs):
            if job.state not in TERMINAL_STATES:
                if job.backend_job_id:
                    self._cancel_on_backend(job.backend_job_id)
                job._submit_retry_scheduled = False
                job.state = JobState.CANCELLED
                if not job.error:
                    job.error = "Cancelled"
        self._notify()
        self._pump()

    def clear_completed(self) -> None:
        self._jobs = [j for j in self._jobs if j.state not in TERMINAL_STATES]
        self._notify()

    def clear_all(self) -> None:
        """Drop every job — used when a new file is opened.

        The queue is process-global session state, not stored in the .blend, so
        a freshly opened file must start empty rather than inheriting the
        previous file's jobs (whose scene/node references are now stale).

        Non-terminal jobs first get cancel_all's terminal treatment: dropping
        a RUNNING_DOWNLOAD job nakedly would let its in-flight download thread
        survive with no queue entry and import the paid result into the
        freshly opened file via _finish_import.
        """
        for job in list(self._jobs):
            if job.state not in TERMINAL_STATES:
                if job.backend_job_id:
                    self._cancel_on_backend(job.backend_job_id)
                job._submit_retry_scheduled = False
                job.state = JobState.CANCELLED
                if not job.error:
                    job.error = "Cancelled"
            # Same release pass _notify() runs for terminal jobs — these are
            # being dropped, so no later notify will see them.
            try:
                job.release_resources()
            except Exception as e:
                logger.debug(
                    "%s resource release failed for %s: %s",
                    LOG_PREFIX, job.id, e,
                )
        self._jobs = []
        self._notify()

    def snapshot(self) -> list:
        return list(self._jobs)

    def add_listener(self, fn) -> None:
        if fn not in self._listeners:
            self._listeners.append(fn)

    def remove_listener(self, fn) -> None:
        try:
            self._listeners.remove(fn)
        except ValueError:
            pass

    def running_count(self) -> int:
        return sum(1 for j in self._jobs if j.state in RUNNING_STATES)

    def pending_count(self) -> int:
        return sum(1 for j in self._jobs if j.state == JobState.PENDING)

    def has_active_work(self) -> bool:
        return any(
            j.state in RUNNING_STATES
            or j.state == JobState.PENDING
            or j.state == JobState.PAUSED_AUTH
            for j in self._jobs
        )

    def paused_jobs(self) -> list:
        return [j for j in self._jobs if j.state == JobState.PAUSED_AUTH]

    # ------------------------------------------------------------------ #
    # Auth pause / resume (called by auth_watcher)
    # ------------------------------------------------------------------ #

    def is_auth_paused(self) -> bool:
        return self._auth_paused

    def resume_after_auth(self) -> None:
        self._auth_paused = False
        for job in self._jobs:
            if job.state == JobState.PAUSED_AUTH:
                job.state = JobState.PENDING
                job.error = ""
                job.user_message = ""
                job.backend_job_id = ""
                job.backend_api_type = ""
                job.submit_attempts = 0
                job._submit_retry_scheduled = False
                job.poll_count = 0
                job.poll_start_time = 0.0
                job.consecutive_poll_errors = 0
        self._notify()
        self._pump()

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    @staticmethod
    def _cancel_on_backend(backend_job_id: str) -> None:
        """Fire-and-forget cancel request to the backend queue."""
        try:
            from mixar.modules.common.api.services.job_queue_service import (
                get_job_queue_service,
            )
            service = get_job_queue_service()
            service.cancel_job(backend_job_id)
        except Exception as e:
            # Backend may return 404 for in-flight jobs it can't cancel
            logger.warning(
                "%s backend cancel failed for %s: %s (job may still complete on server)",
                LOG_PREFIX, backend_job_id, e,
            )


    def _find(self, job_id: str):
        for j in self._jobs:
            if j.id == job_id:
                return j
        return None

    @staticmethod
    def _notify_enqueue_toast(job: Job) -> None:
        """Confirm the enqueue with a viewport toast.

        The agent's chat text alone is easy to miss; this covers every
        enqueue path (user- and agent-initiated) since they all funnel
        through ``submit()``. The toast then stays up for as long as the
        queue has work — see enqueue_toast.
        """
        try:
            from .enqueue_toast import notify_job_enqueued
            notify_job_enqueued(job)
        except Exception as e:
            logger.debug("%s failed to push enqueue toast: %s", LOG_PREFIX, e)

    @staticmethod
    def _ensure_status_pump() -> None:
        """Keep the 0.5 s repaint pump running while this queue has work.

        The pump advances the Agent Bubble pill's elapsed clock. It was
        previously kicked only from ``queue_properties._sync_mirror``, which
        is attached to a hand-listed set of features — so a queue missing
        from that tuple ran jobs the pill counted but never repainted for,
        freezing the clock at 0:00. Starting it here covers every queue.
        """
        try:
            from mixar.modules.common.job_queue.ui import queue_status_icons
            queue_status_icons.start_blink_if_needed()
        except Exception as e:
            logger.debug("%s failed to start status pump: %s", LOG_PREFIX, e)

    @staticmethod
    def _refresh_queue_toast() -> None:
        """Keep the queue-activity toast in step with live job state.

        Runs on every notify (not just submit) because the toast's whole
        job is to survive until the queue drains: it has to follow jobs
        completing, failing and being cancelled, not only arriving.
        """
        try:
            from .enqueue_toast import refresh_from_queues
            refresh_from_queues()
        except Exception as e:
            logger.debug("%s failed to refresh queue toast: %s", LOG_PREFIX, e)

    def _notify(self) -> None:
        # Terminal jobs stay in history until the user clears them, but large
        # request bodies (notably base64 Auto Rig GLBs) must not stay with them.
        # Centralizing release here covers success, every failure branch, and
        # cancellation without relying on each transition site to remember it.
        for job in self._jobs:
            if job.state in TERMINAL_STATES:
                try:
                    job.release_resources()
                except Exception as e:
                    logger.debug(
                        "%s resource release failed for %s: %s",
                        LOG_PREFIX, job.id, e,
                    )
        self._notify_failure_toasts()
        self._refresh_queue_toast()
        self._ensure_status_pump()
        for fn in list(self._listeners):
            try:
                fn(self)
            except Exception as e:
                logger.warning("%s listener failed: %s", LOG_PREFIX, e)
        redraw_3d_views()

    def _notify_failure_toasts(self) -> None:
        """Surface a viewport toast once for each newly-FAILED job.

        A uniform safety net so a failed paid generation is never silent —
        previously only features whose listener passed ``batch_popup_title``
        showed any feedback, so Image Gen / Lookdev / Hunyuan UV / Texture
        Edit failures were invisible unless the Queue panel was open.
        """
        for job in self._jobs:
            if job.state == JobState.FAILED and not job._failure_notified:
                job._failure_notified = True
                try:
                    from mixar.modules.common.notifications import (
                        get_notification_store,
                    )
                    message = job.user_message or job.error or "Generation failed"
                    # display_label strips the agent-batch prefix + dedup hash
                    # ("ImageGen: a hero [3f2a]") that the raw label carries.
                    title = (
                        getattr(job, "display_label", "")
                        or job.label
                        or "Generation failed"
                    )
                    get_notification_store().push(
                        "error", title, body=message, priority="high",
                    )
                except Exception as e:
                    logger.debug(
                        "%s failed to push failure toast: %s", LOG_PREFIX, e,
                    )

    def _pump(self) -> None:
        if self._auth_paused or self._pumping:
            return
        self._pumping = True
        try:
            while True:
                next_job = next(
                    (j for j in self._jobs if j.state == JobState.PENDING), None
                )
                if next_job is None:
                    return
                self._start_job(next_job)
        finally:
            self._pumping = False

    # ------------------------------------------------------------------ #
    # Per-job state machine
    # ------------------------------------------------------------------ #

    def _start_job(self, job: Job) -> None:
        job.state = JobState.RUNNING_SUBMIT
        job.error = ""
        job.user_message = ""
        self._notify()
        self._submit_job_attempt(job)

    def _submit_job_attempt(self, job: Job) -> None:
        job.submit_attempts += 1
        job._submit_retry_scheduled = False

        def on_submit_success(response):
            self._on_submit_success(job, response)

        def on_submit_error(error):
            self._on_submit_error(job, error)

        try:
            job.submit(on_submit_success, on_submit_error)
        except Exception as e:
            self._on_submit_error(job, e)

    def _on_submit_success(self, job: Job, response) -> None:
        if job.state == JobState.CANCELLED:
            self._pump()
            return
        job.apply_backend_metadata(job._unwrap_response(response))
        job._submit_retry_scheduled = False
        job.error = ""
        job.user_message = ""
        try:
            job.parse_submit_response(response)
        except Exception as e:
            job.state = JobState.FAILED
            job.error = f"Failed to parse submit response: {e}"
            job.user_message = "Failed to process server response"
            self._notify()
            self._pump()
            return

        # Sync-type jobs may already have the result inline in the submit
        # response (e.g. ImageGen, Lookdev360).  Skip polling to avoid
        # hitting GET /jobs/<empty> → 404.
        if job.should_skip_poll():
            job.state = JobState.RUNNING_DOWNLOAD
            self._notify()
            self._begin_download(job, [])
            return

        job.state = JobState.RUNNING_POLL
        job.poll_count = 0
        job.poll_start_time = time.time()
        if not job.backend_status:
            job.backend_status = "PENDING"
        self._notify()
        _ensure_sync_watchdog()
        # The backend job queue is push-driven. Do not start the old REST GET
        # polling loop here; ``job.update``/``job.sync`` will advance the job.
        #
        # A very fast job can emit its terminal ``job.update`` push while we
        # are still in RUNNING_SUBMIT. handle_backend_job_update records the
        # status but skips the transition (pushes are at-most-once), so catch
        # up here instead of waiting for the next 30s watchdog sync.
        if job.backend_job_id:
            if job.backend_status == "DONE":
                _request_backend_job_get(job.backend_job_id)
            elif job.backend_status in FAILED_BACKEND_STATUSES:
                _request_backend_job_sync()

    def _on_submit_error(self, job: Job, error) -> None:
        if job.state != JobState.RUNNING_SUBMIT:
            return
        if isinstance(error, AuthenticationError):
            self._enter_auth_pause(job, error)
            return
        if isinstance(error, (APITimeoutError, APIConnectionError)):
            if self._retry_submit_later(job, error):
                return
        job.state = JobState.FAILED
        job.error = str(error)
        job.user_message = classify_error(error) or "Submission failed"
        self._notify()
        self._pump()

    def _retry_submit_later(self, job: Job, error) -> bool:
        """Keep ambiguous submit failures active and retry idempotently."""
        if job.state == JobState.CANCELLED:
            return True
        if job.backend_job_id:
            return True

        job.error = str(error)
        if job.submit_attempts >= job.max_submit_attempts:
            job.state = JobState.FAILED
            job.user_message = classify_error(error) or "Submission failed"
            self._notify()
            self._pump()
            return True

        job.state = JobState.RUNNING_SUBMIT
        job.user_message = "Submission still pending - retrying"
        self._notify()

        if job._submit_retry_scheduled:
            return True
        job._submit_retry_scheduled = True

        def _retry():
            job._submit_retry_scheduled = False
            if job.state != JobState.RUNNING_SUBMIT or job.backend_job_id:
                return None
            job.error = ""
            job.user_message = "Retrying submission..."
            self._notify()
            self._submit_job_attempt(job)
            return None

        bpy.app.timers.register(_retry, first_interval=job.submit_retry_delay_s)
        return True

    def _schedule_poll(self, job: Job, interval: float) -> None:
        # Capture job by closure; the tick is a no-op if state changed.
        custom = job.get_poll_interval()
        actual_interval = custom if custom > 0 else interval

        def tick():
            return self._poll_tick(job)

        bpy.app.timers.register(tick, first_interval=actual_interval)

    def _poll_tick(self, job: Job):
        if job.state != JobState.RUNNING_POLL:
            return None  # cancelled, paused, or terminal -- unregister

        elapsed = time.time() - job.poll_start_time
        if elapsed > MAX_POLL_DURATION:
            if job.backend_job_id:
                self._cancel_on_backend(job.backend_job_id)
            job.state = JobState.FAILED
            job.error = (
                f"Job timed out after {int(MAX_POLL_DURATION // 60)} minutes"
            )
            job.user_message = "Generation timed out — please try again"
            self._notify()
            self._pump()
            return None

        job.poll_count += 1

        def on_poll_success(response):
            self._on_poll_success(job, response)

        def on_poll_error(error):
            self._on_poll_error(job, error)

        try:
            job.poll(on_poll_success, on_poll_error)
        except Exception as e:
            self._on_poll_error(job, e)

        custom = job.get_poll_interval()
        return custom if custom > 0 else get_poll_interval(job.poll_count)

    def _on_poll_success(self, job: Job, response) -> None:
        # Full job.get/job.sync snapshots can arrive while a fast job is still
        # leaving RUNNING_SUBMIT. Retain their display metadata even when the
        # lifecycle parser must wait for RUNNING_POLL.
        job.apply_backend_metadata(job._unwrap_response(response))
        if job.state != JobState.RUNNING_POLL:
            return
        job.consecutive_poll_errors = 0
        try:
            status, result_files = job.parse_poll_response(response)
        except Exception as e:
            job.state = JobState.FAILED
            job.error = f"Error parsing poll response: {e}"
            job.user_message = "Failed to process server response"
            self._notify()
            self._pump()
            return

        if status in ("WAIT", "RUN"):
            self._notify()
            return
        if status == "DONE":
            job.state = JobState.RUNNING_DOWNLOAD
            self._notify()
            self._begin_download(job, result_files)
            return
        if status == "FAIL":
            job.state = JobState.FAILED
            if not job.error:
                job.error = "Job failed on backend"
            if not job.user_message:
                job.user_message = "Generation failed"
            self._notify()
            self._pump()
            return

    def _fail_timed_out(self, job: Job) -> None:
        """Fail a job stranded past its phase deadline.

        Two phases, two deadlines. Previously this hard-returned on anything
        but RUNNING_POLL, which is why a wedged download was unbounded: the
        poll phase was guarded and everything after it was not.
        """
        if job.state == JobState.RUNNING_POLL:
            # No terminal push arrived within MAX_POLL_DURATION.
            if job.backend_job_id:
                self._cancel_on_backend(job.backend_job_id)
            job.error = (
                f"Job timed out after {int(MAX_POLL_DURATION // 60)} minutes"
            )
            job.user_message = "Generation timed out — please try again"
        elif job.state == JobState.RUNNING_DOWNLOAD:
            # The worker thread should have failed itself long before this;
            # reaching here means it died without registering either callback.
            # Do NOT cancel on the backend — the generation already succeeded
            # and the user paid for it; only the transfer is lost.
            job.error = (
                "Download did not finish within "
                f"{int(DOWNLOAD_WATCHDOG_DEADLINE_S // 60)} minutes"
            )
            job.user_message = "Download timed out — please retry"
        else:
            return
        job.state = JobState.FAILED
        self._notify()
        self._pump()

    def _on_poll_error(self, job: Job, error) -> None:
        if job.state != JobState.RUNNING_POLL:
            return
        if isinstance(error, AuthenticationError):
            self._enter_auth_pause(job, error)
            return
        # If backend returned 404, the job was cleaned up (result already fetched or expired)
        status_code = getattr(error, 'status_code', None)
        if status_code == 404:
            job.state = JobState.FAILED
            job.error = "Job result expired — please retry"
            job.user_message = "Job result expired — please retry"
            self._notify()
            self._pump()
            return
        job.consecutive_poll_errors += 1
        logger.warning(
            "%s poll error for %s (%d/%d): %s",
            LOG_PREFIX,
            job.id,
            job.consecutive_poll_errors,
            MAX_CONSECUTIVE_POLL_ERRORS,
            error,
        )
        if job.consecutive_poll_errors >= MAX_CONSECUTIVE_POLL_ERRORS:
            job.state = JobState.FAILED
            job.error = (
                f"Failed after {MAX_CONSECUTIVE_POLL_ERRORS} "
                f"consecutive poll errors: {error}"
            )
            job.user_message = classify_error(error) or "Generation failed — please retry"
            self._notify()
            self._pump()

    # ------------------------------------------------------------------ #
    # Auth pause
    # ------------------------------------------------------------------ #

    def _enter_auth_pause(self, job: Job, error) -> None:
        job.state = JobState.PAUSED_AUTH
        job.error = "Waiting for sign-in"
        self._auth_paused = True
        self._notify()
        # Lazy import to avoid circulars
        from .auth_watcher import ensure_auth_watcher
        ensure_auth_watcher()
