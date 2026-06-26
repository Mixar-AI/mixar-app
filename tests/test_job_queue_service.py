# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.api.response import APIResponse
from mixar.modules.common.api.exceptions import TimeoutError as APITimeoutError
from mixar.modules.common.api.processor import APIQueueProcessor
from mixar.modules.common.api.request_queue import (
    AsyncResponse,
    ResponseStatus,
    get_request_queues,
)
from mixar.modules.common.api.services import job_queue_service as JQS
from mixar.modules.common.job_queue.core.generic_jobs import AsyncGLBJob
from mixar.modules.common.job_queue.core import queue_manager as QM
from mixar.modules.common.job_queue.core.job import Job, JobState


class FakeClient:
    def __init__(self):
        self.calls = []

    def post_async(self, endpoint, **kwargs):
        self.calls.append(("POST", endpoint, kwargs))
        return "request-post"

    def get_async(self, endpoint, **kwargs):
        self.calls.append(("GET", endpoint, kwargs))
        return "request-get"

    def get(self, endpoint, **kwargs):
        self.calls.append(("GET_SYNC", endpoint, kwargs))
        return APIResponse(
            success=True,
            status_code=200,
            data={
                "status": "success",
                "message": "ok",
                "data": {
                    "job_id": "job-1",
                    "state": "succeeded",
                    "result": {"files": []},
                },
            },
        )

    def delete_async(self, endpoint, **kwargs):
        self.calls.append(("DELETE", endpoint, kwargs))
        return "request-delete"


def test_job_queue_service_posts_to_job_queue(monkeypatch):
    monkeypatch.setattr(JQS, "get_access_token", lambda: "token")
    client = FakeClient()
    service = JQS.JobQueueService(client)
    received = []

    request_id = service.enqueue(
        job_type="image_gen",
        model="flux",
        payload={"prompt": "oak"},
        on_success=received.append,
    )

    method, endpoint, kwargs = client.calls[0]
    assert request_id == "request-post"
    assert method == "POST"
    assert endpoint == "api/v1/job-queue/jobs"
    assert kwargs["json"]["service"] == "image_gen"
    assert kwargs["json"]["model"] == "flux"
    assert kwargs["json"]["payload"] == {"prompt": "oak"}
    assert kwargs["json"]["idempotency_key"]

    kwargs["on_success"](
        APIResponse(
            success=True,
            status_code=202,
            data={
                "status": "success",
                "message": "Job submitted",
                "data": {"job_id": "job-1", "state": "pending"},
            },
        )
    )
    assert received[0].data["data"]["job_id"] == "job-1"
    assert received[0].data["data"]["status"] == "PENDING"


def test_job_queue_service_accepts_stable_idempotency_key(monkeypatch):
    monkeypatch.setattr(JQS, "get_access_token", lambda: "token")
    client = FakeClient()
    service = JQS.JobQueueService(client)

    service.enqueue(
        job_type="retopology_tripo",
        model="tripo_v2",
        payload={"input_name": "BodySideRh"},
        idempotency_key="stable-submit-key",
    )

    assert client.calls[0][2]["json"]["idempotency_key"] == "stable-submit-key"


def test_job_status_and_cancel_use_job_queue_paths(monkeypatch):
    monkeypatch.setattr(JQS, "get_access_token", lambda: "token")
    client = FakeClient()
    service = JQS.JobQueueService(client)

    service.get_job_status("job-1")
    sync_response = service.get_job_status_sync("job-1")
    service.cancel_job("job-1")

    assert client.calls[0][:2] == ("GET", "api/v1/job-queue/jobs/job-1")
    assert client.calls[1][:2] == ("GET_SYNC", "api/v1/job-queue/jobs/job-1")
    assert client.calls[2][:2] == ("DELETE", "api/v1/job-queue/jobs/job-1")
    assert sync_response.data["data"]["status"] == "DONE"
    assert sync_response.data["data"]["result"] == {"files": []}


class FakeQueueJob(Job):
    poll_calls: int = 0
    handled: bool = False

    def submit(self, on_success, on_error):
        on_success(
            APIResponse(
                success=True,
                status_code=202,
                data={
                    "status": "success",
                    "message": "Job submitted",
                    "data": {"job_id": "job-ws", "state": "pending"},
                },
            )
        )

    def poll(self, on_success, on_error):
        self.poll_calls += 1

    def parse_submit_response(self, response) -> None:
        self._parse_standard_submit(response)

    def parse_poll_response(self, response):
        return self._parse_standard_poll(response)

    def handle_result(self, result_files, on_done, on_error):
        self.handled = True
        on_done("ws-result")
        return True


class AmbiguousSubmitJob(FakeQueueJob):
    submit_calls: int = 0

    def submit(self, on_success, on_error):
        self.submit_calls += 1
        self.submit_success = on_success
        self.submit_error = on_error
        if self.submit_calls == 1:
            on_error(APITimeoutError("Request timed out"))


