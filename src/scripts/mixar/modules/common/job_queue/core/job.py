# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Job dataclass + JobState enum for the generation queue."""

from dataclasses import dataclass, field
from enum import Enum
import time
import uuid


class JobState(str, Enum):
    PENDING = "PENDING"
    RUNNING_SUBMIT = "RUNNING_SUBMIT"
    RUNNING_POLL = "RUNNING_POLL"
    RUNNING_DOWNLOAD = "RUNNING_DOWNLOAD"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PAUSED_AUTH = "PAUSED_AUTH"


TERMINAL_STATES = frozenset(
    {JobState.SUCCESS, JobState.FAILED, JobState.CANCELLED}
)
RUNNING_STATES = frozenset(
    {
        JobState.RUNNING_SUBMIT,
        JobState.RUNNING_POLL,
        JobState.RUNNING_DOWNLOAD,
    }
)


@dataclass
class Job:
    """Base class for all queueable jobs.

    Subclasses implement ``submit``, ``poll``, ``parse_submit_response``,
    and ``parse_poll_response``.  All other state is shared.
    """

    feature_key: str = ""
    label: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: JobState = JobState.PENDING
    error: str = ""
    user_message: str = ""
    created_at: float = field(default_factory=time.time)

    # Backend tracking
    backend_job_id: str = ""
    backend_api_type: str = ""
    poll_count: int = 0
    poll_start_time: float = 0.0
    consecutive_poll_errors: int = 0
    backend_status: str = ""      # Raw status from backend (PENDING/SUBMITTED/POLLING/DONE/FAILED)
    queue_position: int = 0       # Position in backend queue (0 = not queued or unknown)

    # Result objects (populated by on_imported)
    imported_object_names: str = ""

    # ------------------------------------------------------------------ #
    # Subclass interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error):  # pragma: no cover - abstract
        raise NotImplementedError

    def poll(self, on_success, on_error):
        """Default poll: GET /jobs/{backend_job_id} via GenerationQueueService.

        All concrete jobs use the same poll call. Override only if your
        feature requires a different polling endpoint.
        """
        from mixar.modules.common.api.services.generation_queue_service import (
            get_generation_queue_service,
        )
        service = get_generation_queue_service()
        service.get_job_status(
            self.backend_job_id,
            on_success=on_success,
            on_error=on_error,
        )

    def parse_submit_response(self, response) -> None:  # pragma: no cover
        """Populate ``backend_job_id`` and ``backend_api_type`` from response."""
        raise NotImplementedError

    def parse_poll_response(self, response) -> tuple:  # pragma: no cover
        """Return ``(status, result_files)``.

        ``status`` is one of ``"WAIT"``, ``"RUN"``, ``"DONE"``, ``"FAIL"``.
        ``result_files`` is a list of ``{"type", "url"}`` dicts.
        """
        raise NotImplementedError

    def on_imported(self, object_names: str) -> None:
        """Optional hook called after a successful import on the main thread."""
        self.imported_object_names = object_names

    def should_skip_poll(self) -> bool:
        """Return True if the submit response already contains the result.

        Sync-type jobs (ImageGen, Lookdev360) may receive inline results in the
        submit response.  When that happens, polling would hit an empty
        ``backend_job_id`` and 404.  Override this to short-circuit straight to
        the download/handle_result phase.
        """
        return False

    def handle_result(self, result_files, on_done, on_error):
        """Override for non-standard results (images, textures, inline data).

        Return True = job handles it (MUST call on_done or on_error).
        Return False = use standard GLB download/import.
        """
        return False

    def get_poll_interval(self):
        """Override to customize poll interval (seconds). Return 0 for default."""
        return 0.0

    # ------------------------------------------------------------------ #
    # Shared response-parsing helpers
    # ------------------------------------------------------------------ #

    def _unwrap_response(self, response) -> dict:
        """Extract inner data dict from the API response envelope.

        Handles both ``{"data": {"data": {...}}}`` and ``{"data": {...}}``
        formats from the generation queue backend.
        """
        data = getattr(response, "data", None) or {}
        inner = data.get("data", data) if isinstance(data, dict) else {}
        return inner if isinstance(inner, dict) else {}

    def _parse_standard_submit(self, response) -> None:
        """Standard submit parsing: extract ``backend_job_id`` or raise."""
        inner = self._unwrap_response(response)
        self.backend_job_id = inner.get("job_id", "") or ""
        if not self.backend_job_id:
            raise ValueError("Enqueue response missing job_id")

    def _parse_standard_poll(
        self, response, *, fail_message="Generation failed",
    ) -> tuple:
        """Standard poll parsing for async (file-based) jobs.

        Maps backend statuses to the FeatureQueue protocol and extracts
        ``result_files``.  Resets ``poll_start_time`` on first SUBMITTED
        (if the subclass defines ``_processing_started``) so queue wait
        doesn't eat into the timeout budget.
        """
        inner = self._unwrap_response(response)
        status = inner.get("status", "") or ""
        self.backend_status = status
        self.queue_position = inner.get("queue_position") or 0

        if status == "PENDING":
            return ("WAIT", [])
        if status in ("SUBMITTED", "POLLING"):
            if hasattr(self, "_processing_started") and not self._processing_started:
                self._processing_started = True
                self.poll_start_time = time.time()
            return ("RUN", [])
        if status == "DONE":
            result = inner.get("result") or {}
            result_files = (
                result.get("result_files", [])
                if isinstance(result, dict)
                else []
            )
            return ("DONE", result_files)
        if status == "FAILED":
            error = inner.get("error", "")
            if error:
                self.error = error
            self.user_message = (
                inner.get("user_message", "") or fail_message
            )
            return ("FAIL", [])
        return ("WAIT", [])

    # ------------------------------------------------------------------ #
    # UI helpers
    # ------------------------------------------------------------------ #

    def substate_text(self) -> str:
        """Human-readable secondary text for the queue UIList."""
        st = self.state
        if st == JobState.PENDING:
            return "Pending"
        if st == JobState.RUNNING_SUBMIT:
            return "Submitting…"
        if st == JobState.RUNNING_POLL:
            bs = self.backend_status
            if bs == "PENDING":
                if self.queue_position > 0:
                    return f"Queued (#{self.queue_position})"
                return "Queued"
            elapsed = int(time.time() - self.poll_start_time) if self.poll_start_time else 0
            mins, secs = divmod(elapsed, 60)
            return f"Processing {mins}:{secs:02d}"
        if st == JobState.RUNNING_DOWNLOAD:
            return "Downloading…"
        if st == JobState.SUCCESS:
            return f"Done: {self.imported_object_names}" if self.imported_object_names else "Done"
        if st == JobState.FAILED:
            return "Failed"
        if st == JobState.CANCELLED:
            return "Cancelled"
        if st == JobState.PAUSED_AUTH:
            return "Waiting for sign-in"
        return ""
