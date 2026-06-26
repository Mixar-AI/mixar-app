# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Mesh Segmentation job queue: concrete Job + enqueue helpers.

Wires the generic ``FeatureQueue`` framework to the mesh segmentation
service. Async job type with inline JSON results (no file download).
"""

import base64 as _b64
from dataclasses import dataclass, field
from typing import Dict, Optional

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.services.job_queue_service import (
    get_job_queue_service,
)
from mixar.modules.common.job_queue import Job, get_queue
from mixar.modules.common.job_queue.core.job import FAILED_BACKEND_STATUSES
from mixar.modules.common.job_queue.constants import FEATURE_MESH_SEGMENT
from mixar.modules.common.job_queue.core.queue_manager import FeatureQueue
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class MeshSegmentJob(Job):
    """Concrete Job for mesh segmentation (async type, inline results)."""

    # Submission payload
    mesh_bytes_b64: str = ""
    mesh_filename: str = "mesh.obj"
    description: str = ""
    expected_parts: str = ""
    mesh_object_name: str = ""  # String reference, not bpy pointer

    # Internal state
    _result_data: Dict = field(default_factory=dict, repr=False)
    _processing_started: bool = False

    # ------------------------------------------------------------------ #
    # Job interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error) -> None:
        service = get_job_queue_service()
        payload = {
            "mesh_file_bytes_b64": self.mesh_bytes_b64,
            "mesh_filename": self.mesh_filename,
            "description": self.description,
            "expected_parts": self.expected_parts,
        }
        service.enqueue(
            job_type="mesh_segment",
            model="mesh_segment_v1",
            payload=payload,
            idempotency_key=self.submit_idempotency_key,
            on_success=on_success,
            on_error=on_error,
        )

    def poll(self, on_success, on_error) -> None:
        service = get_job_queue_service()
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

        # Release large payload memory after successful submission
        self.mesh_bytes_b64 = ""

    def parse_poll_response(self, response):
        data = getattr(response, "data", None) or {}
        inner = data.get("data", data) if isinstance(data, dict) else {}
        if not isinstance(inner, dict):
            return ("WAIT", [])

        status = inner.get("status", "")
        self.backend_status = status
        self.queue_position = inner.get("queue_position") or 0

        if status == "PENDING":
            try:
                scene = bpy.context.scene
                scene.mixie_mesh_segment_status = "pending"
                scene.mixie_mesh_segment_current_step = "Queued"
            except Exception:
                pass
            return ("WAIT", [])
        if status in ("SUBMITTED", "POLLING"):
            if not self._processing_started:
                self._processing_started = True
                import time
                self.poll_start_time = time.time()
            try:
                scene = bpy.context.scene
                scene.mixie_mesh_segment_status = "processing"
                scene.mixie_mesh_segment_current_step = "Processing..."
            except Exception:
                pass
            return ("RUN", [])
        if status == "DONE":
            result = inner.get("result") or {}
            if isinstance(result, dict):
                self._result_data = result
            return ("DONE", [])
        if status in FAILED_BACKEND_STATUSES:
            self.error = inner.get("error", "Mesh segmentation failed")
            self.user_message = inner.get("user_message", "") or "Mesh segmentation failed"
            return ("FAIL", [])
        return ("WAIT", [])

    def handle_result(self, result_files, on_done, on_error):
        """Apply labels to mesh synchronously on main thread."""
        island_labels = self._result_data.get("island_labels", {})
        if not island_labels:
            on_error("No island labels in result")
            return True

        mesh_obj = bpy.data.objects.get(self.mesh_object_name)
        if not mesh_obj:
            on_error(f"Mesh object '{self.mesh_object_name}' not found")
            return True

        try:
            from mixar.modules.mesh_segment.core.mesh_labeler import (
                apply_labels_to_mesh,
            )

            count, labels = apply_labels_to_mesh(mesh_obj, island_labels)
            logger.debug(
                "[MeshSegment] Applied %d vertex groups to '%s'",
                count, self.mesh_object_name,
            )
        except Exception as e:
            logger.error("[MeshSegment] Error applying labels: %s", e)
            on_error(f"Failed to apply labels: {e}")
            return True

        # Update scene properties
        try:
            scene = bpy.context.scene
            scene.mixie_mesh_segment_is_processing = False
            scene.mixie_mesh_segment_status = "completed"
            scene.mixie_mesh_segment_result = str(island_labels)
        except Exception:
            pass

        on_done(self.mesh_object_name)
        return True

    def get_poll_interval(self):
        return 2.0


# ---------------------------------------------------------------------------
# Enqueue helpers
# ---------------------------------------------------------------------------


def enqueue_mesh_segment_job(
    *,
    mesh_object_name: str,
    mesh_file_path: str,
    description: str,
    expected_parts: str,
) -> Optional[MeshSegmentJob]:
    """Build a ``MeshSegmentJob`` and submit it to the queue."""
    try:
        with open(mesh_file_path, "rb") as f:
            mesh_bytes = f.read()
    except Exception as e:
        logger.error("[MeshSegment] Failed to read mesh file: %s", e)
        return None

    job = MeshSegmentJob(
        feature_key=FEATURE_MESH_SEGMENT,
        label=f"Segment: {mesh_object_name}",
        mesh_bytes_b64=_b64.b64encode(mesh_bytes).decode(),
        mesh_filename="mesh.obj",
        description=description,
        expected_parts=expected_parts,
        mesh_object_name=mesh_object_name,
    )
    queue = _get_mesh_segment_queue()
    if not queue.submit(job):
        logger.warning("[MeshSegment] duplicate job rejected: %s", job.label)
        return None
    return job


# ---------------------------------------------------------------------------
# Queue listener
# ---------------------------------------------------------------------------


_listener_attached = False


def _on_queue_changed(queue: FeatureQueue) -> None:
    """Sync mesh segment progress to queue activity."""
    try:
        scene = bpy.context.scene
    except Exception:
        return
    if scene is None:
        return

    has_work = queue.has_active_work()
    was_processing = bool(getattr(scene, "mixie_mesh_segment_is_processing", False))

    if has_work and not was_processing:
        try:
            scene.mixie_mesh_segment_is_processing = True
            scene.mixie_mesh_segment_error = ""
        except (AttributeError, TypeError):
            pass
        return

    if not has_work and was_processing:
        try:
            scene.mixie_mesh_segment_is_processing = False
        except (AttributeError, TypeError):
            pass


def _get_mesh_segment_queue() -> FeatureQueue:
    global _listener_attached
    queue = get_queue(FEATURE_MESH_SEGMENT)
    if not _listener_attached:
        queue.add_listener(_on_queue_changed)
        _listener_attached = True
    return queue
