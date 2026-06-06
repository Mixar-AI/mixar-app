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
from mixar.modules.common.job_queue import Job, JobState, get_queue
from mixar.modules.common.job_queue.constants import FEATURE_SCENE_GEN_LP
from mixar.modules.common.job_queue.core.queue_manager import FeatureQueue
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
            self.user_message = inner.get("user_message", "") or "Scene generation failed"
            return ("FAIL", [])
        return ("WAIT", [])

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

        # Stamp chain_id on all imported mesh objects
        if self.chain_id:
            # After rename, try both original names and derived target
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
    """Fan out selected mesh objects into per-object LP queue jobs.

    Each object is exported individually. Files exceeding the backend size
    limit are skipped with a warning.
    """
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

_listener_attached = False


def _on_queue_changed(queue: FeatureQueue) -> None:
    try:
        scene = bpy.context.scene
    except Exception:
        return
    if scene is None:
        return

    has_work = queue.has_active_work()
    was_generating = bool(getattr(scene, "mixie_scene_gen_lp_is_generating", False))

    if has_work and not was_generating:
        try:
            scene.mixie_scene_gen_lp_is_generating = True
        except (AttributeError, TypeError):
            pass
        return

    if not has_work and was_generating:
        try:
            scene.mixie_scene_gen_lp_is_generating = False
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
            wm.popup_menu(_draw, title="Scene Gen LP batch complete", icon='INFO')
        except Exception as e:
            logger.debug("Batch summary popup failed: %s", e)
        return None

    try:
        bpy.app.timers.register(_popup, first_interval=0.0)
    except Exception as e:
        logger.debug("Could not schedule batch summary popup: %s", e)


def _get_lp_queue() -> FeatureQueue:
    global _listener_attached
    queue = get_queue(FEATURE_SCENE_GEN_LP)
    if not _listener_attached:
        queue.add_listener(_on_queue_changed)
        _listener_attached = True
    return queue
