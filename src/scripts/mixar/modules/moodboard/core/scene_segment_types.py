# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""State types shared by the moodboard Scene Segment client."""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Iterable, List, Optional


SegmentCallback = Callable[[bool, Optional[bytes], str], None]
UploadCallback = Callable[[bool, str], None]


class JobStatus(Enum):
    """Lifecycle of an uploaded source image."""

    PENDING = "pending"
    UPLOADING = "uploading"
    READY = "ready"
    FAILED = "failed"


class RequestStatus(Enum):
    """Lifecycle of one segmentation request."""

    QUEUED = "queued"
    GENERATING = "generating"
    COMPLETED = "completed"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    FAILED = "failed"


@dataclass
class SegmentRequest:
    """Client-side tracking for a server segmentation request."""

    request_id: str
    status: RequestStatus = RequestStatus.QUEUED
    error: Optional[str] = None
    callback: Optional[SegmentCallback] = None
    created_at: float = field(default_factory=time.monotonic)


@dataclass
class JobState:
    """Client-side state for a source image and its SAM3 requests."""

    job_id: Optional[str] = None
    status: JobStatus = JobStatus.PENDING
    image_size: Optional[Dict[str, int]] = None
    expires_at: Optional[float] = None
    requests: Dict[str, SegmentRequest] = field(default_factory=dict)
    upload_callbacks: List[UploadCallback] = field(default_factory=list)


def expire_stalled_requests(
    states: Iterable[JobState], now: float, timeout: float,
) -> List[SegmentCallback]:
    """Prune non-terminal requests older than *timeout*."""
    callbacks = []
    for state in states:
        for request_id, request in list(state.requests.items()):
            if request.status not in (
                RequestStatus.QUEUED,
                RequestStatus.GENERATING,
            ):
                continue
            if now - request.created_at < timeout:
                continue
            request.status = RequestStatus.FAILED
            request.error = "Segmentation timed out"
            if request.callback:
                callbacks.append(request.callback)
            request.callback = None
            state.requests.pop(request_id, None)
    return callbacks


def drain_upload_callbacks(state: JobState) -> List[UploadCallback]:
    """Detach all upload waiters so each can be notified exactly once."""
    callbacks = list(state.upload_callbacks)
    state.upload_callbacks.clear()
    return callbacks
