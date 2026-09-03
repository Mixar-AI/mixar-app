# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Generic Job subclasses for the dominant queue patterns.

``AsyncGLBJob``  — submit → poll → download GLB → import (8 former subclasses)
``SyncImageJob`` — submit (may return inline result) → download images → moodboard (3 former subclasses)
``StreamingVideoJob`` — stream inputs → submit → download video → moodboard
"""

import io
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from mixar.config.logging_config import get_logger
from .job import FAILED_BACKEND_STATUSES, Job, JobState
from .helpers import (
    download_images_to_moodboard,
    extract_image_name,
    extract_image_urls,
)

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
        ``fn(job, object_names) -> str | None`` called from ``on_imported``.
        A hook that RENAMES what it imported must return the final object
        name(s) — see ``on_imported`` for why.
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
        """Record the imported objects, then run the post-import hook.

        ``imported_object_names`` is the job's only handle on what it put in
        the scene, and every later consumer resolves it through
        ``bpy.data.objects.get()`` — the generations-library archiver, the
        queue list's "select the result" click. Most of our hooks RENAME the
        import (``model_gen`` names the mesh after the source image, retopology
        appends ``_low``), which frees the name recorded a line earlier and
        leaves the job pointing at an object that no longer exists.

        So a renaming hook returns its final name and we record THAT. Hooks
        that only inspect return None and keep the imported names.
        """
        super().on_imported(object_names)
        if self._on_imported_hook is not None:
            try:
                final = self._on_imported_hook(self, object_names)
            except Exception as e:
                logger.warning("on_imported hook failed: %s", e)
            else:
                if isinstance(final, str) and final.strip():
                    self.imported_object_names = final.strip()


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
    _on_images_added_hook : callable | None
        ``fn(job, names)`` called on the main thread after moodboard images
        are added and before the queue marks the job complete. Hook failure is
        terminal so required metadata cannot be silently omitted.
    """

    job_type: str = ""
    model: str = ""
    payload: dict = field(default_factory=dict)
    fail_message: str = "Generation failed"
    name_prefix: str = "image"
    prompt_text: str = ""
    undo_message: str = ""
    base_name: str = ""  # agent-chosen image name (overrides name_prefix)
    _on_images_added_hook: Optional[Callable] = field(default=None, repr=False)
    _on_imported_hook: Optional[Callable] = field(default=None, repr=False)

    _image_urls: List[str] = field(default_factory=list, repr=False)
    # Backend-suggested display name (model-generated for Gemini image gen).
    # Used only when no explicit base_name was provided.
    _server_image_name: str = field(default="", repr=False)

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
            self._server_image_name = extract_image_name(result)

        if not self.backend_job_id and not self._image_urls:
            raise ValueError("Enqueue response missing job_id")

        self.payload = {}  # release memory

    def release_resources(self) -> None:
        self.payload = {}
        self._image_urls = []
        self._on_images_added_hook = None

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
                self._server_image_name = extract_image_name(result)
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

        def _on_images_added(names: str) -> None:
            if self._on_images_added_hook is not None:
                self._on_images_added_hook(self, names)

        def _download_done(image_names: str):
            self.on_imported(image_names)
            on_done(image_names)

        download_images_to_moodboard(
            urls=list(self._image_urls),
            name_prefix=self.name_prefix,
            prompt=self.prompt_text,
            job_id=self.id,
            on_added=_on_images_added,
            on_done=_download_done,
            on_error=on_error,
            undo_message=self.undo_message,
            base_name=self.base_name or self._server_image_name,
            scene_name=self.scene_name,
            should_apply=lambda: self.state == JobState.RUNNING_DOWNLOAD,
        )
        return True

    def on_imported(self, image_names: str) -> None:
        super().on_imported(image_names)
        if self._on_imported_hook is not None:
            try:
                self._on_imported_hook(self, image_names)
            except Exception as e:
                logger.warning("on_imported hook failed: %s", e)

    def get_poll_interval(self):
        return 3.0


