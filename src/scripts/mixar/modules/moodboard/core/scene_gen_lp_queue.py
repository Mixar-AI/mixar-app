# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene Gen LP queue: Retopology for Scene Gen Experimental.

Mirrors ``hunyuan/core/retopology_queue.py`` but uses its own
``scene_gen_lp`` feature queue so it is completely independent from the
standalone Retopology feature.  Each job carries a ``chain_id`` that is
stamped on the imported mesh as a custom property (``mixar_chain_id``).
"""

import os
import re
from dataclasses import dataclass
from typing import Optional

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.services.generation_queue_service import get_generation_queue_service
from mixar.modules.common.job_queue import (
    Job, get_queue_with_listener, create_scene_flag_listener,
)
from mixar.modules.common.job_queue.constants import FEATURE_SCENE_GEN_LP
from mixar.modules.hunyuan.constants import MAX_FILE_SIZE_TOPOLOGY

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class SceneGenLPJob(Job):
    """Concrete Job for Scene Gen LP (Hunyuan Topology) retopology."""

    _processing_started: bool = False
    file_bytes: bytes = b""
    file_filename: str = "export.glb"
    chain_id: str = ""
    polygon_type: Optional[str] = None
    face_level: Optional[str] = None
    post_process: bool = True

    def submit(self, on_success, on_error) -> None:
        service = get_generation_queue_service()
        sdk_params = {}
        if self.polygon_type:
            sdk_params["PolygonType"] = self.polygon_type
        if self.face_level:
            sdk_params["FaceLevel"] = self.face_level

        payload = {
            "sdk_params": sdk_params,
            "input_name": self.label,
            "post_process": self.post_process,
            "file_bytes_b64": __import__("base64").b64encode(self.file_bytes).decode(),
            "file_filename": self.file_filename,
        }

        service.enqueue(
            job_type="retopology",
            model="hunyuan_topology",
            payload=payload,
            on_success=on_success,
            on_error=on_error,
        )

    def parse_submit_response(self, response) -> None:
        self._parse_standard_submit(response)

    def parse_poll_response(self, response):
        return self._parse_standard_poll(
            response, fail_message="Scene generation failed",
        )

    def on_imported(self, object_names: str) -> None:
        """Handle imported retopo mesh and stamp chain_id."""
        super().on_imported(object_names)

        names = [n.strip() for n in object_names.split(",") if n.strip()]
        has_low_suffix = any("_low" in n for n in names)

        if has_low_suffix:
            logger.info("[SceneGenLP] Post-processed mesh detected, skipping client-side cleanup")
        else:
            logger.warning("[SceneGenLP] Unprocessed mesh detected, applying client-side fallback")
            name = os.path.splitext(self.label)[0] if "." in self.label else self.label
            for suffix in ("_high", "_High", "_HIGH"):
                if name.endswith(suffix):
                    name = name[:-len(suffix)]
                    break
            target = name + "_low"
            try:
                from mixar.modules.hunyuan.core.hunyuan_helpers import (
                    post_import_rename_and_setup,
                )
                post_import_rename_and_setup(object_names, target, smart_uv=True)
            except Exception as e:
                logger.warning("[SceneGenLP] post_import_rename_and_setup failed: %s", e)

        if self.chain_id:
            base = re.sub(r'[^a-zA-Z0-9_]', '_', self.label)
            base = re.sub(r'_+', '_', base).strip('_') or "object"
            for suffix in ("_high", "_High", "_HIGH"):
                if base.endswith(suffix):
                    base = base[:-len(suffix)]
                    break
            possible_names = list(names) + [base + "_low"]
            for name in possible_names:
                obj = bpy.data.objects.get(name)
                if obj is not None:
                    obj["mixar_chain_id"] = self.chain_id


# ---------------------------------------------------------------------------
# Enqueue helpers
# ---------------------------------------------------------------------------


def enqueue_scene_gen_lp_jobs(
    *,
    context,
    objects_with_chain_ids: list,
    shared_params: dict,
    operator=None,
) -> list:
    """Fan out selected mesh objects into per-object LP queue jobs."""
    from mixar.modules.hunyuan.core.retopology_queue import _export_single_object

    queue = _get_lp_queue()
    enqueued: list = []

    for obj, chain_id in objects_with_chain_ids:
        if obj.type != 'MESH':
            continue
        try:
            file_bytes, filename = _export_single_object(context, obj)
        except Exception as e:
            msg = f"Failed to export '{obj.name}': {e}"
            logger.warning(msg)
            if operator is not None:
                operator.report({'WARNING'}, msg)
            continue

        if len(file_bytes) > MAX_FILE_SIZE_TOPOLOGY:
            size_mb = len(file_bytes) / (1024 * 1024)
            msg = (
                f"Skipping '{obj.name}': exported file is {size_mb:.1f}MB "
                f"(max {MAX_FILE_SIZE_TOPOLOGY // (1024 * 1024)}MB)"
            )
            logger.warning(msg)
            if operator is not None:
                operator.report({'WARNING'}, msg)
            continue

        job = SceneGenLPJob(
            feature_key=FEATURE_SCENE_GEN_LP,
            label=obj.name,
            file_bytes=file_bytes,
            file_filename=filename,
            chain_id=chain_id,
            polygon_type=shared_params.get("polygon_type"),
            face_level=shared_params.get("face_level"),
            post_process=shared_params.get("post_process", True),
        )
        queue.submit(job)
        enqueued.append(job)

    return enqueued


# ---------------------------------------------------------------------------
# Queue listener
# ---------------------------------------------------------------------------

_listener = create_scene_flag_listener(
    "mixie_scene_gen_lp_is_generating",
    batch_popup_title="Scene Gen LP batch complete",
)


def _get_lp_queue():
    return get_queue_with_listener(FEATURE_SCENE_GEN_LP, _listener)
