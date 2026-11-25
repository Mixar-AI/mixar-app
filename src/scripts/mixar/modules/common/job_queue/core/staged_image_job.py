# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image job whose ONE source file is streamed to the backend before submit.

``SyncImageJob`` sends its payload as-is, which suits prompts and small
base64 references. An upscale source is a full-resolution image (up to 96
megapixels): base64 in the job JSON would triple its memory and bypass the
backend's measured staging. This job streams the file through
``POST /job-queue/uploads/image?purpose=<upload_purpose>`` (the backend
measures it and stamps its size into the key it returns), puts that key in
``payload[source_key_field]``, then submits like any image job. The result
downloads to the Moodboard through the normal image path.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from .generic_jobs import SyncImageJob


@dataclass
class StagedImageJob(SyncImageJob):
    """``SyncImageJob`` plus one staged source image.

    ``source_input`` carries ``filename``, ``mime_type`` and EITHER ``bytes``
    (an in-memory copy, e.g. a packed image) OR ``filepath`` +
    ``file_size_bytes`` (streamed from disk on the upload thread).
    """

    source_input: dict = field(default_factory=dict, repr=False)
    upload_purpose: str = ""
    source_key_field: str = "image_s3_key"
    _staged_key: str = field(default="", repr=False)

    @staticmethod
    def _response_data(response):
        outer = getattr(response, "data", None) or {}
        data = outer.get("data", outer) if isinstance(outer, dict) else {}
        return data if isinstance(data, dict) else {}

    def _body(self):
        content = self.source_input.get("bytes")
        if content is not None:
            return (lambda data=bytes(content): io.BytesIO(data)), len(content)
        path = str(self.source_input.get("filepath") or "")
        if not path:
            raise ValueError("The source image has no data to upload")
        return (lambda p=path: open(p, "rb")), int(
            self.source_input.get("file_size_bytes") or 0
        )

    def submit(self, on_success, on_error) -> None:
        if self._staged_key:
            self.payload[self.source_key_field] = self._staged_key
            super().submit(on_success, on_error)
            return

        try:
            body_factory, content_length = self._body()
        except ValueError as exc:
            on_error(exc)
            return

        from mixar.modules.common.api.services.job_queue_service import (
            get_job_queue_service,
        )

        def _staged(response):
            key = str(self._response_data(response).get("s3_key") or "")
            if not key:
                on_error(ValueError("Media staging response omitted s3_key"))
                return
            self._staged_key = key
            self.source_input = {}  # the bytes are on the server now
            # A main-thread timer runs this after QueueManager's submitting_as
            # block has ended: the deferred enqueue re-states the job's origin.
            from mixar.modules.common.api.services.job_queue_service import (
                submitting_as,
            )
            with submitting_as(getattr(self, "origin", "")):
                self.submit(on_success, on_error)

        get_job_queue_service().stage_media(
            media_kind="image",
            filename=str(self.source_input.get("filename") or "source.png"),
            content_type=str(self.source_input.get("mime_type") or "image/png"),
            content_length=content_length,
            body_factory=body_factory,
            on_success=_staged,
            on_error=on_error,
            purpose=self.upload_purpose,
        )

    def release_resources(self) -> None:
        super().release_resources()
        self.source_input = {}
