# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hunyuan Part decomposition enqueue helper.

Validates face count and file size, then calls ``enqueue_generation(kind="glb")``.
"""

import base64 as _b64

from mixar.config.logging_config import get_logger
from mixar.modules.common.job_queue import enqueue_generation
from mixar.modules.common.job_queue.constants import FEATURE_HUNYUAN_PART
from ..constants import LIMITS, MAX_FILE_SIZE_PART
from .hunyuan_helpers import _get_total_face_count, export_selected_mesh

logger = get_logger(__name__)


def enqueue_part_job(*, context, operator=None):
    """Validate face count, export mesh, and submit a Part job to the queue."""
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

    payload = {
        "file_bytes_b64": _b64.b64encode(file_bytes).decode(),
        "file_filename": filename,
    }

    return enqueue_generation(
        kind="glb",
        feature_key=FEATURE_HUNYUAN_PART,
        job_type="hunyuan_part",
        model="hunyuan_part",
        payload=payload,
        label=obj_name,
        scene_flag="mixie_hunyuan_part_is_generating",
    )
