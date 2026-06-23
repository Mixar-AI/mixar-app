# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.api.response import APIResponse
from mixar.modules.common.api.services import generation_queue_service as GQS
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


def test_generation_queue_facade_posts_to_job_queue(monkeypatch):
    monkeypatch.setattr(GQS, "get_access_token", lambda: "token")
    client = FakeClient()
    service = GQS.GenerationQueueService(client)
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


def test_job_status_and_cancel_use_job_queue_paths(monkeypatch):
    monkeypatch.setattr(GQS, "get_access_token", lambda: "token")
    client = FakeClient()
    service = GQS.GenerationQueueService(client)

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


def test_terminal_job_update_reconciles_with_ws_sync(monkeypatch):
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
                        "jobs": [
                            {
                                "job_id": "job-ws",
                                "state": "succeeded",
                                "result": {"result_files": []},
                            }
                        ]
                    }
                )
            return "ws-request"

    fake_client = FakeWSClient()
    monkeypatch.setattr(jsonrpc_client, "get_jsonrpc_client", lambda: fake_client)

    queue = QM.get_queue("test_ws_sync")
    job = FakeQueueJob()
    assert queue.submit(job) is True

    assert QM.handle_backend_job_update({"job_id": "job-ws", "state": "succeeded"})

    assert fake_client.requests == [("job.sync", {})]
    assert job.poll_calls == 0
    assert job.handled is True
    assert job.state == JobState.SUCCESS
