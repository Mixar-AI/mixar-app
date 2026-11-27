# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A job must not strand behind a WebSocket push that cannot arrive.

Production defect these pin (prod, 2026-10-06): a World Labs job finished on
the backend in five minutes, but the desktop had no agent WebSocket that
session. ``job.update``, ``job.get`` and ``job.sync`` all ride that socket, so
the job sat in RUNNING_POLL for MAX_POLL_DURATION, was failed as "timed out",
and the client then tried to cancel a job that had already succeeded (409).
The watchdog now polls ``GET /job-queue/jobs/{id}`` while the socket is down.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

import bpy

bpy.types.Panel.bl_rna = SimpleNamespace(
    properties={"bl_space_type": SimpleNamespace(enum_items=[])}
)

from mixar.modules.common.api.exceptions import (
    AuthenticationError,
    ConnectionError as APIConnectionError,
)
from mixar.modules.common.api.response import APIResponse
from mixar.modules.common.api.services.job_queue_service import JobQueueService
from mixar.modules.common.job_queue.core import queue_manager as QM
from mixar.modules.common.job_queue.core.job import Job, JobState

_NOW = 1_700_000_000.0


class _PollJob(Job):
    """A job whose REST poll is scripted by the test."""

    def submit(self, on_success, on_error):  # pragma: no cover - unused
        raise NotImplementedError

    def parse_submit_response(self, response):  # pragma: no cover - unused
        raise NotImplementedError

    def parse_poll_response(self, response):
        return self._parse_standard_poll(response)

    def poll(self, on_success, on_error):
        self.poll_calls = getattr(self, "poll_calls", 0) + 1
        outcome = self.poll_outcome
        if isinstance(outcome, Exception):
            on_error(outcome)
        else:
            on_success(outcome)


def _snapshot(state, result=None, error=None):
    data = {"job_id": "backend-1", "state": state}
    if result is not None:
        data["result"] = result
    if error is not None:
        data["error"] = error
    # ``Job.poll`` goes through JobQueueService.get_job_status, which hands
    # the parser the normalized envelope; the scripted poll does the same.
    return JobQueueService._normalize_response(
        APIResponse(
            success=True,
            status_code=200,
            data={"status": "success", "message": "ok", "data": data},
        )
    )


@pytest.fixture
def queue(monkeypatch):
    QM._queues.clear()
    QM._sync_watchdog_registered = False
    monkeypatch.setattr(QM, "redraw_3d_views", lambda: None)
    monkeypatch.setattr(QM.time, "time", lambda: _NOW)
    monkeypatch.setattr(QM.bpy.app.timers, "register", lambda *a, **k: None)
    q = QM.FeatureQueue("test_fallback")
    QM._queues["test_fallback"] = q
    yield q
    QM._queues.clear()
    QM._sync_watchdog_registered = False


def _polling_job(queue, outcome):
    job = _PollJob(label="job", feature_key="test_fallback")
    job.state = JobState.RUNNING_POLL
    job.backend_job_id = "backend-1"
    job.poll_start_time = _NOW - 30.0
    job.poll_outcome = outcome
    queue._jobs.append(job)
    return job


def _watchdog_tick(monkeypatch, *, socket_up):
    captured = []
    monkeypatch.setattr(
        QM.bpy.app.timers, "register", lambda fn, **k: captured.append(fn),
    )
    sync_calls = []
    monkeypatch.setattr(
        QM, "_request_backend_job_sync",
        lambda: sync_calls.append(1) or socket_up,
    )
    QM._sync_watchdog_registered = False
    QM._ensure_sync_watchdog()
    assert captured
    return captured[0], sync_calls


