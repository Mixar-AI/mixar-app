# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Job dataclass + JobState enum for the job queue."""

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

FAILED_BACKEND_STATUSES = frozenset({"FAILED", "CANCELLED", "DLQ"})


@dataclass
class Job:
    """Base class for all queueable jobs.

    Subclasses implement ``submit``, ``poll``, ``parse_submit_response``,
    and ``parse_poll_response``.  All other state is shared.
    """

    feature_key: str = ""
    label: str = ""
    # Name of the scene that submitted this job. Captured at submit time so the
    # scene-flag listener can set/clear the "generating" bool on the ORIGINATING
    # scene rather than whatever scene happens to be active when a queue
    # notification fires (which strands the flag when the user switches scenes).
    scene_name: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: JobState = JobState.PENDING
    error: str = ""
    user_message: str = ""
    # Session-relative clocks (time.monotonic, not epoch) so they survive
    # being round-tripped through a 32-bit ``bpy.props.FloatProperty`` on
    # the scene-side mirror. Epoch seconds (~1.75e9) lose ~128 s of
    # precision when stored as a single-precision float, which corrupted
    # the queue row's elapsed display before we switched to monotonic.
    created_at: float = field(default_factory=time.monotonic)
    finished_at: float = 0.0  # stamped by the mirror sync on first terminal tick

    # Backend tracking
    # Generation identity is shared here rather than only on generic job
    # subclasses so bespoke queues receive authoritative submit/WS metadata.
    service: str = ""
    # Optional backend catalog capability that owns the originating workflow.
    # Usually the service's parent capability is correct; composite workflows
    # can override it without hardcoding any human-facing label.
    origin_capability_key: str = ""
    model: str = ""
    backend_job_id: str = ""
    backend_api_type: str = ""
    poll_count: int = 0
    poll_start_time: float = 0.0
    consecutive_poll_errors: int = 0
    backend_status: str = ""      # Raw status from backend (PENDING/SUBMITTED/POLLING/DONE/FAILED)
    queue_position: int = 0       # Position in backend queue (0 = not queued or unknown)
    # Full ``result`` object from the DONE poll. ``_parse_standard_poll``
    # returns only ``result_files`` (all any caller needed until segmentation),
    # but adapters also send sibling keys — e.g. Tripo segmentation's
    # ``part_names``, which the import hook uses to name the split objects.
    # Keeping the whole dict here means a new result field never needs another
    # signature change.
    result_data: dict = field(default_factory=dict)

    # Submit retry/idempotency tracking. A local HTTP submit timeout is
    # ambiguous: the backend may still accept the request later.
    submit_idempotency_key: str = field(default_factory=lambda: str(uuid.uuid4()))
    submit_attempts: int = 0
    max_submit_attempts: int = 3
    submit_retry_delay_s: float = 8.0
    _submit_retry_scheduled: bool = field(default=False, repr=False)

    # Result objects (populated by on_imported)
    imported_object_names: str = ""
    # Optional UI-only title when ``label`` also carries dedup or downstream
    # naming data. Keeping this structured avoids parsing human text.
    display_label: str = ""

    # Set once a FAILED toast has been surfaced for this job, so the queue's
    # per-notify failure sweep shows the toast exactly once (edge-detected).
    _failure_notified: bool = field(default=False, repr=False)

    # ------------------------------------------------------------------ #
    # Subclass interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error):  # pragma: no cover - abstract
        raise NotImplementedError

    def poll(self, on_success, on_error):
        """Default poll: GET /jobs/{backend_job_id} via JobQueueService.

        All concrete jobs use the same poll call. Override only if your
        feature requires a different polling endpoint.
        """
        from mixar.modules.common.api.services.job_queue_service import (
            get_job_queue_service,
        )
        service = get_job_queue_service()
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

    def release_resources(self) -> None:
        """Release large transient resources after entering a terminal state.

        Subclasses may override.  Implementations must be idempotent because
        queue notifications can run more than once for terminal jobs.
        """
        return None

    # ------------------------------------------------------------------ #
    # Shared response-parsing helpers
    # ------------------------------------------------------------------ #

    def _unwrap_response(self, response) -> dict:
        """Extract inner data dict from the API response envelope.

        Handles both ``{"data": {"data": {...}}}`` and ``{"data": {...}}``
        formats from the job queue backend.
        """
        data = getattr(response, "data", None) or {}
        inner = data.get("data", data) if isinstance(data, dict) else {}
        return inner if isinstance(inner, dict) else {}

    def apply_backend_metadata(self, data: dict) -> None:
        """Merge optional service/model fields from a client view.

        Missing keys are ignored for rolling-deploy compatibility. A blank
        incoming model also preserves the locally submitted model.
        """
        if not isinstance(data, dict):
            return

        if "service" in data:
            service = str(data.get("service") or "").strip()
            if service:
                self.service = service

        if "model" in data:
            model = str(data.get("model") or "").strip()
            if model:
                self.model = model

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
            if isinstance(result, dict):
                self.result_data = result
            result_files = (
                result.get("result_files", [])
                if isinstance(result, dict)
                else []
            )
            return ("DONE", result_files)
        if status in FAILED_BACKEND_STATUSES:
            error = inner.get("error", "")
            if error:
                self.error = error
            elif status == "CANCELLED":
                self.error = "Cancelled"
            elif status == "DLQ":
                self.error = "Job failed permanently after retries"
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
            # No elapsed time here — row 1 of the queue UIList already
            # shows the job's running clock; a second one is confusing.
            return "Processing"
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
