# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Model 3D generation queue: concrete Job + enqueue helper.

Replaces the blocking 600s async call in ``image_to_3d_ops.py`` with a
proper submit+poll queue pattern via the unified generation queue.
"""

import base64
from dataclasses import dataclass
from typing import Optional

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.services.generation_queue_service import get_generation_queue_service
from mixar.modules.common.job_queue import Job, JobState, get_queue
from mixar.modules.common.job_queue.constants import FEATURE_MODEL_3D
from mixar.modules.common.job_queue.core.queue_manager import FeatureQueue

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class Model3DJob(Job):
    """Concrete Job for the Model 3D generation flow (Replicate/Tripo)."""

    _processing_started: bool = False
    image_bytes: bytes = b""
    image_filename: str = "image.png"
    model_name: str = ""
    prompt: Optional[str] = None
    parameters: Optional[dict] = None

    # ------------------------------------------------------------------ #
    # Job interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error) -> None:
        service = get_generation_queue_service()
        payload = {}
        if self.image_bytes:
            payload["image_bytes_b64"] = base64.b64encode(self.image_bytes).decode()
            payload["image_filename"] = self.image_filename
        if self.prompt:
            payload["prompt"] = self.prompt
        if self.parameters:
            payload["params"] = self.parameters

        service.enqueue(
            job_type="model_3d",
            model=self.model_name,
            payload=payload,
            on_success=on_success,
            on_error=on_error,
        )

    def poll(self, on_success, on_error) -> None:
        service = get_generation_queue_service()
        service.get_job_status(
            self.backend_job_id,
            on_success=on_success,
            on_error=on_error,
        )

    def parse_submit_response(self, response) -> None:
        data = getattr(response, "data", None) or {}
        inner = data.get("data", data) if isinstance(data, dict) else {}
        self.backend_job_id = inner.get("job_id", "") if isinstance(inner, dict) else ""
        if not self.backend_job_id:
            raise ValueError("Enqueue response missing job_id")

    def parse_poll_response(self, response):
        data = getattr(response, "data", None) or {}
        inner = data.get("data", data) if isinstance(data, dict) else {}
        if not isinstance(inner, dict):
            return ("WAIT", [])
        status = inner.get("status", "") or ""
        self.backend_status = status
        self.queue_position = inner.get("queue_position") or 0
        if status == "PENDING":
            return ("WAIT", [])
        if status in ("SUBMITTED", "POLLING"):
            if not self._processing_started:
                self._processing_started = True
                self.poll_start_time = __import__("time").time()
            return ("RUN", [])
        if status == "DONE":
            result = inner.get("result") or {}
            result_files = result.get("result_files", []) if isinstance(result, dict) else []
            return ("DONE", result_files)
        if status == "FAILED":
            error = inner.get("error", "")
            if error:
                self.error = error
            self.user_message = inner.get("user_message", "") or "3D model generation failed"
            return ("FAIL", [])
        return ("WAIT", [])

    def on_imported(self, object_names: str) -> None:
        super().on_imported(object_names)


# ---------------------------------------------------------------------------
# Enqueue helper
# ---------------------------------------------------------------------------


def enqueue_model_3d_job(
    *,
    image_bytes: bytes,
    model_name: str,
    prompt: Optional[str] = None,
    parameters: Optional[dict] = None,
    label: str = "",
) -> Model3DJob:
    """Create a Model3DJob and submit it to the queue."""
    if not label:
        label = model_name or "model_3d"

    job = Model3DJob(
        feature_key=FEATURE_MODEL_3D,
        label=label,
        image_bytes=image_bytes,
        image_filename="image.png",
        model_name=model_name,
        prompt=prompt,
        parameters=parameters,
    )
    queue = _get_model_3d_queue()
    queue.submit(job)
    return job


# ---------------------------------------------------------------------------
# Queue listener
# ---------------------------------------------------------------------------

_listener_attached = False


def _on_queue_changed(queue: FeatureQueue) -> None:
    try:
        scene = bpy.context.scene
    except Exception:
        return
    if scene is None:
        return

    has_work = queue.has_active_work()
    was_generating = bool(getattr(scene, "mixie_image_to_3d_is_generating", False))

    if has_work and not was_generating:
        try:
            scene.mixie_image_to_3d_is_generating = True
        except (AttributeError, TypeError):
            pass
        return

    if not has_work and was_generating:
        try:
            scene.mixie_image_to_3d_is_generating = False
        except (AttributeError, TypeError):
            pass

        snapshot = queue.snapshot()
        succeeded = sum(1 for j in snapshot if j.state == JobState.SUCCESS)
        failed = sum(1 for j in snapshot if j.state == JobState.FAILED)
        cancelled = sum(1 for j in snapshot if j.state == JobState.CANCELLED)

        if (succeeded + failed + cancelled) > 0:
            _show_batch_summary_popup(succeeded, failed, cancelled)


def _show_batch_summary_popup(succeeded: int, failed: int, cancelled: int) -> None:
    def _draw(self_menu, context):
        layout = self_menu.layout
        layout.label(text=f"Succeeded: {succeeded}", icon='CHECKMARK')
        if failed:
            layout.label(text=f"Failed: {failed}", icon='ERROR')
        if cancelled:
            layout.label(text=f"Cancelled: {cancelled}", icon='CANCEL')

    def _popup():
        try:
            wm = bpy.context.window_manager
            wm.popup_menu(
                _draw,
                title="Image to 3D batch complete",
                icon='INFO',
            )
        except Exception as e:
            logger.debug("Batch summary popup failed: %s", e)
        return None

    try:
        bpy.app.timers.register(_popup, first_interval=0.0)
    except Exception as e:
        logger.debug("Could not schedule batch summary popup: %s", e)


def _get_model_3d_queue() -> FeatureQueue:
    global _listener_attached
    queue = get_queue(FEATURE_MODEL_3D)
    if not _listener_attached:
        queue.add_listener(_on_queue_changed)
        _listener_attached = True
    return queue