def test_socket_down_done_job_starts_download(queue, monkeypatch):
    """The defect: with no socket the DONE job waited for a push that never
    came. The REST snapshot must advance it exactly like a sync snapshot."""
    downloads = []
    monkeypatch.setattr(
        QM.FeatureQueue, "_begin_download",
        lambda self, job, files: downloads.append((job, files)),
    )
    files = [{"type": "glb", "url": "https://example.test/world.spz"}]
    job = _polling_job(queue, _snapshot("succeeded", result={"result_files": files}))

    tick, sync_calls = _watchdog_tick(monkeypatch, socket_up=False)
    assert tick() == QM._SYNC_WATCHDOG_INTERVAL

    assert sync_calls, "the socket path is still tried first"
    assert job.poll_calls == 1
    assert job.state == JobState.RUNNING_DOWNLOAD
    assert downloads == [(job, files)]


def test_socket_down_failed_job_carries_backend_reason(queue, monkeypatch):
    job = _polling_job(
        queue, _snapshot("failed", error="The provider rejected the prompt."),
    )
    tick, _ = _watchdog_tick(monkeypatch, socket_up=False)
    tick()

    assert job.state == JobState.FAILED
    assert job.error == "The provider rejected the prompt."


def test_fallback_is_rate_limited(queue, monkeypatch):
    """The watchdog ticks every 5 s; REST is polled once per fallback interval."""
    job = _polling_job(queue, _snapshot("running"))
    tick, _ = _watchdog_tick(monkeypatch, socket_up=False)

    tick()
    assert job.poll_calls == 1
    tick()  # same clock — inside the interval
    assert job.poll_calls == 1
    monkeypatch.setattr(QM.time, "time", lambda: _NOW + QM._REST_FALLBACK_INTERVAL)
    tick()
    assert job.poll_calls == 2
    assert job.state == JobState.RUNNING_POLL


def test_socket_up_never_polls_rest(queue, monkeypatch):
    job = _polling_job(queue, _snapshot("succeeded", result={"result_files": []}))
    tick, sync_calls = _watchdog_tick(monkeypatch, socket_up=True)
    tick()

    assert sync_calls == [1]
    assert getattr(job, "poll_calls", 0) == 0
    assert job.state == JobState.RUNNING_POLL


def test_fallback_skips_jobs_without_a_backend_id(queue, monkeypatch):
    job = _polling_job(queue, _snapshot("succeeded"))
    job.backend_job_id = ""
    tick, _ = _watchdog_tick(monkeypatch, socket_up=False)
    tick()
    assert getattr(job, "poll_calls", 0) == 0


def test_transient_rest_error_is_not_counted(queue, monkeypatch):
    """A flaky network must not fail a paid generation; the 60-minute
    deadline stays the only way a fallback-polled job times out."""
    job = _polling_job(queue, APIConnectionError("offline"))
    tick, _ = _watchdog_tick(monkeypatch, socket_up=False)
    for i in range(QM.MAX_CONSECUTIVE_POLL_ERRORS + 2):
        monkeypatch.setattr(
            QM.time, "time", lambda i=i: _NOW + i * QM._REST_FALLBACK_INTERVAL,
        )
        tick()

    assert job.poll_calls == QM.MAX_CONSECUTIVE_POLL_ERRORS + 2
    assert job.consecutive_poll_errors == 0
    assert job.state == JobState.RUNNING_POLL


def test_auth_error_pauses_like_a_normal_poll(queue, monkeypatch):
    monkeypatch.setattr(
        "mixar.modules.common.job_queue.core.auth_watcher.ensure_auth_watcher",
        lambda: None,
    )
    job = _polling_job(
        queue, AuthenticationError(message="expired", status_code=401),
    )
    tick, _ = _watchdog_tick(monkeypatch, socket_up=False)
    tick()
    assert job.state == JobState.PAUSED_AUTH


def test_deadline_still_fails_a_job_the_backend_never_finishes(queue, monkeypatch):
    cancelled = []
    monkeypatch.setattr(
        QM.FeatureQueue, "_cancel_on_backend",
        staticmethod(lambda job_id: cancelled.append(job_id)),
    )
    job = _polling_job(queue, _snapshot("running"))
    job.poll_start_time = _NOW - QM.MAX_POLL_DURATION - 1
    tick, _ = _watchdog_tick(monkeypatch, socket_up=False)
    tick()

    assert job.state == JobState.FAILED
    assert cancelled == ["backend-1"]
