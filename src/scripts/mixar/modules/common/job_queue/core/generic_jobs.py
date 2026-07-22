# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generic Job subclasses for the two dominant queue patterns.

``AsyncGLBJob``  — submit → poll → download GLB → import (8 former subclasses)
``SyncImageJob`` — submit (may return inline result) → download images → moodboard (3 former subclasses)
"""

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from mixar.config.logging_config import get_logger
from .job import FAILED_BACKEND_STATUSES, Job
from .helpers import download_images_to_moodboard, extract_image_urls

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pattern A — Async GLB
# ---------------------------------------------------------------------------


@dataclass
class AsyncGLBJob(Job):
    """Generic job: submit → poll → download GLB → import.

    Fields
    ------
    job_type, model : str
        Passed verbatim to ``JobQueueService.enqueue()``.
    payload : dict
        Serialised payload; cleared after successful submit.
    fail_message : str
        Human-readable fallback shown when the backend returns FAILED.
    _on_imported_hook : callable | None
        ``fn(job, object_names)`` called from ``on_imported``.
    """

    job_type: str = ""
    model: str = ""
    payload: dict = field(default_factory=dict)
    fail_message: str = "Generation failed"
    _on_imported_hook: Optional[Callable] = field(default=None, repr=False)
    # Extra glTF import operator kwargs (GLB only). Animate uses this to
    # keep Tripo rigged/animated imports from collapsing — see model_io.
    import_options: Optional[dict] = field(default=None, repr=False)

    _processing_started: bool = False

    # ------------------------------------------------------------------ #
    # Job interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error) -> None:
        from mixar.modules.common.api.services.job_queue_service import (
            get_job_queue_service,
        )
        service = get_job_queue_service()
        service.enqueue(
            job_type=self.job_type,
            model=self.model,
            payload=self.payload,
            idempotency_key=self.submit_idempotency_key,
            on_success=on_success,
            on_error=on_error,
        )

    def parse_submit_response(self, response) -> None:
        self._parse_standard_submit(response)
        self.payload = {}  # release memory

    def release_resources(self) -> None:
        self.payload = {}

    def parse_poll_response(self, response):
        return self._parse_standard_poll(
            response, fail_message=self.fail_message,
        )

    def on_imported(self, object_names: str) -> None:
        super().on_imported(object_names)
        if self._on_imported_hook is not None:
            try:
                self._on_imported_hook(self, object_names)
            except Exception as e:
                logger.warning("on_imported hook failed: %s", e)


# ---------------------------------------------------------------------------
# Pattern B — Sync Image
# ---------------------------------------------------------------------------


@dataclass
class SyncImageJob(Job):
    """Generic job: submit (possibly sync result) → download images → moodboard.

    Fields
    ------
    job_type, model : str
        Passed verbatim to ``JobQueueService.enqueue()``.
    payload : dict
        Serialised payload; cleared after successful submit.
    fail_message : str
        Human-readable fallback shown when the backend returns FAILED.
    prompt_text : str
        Stored with the moodboard entry.
    name_prefix : str
        Prefix for ``bpy.data.images`` names (e.g. ``"imagegen"``).
    undo_message : str
        If set, pushes an undo step after adding images.
    """

    job_type: str = ""
    model: str = ""
    payload: dict = field(default_factory=dict)
    fail_message: str = "Generation failed"
    name_prefix: str = "image"
    prompt_text: str = ""
    undo_message: str = ""
    base_name: str = ""  # agent-chosen image name (overrides name_prefix)

    _image_urls: List[str] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------------ #
    # Job interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error) -> None:
        from mixar.modules.common.api.services.job_queue_service import (
            get_job_queue_service,
        )
        service = get_job_queue_service()
        service.enqueue(
            job_type=self.job_type,
            model=self.model,
            payload=self.payload,
            idempotency_key=self.submit_idempotency_key,
            on_success=on_success,
            on_error=on_error,
        )

    def parse_submit_response(self, response) -> None:
        inner = self._unwrap_response(response)
        self.backend_job_id = inner.get("job_id", "") or ""

        status = inner.get("status", "")
        result = inner.get("result") or {}
        if status == "DONE" and isinstance(result, dict):
            self._image_urls = extract_image_urls(result)

        if not self.backend_job_id and not self._image_urls:
            raise ValueError("Enqueue response missing job_id")

        self.payload = {}  # release memory

    def release_resources(self) -> None:
        self.payload = {}
        self._image_urls = []

    def should_skip_poll(self) -> bool:
        return bool(self._image_urls)

    def parse_poll_response(self, response):
        inner = self._unwrap_response(response)
        status = inner.get("status", "")
        self.backend_status = status

        if status == "PENDING":
            return ("WAIT", [])
        if status in ("SUBMITTED", "POLLING"):
            return ("RUN", [])
        if status == "DONE":
            result = inner.get("result") or {}
            if isinstance(result, dict):
                self._image_urls = extract_image_urls(result)
            return ("DONE", [])
        if status in FAILED_BACKEND_STATUSES:
            self.error = inner.get("error", self.fail_message)
            self.user_message = (
                inner.get("user_message", "") or self.fail_message
            )
            return ("FAIL", [])
        return ("WAIT", [])

    def handle_result(self, result_files, on_done, on_error):
        if not self._image_urls:
            on_error("No image URLs in server response")
            return True

        download_images_to_moodboard(
            urls=list(self._image_urls),
            name_prefix=self.name_prefix,
            prompt=self.prompt_text,
            job_id=self.id,
            on_done=on_done,
            on_error=on_error,
            undo_message=self.undo_message,
            base_name=self.base_name,
        )
        return True

    def get_poll_interval(self):
        return 3.0