# ---------------------------------------------------------------------------
# Pattern C — streamed media inputs + video output
# ---------------------------------------------------------------------------


@dataclass
class StreamingVideoJob(AsyncGLBJob):
    """Stage large media without base64, then enqueue a video result job.

    ``image_inputs`` entries carry ``filename``, ``mime_type`` and ``bytes``.
    ``video_inputs`` carry ``filename``, ``mime_type``, ``filepath`` and
    ``file_size_bytes``. Uploads are sequential to bound memory and network
    pressure; each callback advances to the next input before the final queue
    submit.
    """

    image_inputs: list = field(default_factory=list, repr=False)
    video_inputs: list = field(default_factory=list, repr=False)
    max_video_duration_seconds: float = 15.0
    _upload_index: int = field(default=0, repr=False)
    _staged_image_keys: list = field(default_factory=list, repr=False)
    _staged_video_keys: list = field(default_factory=list, repr=False)
    _staged_video_seconds: float = field(default=0.0, repr=False)

    def _uploads(self):
        return [
            *(('image', item) for item in self.image_inputs),
            *(('video', item) for item in self.video_inputs),
        ]

    @staticmethod
    def _response_data(response):
        outer = getattr(response, "data", None) or {}
        data = outer.get("data", outer) if isinstance(outer, dict) else {}
        return data if isinstance(data, dict) else {}

    def submit(self, on_success, on_error) -> None:
        uploads = self._uploads()
        if self._upload_index >= len(uploads):
            if self._staged_image_keys:
                self.payload["reference_image_s3_keys"] = list(
                    self._staged_image_keys
                )
            if self._staged_video_keys:
                self.payload["reference_video_s3_keys"] = list(
                    self._staged_video_keys
                )
            super().submit(on_success, on_error)
            return

        media_kind, item = uploads[self._upload_index]
        if media_kind == 'image':
            content = item.get("bytes") or b""
            body_factory = lambda data=content: io.BytesIO(data)
            content_length = len(content)
        else:
            filepath = item.get("filepath") or ""
            body_factory = lambda path=filepath: open(path, "rb")
            content_length = int(item.get("file_size_bytes") or 0)

        from mixar.modules.common.api.services.job_queue_service import (
            get_job_queue_service,
        )

        def _staged(response):
            data = self._response_data(response)
            key = str(data.get("s3_key") or "")
            if not key:
                on_error(ValueError("Media staging response omitted s3_key"))
                return
            if media_kind == 'image':
                self._staged_image_keys.append(key)
            else:
                try:
                    duration = float(data.get("duration_seconds") or 0.0)
                except (TypeError, ValueError):
                    duration = 0.0
                if duration <= 0:
                    on_error(ValueError("Could not determine video duration"))
                    return
                self._staged_video_seconds += duration
                if self._staged_video_seconds > self.max_video_duration_seconds + 0.001:
                    # The cap is catalog-supplied; quoting a literal would
                    # misreport the limit the moment the DB seed changes.
                    on_error(ValueError(
                        "Selected videos exceed the "
                        f"{self.max_video_duration_seconds:g}-second "
                        "combined limit"
                    ))
                    return
                self._staged_video_keys.append(key)
            self._upload_index += 1
            self.submit(on_success, on_error)

        get_job_queue_service().stage_media(
            media_kind=media_kind,
            filename=item.get("filename") or f"reference.{media_kind}",
            content_type=item.get("mime_type") or "application/octet-stream",
            content_length=content_length,
            body_factory=body_factory,
            on_success=_staged,
            on_error=on_error,
        )

    def parse_submit_response(self, response) -> None:
        super().parse_submit_response(response)
        self.image_inputs = []
        self.video_inputs = []

    def release_resources(self) -> None:
        super().release_resources()
        self.image_inputs = []
        self.video_inputs = []
