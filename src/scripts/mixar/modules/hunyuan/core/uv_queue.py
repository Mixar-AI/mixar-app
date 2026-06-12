# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hunyuan UV unwrapping queue: concrete Job + enqueue helper.

Mirrors ``retopology_queue.py`` but for the Hunyuan 3D UV unwrapping
service. The mesh file is exported and snapshotted at enqueue time.
"""

import base64
from dataclasses import dataclass

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.services.generation_queue_service import get_generation_queue_service
from mixar.modules.common.job_queue import Job, get_queue
from mixar.modules.common.job_queue.constants import FEATURE_HUNYUAN_UV
from mixar.modules.common.job_queue.core.queue_manager import FeatureQueue
from ..constants import LIMITS, MAX_FILE_SIZE_UV
from .hunyuan_helpers import _get_total_face_count, export_selected_mesh

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class UVJob(Job):
    """Concrete Job for the Hunyuan 3D UV unwrapping flow."""

    _processing_started: bool = False
    file_bytes: bytes = b""
    file_filename: str = "export.glb"

    # ------------------------------------------------------------------ #
    # Job interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error) -> None:
        service = get_generation_queue_service()
        payload = {
            "file_bytes_b64": base64.b64encode(self.file_bytes).decode(),
            "file_filename": self.file_filename,
        }
        service.enqueue(
            job_type="hunyuan_uv",
            model="hunyuan_uv",
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
            self.user_message = inner.get("user_message", "") or "Generation failed"
            return ("FAIL", [])
        return ("WAIT", [])

    def on_imported(self, object_names: str) -> None:
        super().on_imported(object_names)


# ---------------------------------------------------------------------------
# Enqueue helper
# ---------------------------------------------------------------------------


def enqueue_uv_job(*, context, operator=None) -> UVJob:
    """Validate face count, export mesh, create UVJob, submit to queue."""
    max_faces = LIMITS['UV']['max_faces']
    face_count = _get_total_face_count(context)
    if face_count > max_faces:
        raise ValueError(
            f"Selected mesh has {face_count:,} faces (max {max_faces:,})",
        )

    uv = context.scene.hunyuan.uv
    file_bytes, filename = export_selected_mesh(context, uv.export_format)
    if len(file_bytes) > MAX_FILE_SIZE_UV:
        size_mb = len(file_bytes) / (1024 * 1024)
        raise ValueError(f"Exported file is {size_mb:.1f}MB (max 100MB)")

    obj_name = next(
        (o.name for o in context.selected_objects if o.type == 'MESH'),
        "uv_job",
    )

    job = UVJob(
        feature_key=FEATURE_HUNYUAN_UV,
        label=obj_name,
        file_bytes=file_bytes,
        file_filename=filename,
    )
    queue = _get_uv_queue()
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
    was_generating = bool(getattr(scene, "mixie_hunyuan_uv_is_generating", False))

    if has_work and not was_generating:
        try:
            scene.mixie_hunyuan_uv_is_generating = True
        except (AttributeError, TypeError):
            pass
        return

    if not has_work and was_generating:
        try:
            scene.mixie_hunyuan_uv_is_generating = False
        except (AttributeError, TypeError):
            pass


def _get_uv_queue() -> FeatureQueue:
    global _listener_attached
    queue = get_queue(FEATURE_HUNYUAN_UV)
    if not _listener_attached:
        queue.add_listener(_on_queue_changed)
        _listener_attached = True
    return queue
