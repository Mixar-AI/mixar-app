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
