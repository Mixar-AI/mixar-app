# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Streaming async requests must reopen bodies for auth retries."""

import io
from types import SimpleNamespace

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.common.api import client as client_module


class _Response:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data
        self.ok = status_code < 400
        self.headers = {}
        self.text = str(data)
        self.closed = False

    def json(self):
        return self._data

    def close(self):
        self.closed = True


class _ImmediateExecutor:
    is_running = True

    def submit(self, request, callback):
        try:
            callback(request.request_id, request.callable(), None)
        except Exception as exc:
            callback(request.request_id, None, exc)


def test_async_auth_retry_uses_fresh_closed_streams(monkeypatch):
    monkeypatch.setattr(client_module, "_ensure_api_infrastructure", lambda: None)
    monkeypatch.setattr(client_module, "get_executor", lambda: _ImmediateExecutor())
    monkeypatch.setattr(
        client_module,
        "refresh_access_token",
        lambda: {"success": True},
    )
    client = client_module.HTTPClient(base_url="https://api.example.test")
    first = _Response(401, {"detail": "expired"})
    second = _Response(200, {"data": {"s3_key": "owned/key"}})
    responses = iter((first, second))
    bodies = []
    reads = []

    def body_factory():
        body = io.BytesIO(b"video-bytes")
        bodies.append(body)
        return body

    def request(**kwargs):
        reads.append(kwargs["data"].read())
        return next(responses)

    client._session = SimpleNamespace(request=request)
    client.post_async(
        "api/v1/job-queue/uploads/video",
        data_factory=body_factory,
        headers={"Content-Type": "video/mp4"},
    )

    assert reads == [b"video-bytes", b"video-bytes"]
    assert len(bodies) == 2
    assert all(body.closed for body in bodies)
    assert first.closed is True