def test_submit_timeout_stays_recoverable_until_late_success(monkeypatch):
    QM._queues.clear()
    QM._sync_watchdog_registered = False
    registered_timers = []
    monkeypatch.setattr(
        QM.bpy.app.timers,
        "register",
        lambda fn, first_interval=0.0: registered_timers.append((fn, first_interval)),
    )

    queue = QM.get_queue("test_submit_timeout_recovery")
    job = AmbiguousSubmitJob()
    assert queue.submit(job) is True

    assert job.state == JobState.RUNNING_SUBMIT
    assert job.submit_calls == 1
    assert job.user_message == "Submission still pending - retrying"
    assert registered_timers[0][1] == job.submit_retry_delay_s

    job.submit_success(
        APIResponse(
            success=True,
            status_code=202,
            data={
                "status": "success",
                "message": "Job submitted",
                "data": {"job_id": "job-late", "state": "pending"},
            },
        )
    )

    assert job.state == JobState.RUNNING_POLL
    assert job.backend_job_id == "job-late"

    retry_timer = registered_timers[0][0]
    assert retry_timer() is None
    assert job.submit_calls == 1


def test_async_timeout_callback_allows_late_success_response():
    queues = get_request_queues()
    queues.clear()
    processor = APIQueueProcessor()
    calls = []

    callback_id = queues.register_callback(
        on_success=lambda result: calls.append(("success", result)),
        on_error=lambda error: calls.append(("error", type(error).__name__)),
        timeout=1.0,
    )
    assert queues.cleanup_expired_callbacks(current_time=time.time() + 2.0) == 1

    timeout_response = queues.get_response()
    processor._dispatch_response(timeout_response)

    assert calls == [("error", "TimeoutError")]
    assert queues.expired_callback_count() == 1

    processor._dispatch_response(
        AsyncResponse(
            request_id="request-late",
            status=ResponseStatus.SUCCESS,
            result="accepted",
            callback_id=callback_id,
        )
    )

    assert calls == [("error", "TimeoutError"), ("success", "accepted")]
    assert queues.expired_callback_count() == 0
    queues.clear()


def test_async_glb_job_reuses_idempotency_key_on_submit_retry(monkeypatch):
    class FakeService:
        def __init__(self):
            self.calls = []

        def enqueue(self, **kwargs):
            self.calls.append(kwargs)

    fake_service = FakeService()
    monkeypatch.setattr(JQS, "get_job_queue_service", lambda: fake_service)

    job = AsyncGLBJob(
        job_type="retopology_tripo",
        model="tripo_v2",
        payload={"input_name": "BodySideRh"},
    )
    job.submit(lambda response: None, lambda error: None)
    job.submit(lambda response: None, lambda error: None)

    assert fake_service.calls[0]["idempotency_key"] == job.submit_idempotency_key
    assert fake_service.calls[1]["idempotency_key"] == job.submit_idempotency_key


def test_feature_queue_waits_for_ws_without_rest_poll_timer(monkeypatch):
    QM._queues.clear()
    QM._sync_watchdog_registered = False
    registered_timers = []
    monkeypatch.setattr(
        QM.bpy.app.timers,
        "register",
        lambda fn, first_interval=0.0: registered_timers.append(first_interval),
    )

    queue = QM.get_queue("test_ws_no_poll")
    job = FakeQueueJob()

    assert queue.submit(job) is True

    assert job.state == JobState.RUNNING_POLL
    assert job.backend_job_id == "job-ws"
    assert job.backend_status == "PENDING"
    assert job.poll_calls == 0
    assert registered_timers == [QM._SYNC_WATCHDOG_INTERVAL]


def test_terminal_job_update_reconciles_with_ws_get(monkeypatch):
    QM._queues.clear()
    QM._sync_watchdog_registered = False
    monkeypatch.setattr(QM.bpy.app.timers, "register", lambda *args, **kwargs: None)

    from mixar.modules.space_mixie_chat.core import jsonrpc_client, main_thread_executor

    monkeypatch.setattr(main_thread_executor, "run_on_main_thread", lambda fn: fn())

    class FakeWSClient:
        is_connected = True

        def __init__(self):
            self.requests = []

        def send_request(self, method, params, on_result=None):
            self.requests.append((method, params))
            if on_result is not None:
                on_result(
                    {
                        "job": {
                            "job_id": "job-ws",
                            "state": "succeeded",
                            "result": {"result_files": []},
                        }
                    }
                )
            return "ws-request"

    fake_client = FakeWSClient()
    monkeypatch.setattr(jsonrpc_client, "get_jsonrpc_client", lambda: fake_client)

    queue = QM.get_queue("test_ws_sync")
    job = FakeQueueJob()
    assert queue.submit(job) is True

    assert QM.handle_backend_job_update({"job_id": "job-ws", "state": "succeeded"})

    assert fake_client.requests == [("job.get", {"job_id": "job-ws"})]
    assert job.poll_calls == 0
    assert job.handled is True
    assert job.state == JobState.SUCCESS


def test_dlq_job_update_fails_immediately(monkeypatch):
    QM._queues.clear()
    QM._sync_watchdog_registered = False
    monkeypatch.setattr(QM.bpy.app.timers, "register", lambda *args, **kwargs: None)

    queue = QM.get_queue("test_ws_dlq")
    job = FakeQueueJob()
    assert queue.submit(job) is True

    assert QM.handle_backend_job_update(
        {
            "job_id": "job-ws",
            "state": "dlq",
            "error": "exhausted retries",
        }
    )

    assert job.backend_status == "DLQ"
    assert job.poll_calls == 0
    assert job.state == JobState.FAILED
    assert job.error == "exhausted retries"
