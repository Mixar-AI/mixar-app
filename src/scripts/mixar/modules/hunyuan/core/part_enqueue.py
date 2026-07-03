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


def _resolve_part_model(context) -> str:
    """Model slug for ``hunyuan_part`` — the Mesh Segment tab's catalog
    selection when its mode is Part Segmentation, else the catalog
    default, else the legacy hardcoded slug (byte-identical today)."""
    selected = ""
    try:
        from mixar.modules.common.generation_params import (
            resolve_model_slug, resolve_service_key,
        )
        sidebar = getattr(context.scene, 'mixie_moodboard_sidebar', None)
        tab = getattr(sidebar, 'tab_mesh_segment', None) if sidebar else None
        if tab is not None:
            mode = resolve_service_key(
                "mesh_segmentation", getattr(tab, "mode", ""))
            if mode == "hunyuan_part":
                selected = getattr(tab, 'model', '')
        return resolve_model_slug("hunyuan_part", selected, "hunyuan_part")
    except Exception:
        return "hunyuan_part"


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

    model = _resolve_part_model(context)
    payload = {
        "file_bytes_b64": _b64.b64encode(file_bytes).decode(),
        "file_filename": filename,
    }
    # Merge catalog schema params (none today — payload stays untouched).
    try:
        from mixar.modules.common.generation_params import (
            assemble_payload, collect_params,
        )
        payload = assemble_payload(
            "hunyuan_part", collect_params("hunyuan_part", model),
            payload, model)
    except Exception as e:
        logger.debug("Part catalog param merge skipped: %s", e)

    return enqueue_generation(
        kind="glb",
        feature_key=FEATURE_HUNYUAN_PART,
        job_type="hunyuan_part",
        model=model,
        payload=payload,
        label=obj_name,
        scene_flag="mixie_hunyuan_part_is_generating",
    )
