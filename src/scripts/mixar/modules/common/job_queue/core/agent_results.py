# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generation callbacks — report an agent-enqueued job's outcome upstream.

The backend agent enqueues a generation by running a script that calls one of
our operators; the operator returns as soon as the job is on a ``FeatureQueue``.
Everything after that happens HERE: the client submits, receives ``job.update``
pushes, downloads and imports the result, and is therefore the only party that
knows the final object / image names. So the client reports the terminal
outcome instead of the agent polling for it.

Flow
    enqueue  : ``FeatureQueue.submit`` stamps ``job.agent_ref`` from the
               window_manager side channel (``take_agent_ref``).
    terminal : ``FeatureQueue._notify`` (main thread, after every state
               change) sweeps for stamped jobs in a terminal state and sends
               a ``generation.agent_result`` JSON-RPC request per outcome.
    offline  : a process-local outbox retains just the callback params until
               the backend acknowledges them, rejects them permanently, or
               the retry/age budget expires. It survives queue clearing and
               file loads, and retries on a timer and after reconnect.

Rules this file exists to keep:
  * a job with an empty ``agent_ref`` (every user-initiated one) sends nothing;
  * ``_agent_reported`` is set only after a backend acknowledgement; retries
    keep the same generation identity (the backend deduplicates outcomes);
  * socket callbacks only enqueue Python data; the main-thread sweep owns
    outbox/job changes and Blender timer registration;
  * nothing raises — reporting can never break a queue notification;
  * no local filesystem path is ever put in the params.
