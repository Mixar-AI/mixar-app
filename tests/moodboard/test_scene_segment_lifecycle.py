# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression tests for terminal Scene Segment client state."""

from pathlib import Path

from mixar.modules.moodboard.constants import (
    SCENE_SEGMENT_REQUEST_TIMEOUT_SECONDS,
)
from mixar.modules.moodboard.core.scene_segment_types import (
    JobState,
    RequestStatus,
    SegmentRequest,
    drain_upload_callbacks,
    expire_stalled_requests,
)

ROOT = Path(__file__).resolve().parents[2]
REQUESTS_PATH = (
    ROOT / "src/scripts/mixar/modules/moodboard/core/scene_segment_requests.py"
)


def test_stalled_request_is_pruned_and_callback_is_returned():
    called = []
    callback = lambda *_args: called.append(True)
    request = SegmentRequest(
        request_id="request-1",
        callback=callback,
        created_at=10.0,
    )
    state = JobState(requests={request.request_id: request})

    callbacks = expire_stalled_requests(
        [state],
        10.0 + SCENE_SEGMENT_REQUEST_TIMEOUT_SECONDS + 0.01,
        SCENE_SEGMENT_REQUEST_TIMEOUT_SECONDS,
    )

    assert callbacks == [callback]
    assert state.requests == {}
    assert request.status == RequestStatus.FAILED
    assert request.callback is None
    callbacks[0](False, None, "timed out")
    assert called == [True]


def test_download_completion_is_idempotent_for_late_async_responses():
    source = REQUESTS_PATH.read_text(encoding="utf-8")

    assert "if state.requests.get(request.request_id) is not request:" in source
    assert "state.requests.pop(request.request_id, None)" in source
    assert "threading.Thread" not in source


def test_all_upload_waiters_are_notified_once():
    results = []
    state = JobState()
    state.upload_callbacks.extend(
        [
            lambda success, message: results.append((1, success, message)),
            lambda success, message: results.append((2, success, message)),
        ]
    )

    first = drain_upload_callbacks(state)
    second = drain_upload_callbacks(state)
    for callback in first + second:
        callback(True, "ready")

    assert results == [(1, True, "ready"), (2, True, "ready")]
    assert state.upload_callbacks == []
