# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Build and atomically persist semantic metadata staged with each checkpoint."""

from pathlib import Path

from ..constants import CHECKPOINTS_DIR, MODULE_DIR, SCHEMA_VERSION
from .models import CheckpointRequest
from .project_store import _atomic_json


def write_checkpoint_manifest(request: CheckpointRequest) -> str:
    relative = f"{MODULE_DIR}/{CHECKPOINTS_DIR}/{request.request_id}.json"
    target = Path(request.project.root_path) / relative
    _atomic_json(
        target,
        {
            "schema_version": SCHEMA_VERSION,
            "checkpoint_id": request.request_id,
            "project_id": request.project.project_id,
            "captured_at": request.captured_at,
            "source": request.source,
            "blend_path": request.relative_blend_path,
            "size": request.size,
            "mtime_ns": request.mtime_ns,
            "metadata": request.metadata,
            "dependency_completeness": "saved_blend_only",
        },
    )
    return relative