"""

from dataclasses import dataclass, field
from queue import Empty, SimpleQueue
import time
import weakref

from ..constants import LOG_PREFIX
from .job import JobState, TERMINAL_STATES

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)


_RETRY_INTERVAL = 5.0
_REQUEST_TIMEOUT = 35.0
_MAX_ATTEMPTS = 20
_MAX_AGE = 60 * 60.0
_PERMANENT_REJECTIONS = ('not_owner', 'no_agent_ref', 'invalid_status')


@dataclass
class _PendingResult:
    params: dict
    job_refs: tuple
    created_at: float = field(default_factory=lambda: time.monotonic())
    attempts: int = 0
    attempt: object = None
    retry_at: float = 0.0


# No Job/Blender datablocks or generation/download payloads are retained here.
_pending: dict[str, _PendingResult] = {}
_responses = SimpleQueue()


# Local terminal state -> the status word the backend handler expects.
_STATUS_BY_STATE = {
    JobState.SUCCESS: "succeeded",
    JobState.FAILED: "failed",
    JobState.CANCELLED: "cancelled",
}


def split_result_names(raw) -> list:
    """Split ``imported_object_names`` into a clean list of names.

    The field is a display string joined with ``", "`` (3D: imported object
    names; image jobs: the moodboard image names). Tolerates a plain ``","``
    join and stray whitespace; a list is passed through.
    """
    if isinstance(raw, (list, tuple)):
        return [str(n).strip() for n in raw if str(n).strip()]
    if not raw:
        return []
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def build_agent_result_params(job) -> dict:
    """Assemble the ``generation.agent_result`` params for one terminal job."""
    ref = dict(job.agent_ref or {})
    return {
        "agent_ref": ref,
        "generation_id": str(ref.get("generation_id") or ""),
        "feature_key": str(getattr(job, "feature_key", "") or ""),
        # The base Job carries ``service``; the generic jobs carry the
        # catalog ``job_type`` they were enqueued with. Either names the
        # kind of generation to the backend.
        "job_type": str(
            getattr(job, "service", "") or getattr(job, "job_type", "") or ""
        ),
        "model": str(getattr(job, "model", "") or ""),
        "label": str(getattr(job, "label", "") or ""),
        "backend_job_id": str(getattr(job, "backend_job_id", "") or ""),
        "status": _STATUS_BY_STATE.get(job.state, "failed"),
        "error": str(
            getattr(job, "user_message", "") or getattr(job, "error", "") or ""
        ),
        "result_names": split_result_names(
            getattr(job, "imported_object_names", "")
        ),
    }


def _get_client():
    """Return a connected agent JSON-RPC client, or None."""
    from mixar.modules.space_mixie_chat.core.jsonrpc_client import (
        get_jsonrpc_client,
    )

    client = get_jsonrpc_client()
    if client is None or not client.is_connected:
        return None
    return client


def _apply_responses() -> None:
    """Only the main thread changes outbox entries or live queue jobs."""
    while True:
        try:
            key, attempt, result = _responses.get_nowait()
        except Empty:
            return
        entry = _pending.get(key)
        if entry is None or entry.attempt is not attempt:
            continue
        # A closed/unknown generation is acknowledged too: no live run can
        # consume it. A failed cross-worker relay, however, still needs retry.
        acknowledged = (isinstance(result, dict) and result.get("received") is True
                        and result.get("reason") != "relay_failed")
        if acknowledged:
            _retire(key, acknowledged=True)
        elif isinstance(result, dict) and (
            result.get('reason') in _PERMANENT_REJECTIONS
            or result.get('code') in (-32600, -32601, -32602)
        ):
            _retire(key, reason='permanent backend rejection')
        else:
            entry.attempt = None
            entry.retry_at = time.monotonic() + _RETRY_INTERVAL


def _retire(key, *, acknowledged=False, reason=''):
    entry = _pending.pop(key)
    for job_ref in entry.job_refs:
        job = job_ref()
        if job is not None:
            if acknowledged:
                job._agent_reported = True
            else:
                job._agent_report_abandoned = True
    if not acknowledged:
        logger.warning('%s giving up agent result %s after %d attempts: %s',
                       LOG_PREFIX, key, entry.attempts, reason)


def _retain_batch(batch):
    if batch.retained:
        return
    params = batch.result()
    if params is not None:
        key = next(iter(batch.members))
        _pending[key] = _PendingResult(params, tuple(batch.members.values()))
        batch.retained = True
        batch.outcomes.clear()


def report_agent_batch(batch):
    """Seal-time sweep, including jobs synchronously completed and cleared."""
    try:
        _retain_batch(batch)
        report_agent_results(())
    except Exception:
        logger.warning('%s agent batch sweep failed', LOG_PREFIX, exc_info=True)


def _retry_pending():
    report_agent_results(())
    return _RETRY_INTERVAL if _pending else None


def _arm_retry() -> None:
    import bpy

    if _pending and not bpy.app.timers.is_registered(_retry_pending):
        bpy.app.timers.register(_retry_pending, first_interval=_RETRY_INTERVAL, persistent=True)


def report_agent_results(jobs) -> int:
    """Retain terminal outcomes and send due requests; return the queued count.

    Must run on the main thread. Queue acceptance is not delivery: outcomes
    are retired on acknowledgement or bounded give-up. Queue clearing can
    discard the Job immediately after this call, including while offline.
    """
    sent = 0
    try:
        _apply_responses()
        for job in jobs:
            batch = getattr(job, '_agent_batch', None)
            if batch is not None:
                _retain_batch(batch)
                continue
            if (getattr(job, "agent_ref", None) and job.state in TERMINAL_STATES
                    and not getattr(job, "_agent_reported", False)
                    and not getattr(job, "_agent_report_abandoned", False) and job.id not in _pending):
                _pending[job.id] = _PendingResult(build_agent_result_params(job), (weakref.ref(job),))
        # Expire even while disconnected; a retired live job cannot be re-added.
        now = time.monotonic()
        for key, entry in list(_pending.items()):
            if now - entry.created_at >= _MAX_AGE:
                _retire(key, reason='retention deadline reached')
            elif entry.attempts >= _MAX_ATTEMPTS and now >= entry.retry_at:
                _retire(key, reason='retry budget exhausted')
        if not _pending:
            return 0
        _arm_retry()
        client = _get_client()
        if client is None:
            return 0

        from mixar.modules.space_mixie_chat.constants import JSONRPCMethod

        now = time.monotonic()
        for key, entry in list(_pending.items()):
            if now < entry.retry_at:
                continue
            # Fence late callbacks from a previous attempt. A deadline also
            # permits retry if the old client's writer stopped expiring RPCs.
            attempt = entry.attempt = object()
            entry.attempts += 1
            entry.retry_at = now + _REQUEST_TIMEOUT

            def received(result, key=key, attempt=attempt):
                _responses.put((key, attempt, result))

            try:
                client.send_request(JSONRPCMethod.GENERATION_AGENT_RESULT, entry.params,
                                    received, timeout=_REQUEST_TIMEOUT)
                sent += 1
            except Exception:
                entry.attempt = None
                entry.retry_at = now + _RETRY_INTERVAL
                logger.warning("%s agent result request could not be queued for %s", LOG_PREFIX, key)
        _apply_responses()
    except Exception:  # never escape into _notify
        logger.warning("%s agent result sweep failed", LOG_PREFIX, exc_info=True)
    return sent


def report_all_agent_results() -> int:
    """Sweep live queues AND retained cleared outcomes after (re)connect."""
    try:
        from .queue_manager import all_queues

        total = report_agent_results(job for queue in all_queues() for job in queue.snapshot())
        if total:
            logger.info(
                "%s reconnect sweep reported %d agent generation result(s)",
                LOG_PREFIX, total,
            )
        return total
    except Exception as e:
        logger.warning("%s agent result reconnect sweep failed: %s", LOG_PREFIX, e)
        return 0
