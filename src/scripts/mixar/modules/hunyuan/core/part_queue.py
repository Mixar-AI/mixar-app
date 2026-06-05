# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hunyuan Part decomposition queue: concrete Job + enqueue helper.

Mirrors ``retopology_queue.py`` but for the Hunyuan 3D Part decomposition
service. The mesh file is exported and snapshotted at enqueue time.
"""

import base64
from dataclasses import dataclass

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.services.generation_queue_service import get_generation_queue_service
from mixar.modules.common.job_queue import (
    Job, get_queue_with_listener, create_scene_flag_listener,
)
from mixar.modules.common.job_queue.constants import FEATURE_HUNYUAN_PART
from ..constants import LIMITS, MAX_FILE_SIZE_PART
from .hunyuan_helpers import _get_total_face_count, export_selected_mesh

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class PartJob(Job):
    """Concrete Job for the Hunyuan 3D Part decomposition flow."""

    _processing_started: bool = False
    file_bytes: bytes = b""
    file_filename: str = "export.glb"

    def submit(self, on_success, on_error) -> None:
        service = get_generation_queue_service()
        payload = {
            "file_bytes_b64": base64.b64encode(self.file_bytes).decode(),
            "file_filename": self.file_filename,
        }
        service.enqueue(
            job_type="hunyuan_part",
            model="hunyuan_part",
            payload=payload,
            on_success=on_success,
            on_error=on_error,
        )

    def parse_submit_response(self, response) -> None:
        self._parse_standard_submit(response)

    def parse_poll_response(self, response):
        return self._parse_standard_poll(response, fail_message="Generation failed")


# ---------------------------------------------------------------------------
# Enqueue helper
# ---------------------------------------------------------------------------


def enqueue_part_job(*, context, operator=None) -> PartJob:
    """Validate face count, export mesh, create PartJob, submit to queue."""
    max_faces = LIMITS['PART']['max_faces']
    face_count = _get_total_face_count(context)
    if face_count > max_faces:
        raise ValueError(
            f"Selected mesh has {face_count:,} faces (max {max_faces:,})",
        )

    part = context.scene.hunyuan.part
    file_bytes, filename = export_selected_mesh(context, part.export_format)
    if len(file_bytes) > MAX_FILE_SIZE_PART:
        size_mb = len(file_bytes) / (1024 * 1024)
        raise ValueError(f"Exported file is {size_mb:.1f}MB (max 100MB)")

    obj_name = next(
        (o.name for o in context.selected_objects if o.type == 'MESH'),
        "part_job",
    )

    job = PartJob(
        feature_key=FEATURE_HUNYUAN_PART,
        label=obj_name,
        file_bytes=file_bytes,
        file_filename=filename,
    )
    queue = _get_part_queue()
    queue.submit(job)
    return job


# ---------------------------------------------------------------------------
# Queue listener
# ---------------------------------------------------------------------------

_listener = create_scene_flag_listener("mixie_hunyuan_part_is_generating")


def _get_part_queue():
    return get_queue_with_listener(FEATURE_HUNYUAN_PART, _listener)
