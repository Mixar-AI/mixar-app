# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene Gen HP queue: Image-to-3D Pro generation for Scene Gen Experimental.

Mirrors ``image_to_3d_queue.py`` but uses its own ``scene_gen_hp`` feature
queue so it is completely independent from the standalone Image-to-3D Pro
feature.  Each job carries a ``chain_id`` that is stamped on the imported
mesh as a custom property (``mixar_chain_id``).
"""

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.services.generation_queue_service import get_generation_queue_service
from mixar.modules.common.job_queue import Job, JobState, get_queue
from mixar.modules.common.job_queue.constants import FEATURE_SCENE_GEN_HP
from mixar.modules.common.job_queue.core.queue_manager import FeatureQueue
from mixar.modules.common.utils.image_utils import compress_image_for_upload

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class SceneGenHPJob(Job):
    """Concrete Job for Scene Gen HP (Hunyuan 3D Pro) generation."""

    _processing_started: bool = False
    image_bytes: bytes = b""
    image_filename: str = "image.png"
    chain_id: str = ""
    generate_type: str = "Normal"
    model_version: str = "3.0"
    enable_pbr: bool = False
    face_count: Optional[int] = None
    polygon_type: Optional[str] = None

    def submit(self, on_success, on_error) -> None:
        service = get_generation_queue_service()
        sdk_params = {
            "GenerateType": self.generate_type,
            "Model": self.model_version,
            "EnablePBR": self.enable_pbr,
        }
        if self.face_count is not None:
            sdk_params["FaceCount"] = self.face_count
        if self.polygon_type:
            sdk_params["PolygonType"] = self.polygon_type

        payload = {"sdk_params": sdk_params}
        if self.image_bytes:
            payload["image_bytes_b64"] = __import__("base64").b64encode(self.image_bytes).decode()
            payload["image_filename"] = self.image_filename

        model_key = "hunyuan_pro_v3.1" if self.model_version == "3.1" else "hunyuan_pro_v3"
        service.enqueue(
            job_type="image_to_3d",
            model=model_key,
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
        """Rename imported mesh and stamp chain_id."""
        super().on_imported(object_names)
        base = re.sub(r'[^a-zA-Z0-9_]', '_', self.label)
        base = re.sub(r'_+', '_', base).strip('_') or "object"
        target = base + "_high"
        try:
            from mixar.modules.hunyuan.core.hunyuan_helpers import (
                post_import_rename_and_setup,
            )
            post_import_rename_and_setup(object_names, target)
        except Exception as e:
            logger.warning("[SceneGenHP] post_import_rename_and_setup failed: %s", e)

        # Stamp chain_id on all imported mesh objects
        if self.chain_id:
            names = [n.strip() for n in object_names.split(",") if n.strip()]
            for name in names:
                obj = bpy.data.objects.get(name)
                if obj is None:
                    obj = bpy.data.objects.get(target)
                if obj is not None:
                    obj["mixar_chain_id"] = self.chain_id


# ---------------------------------------------------------------------------
# Enqueue helpers
# ---------------------------------------------------------------------------


def enqueue_scene_gen_hp_jobs(
    *,
    images_with_chain_ids: List[Tuple[bpy.types.Image, str]],
    shared_params: dict,
    operator=None,
) -> list:
    """Submit one SceneGenHPJob per (image, chain_id) tuple.

    Images are compressed to bytes immediately so the queue is decoupled
    from moodboard state.
    """
    queue = _get_hp_queue()
    enqueued: list = []

    from mixar.modules.hunyuan.constants import DEFAULT_FACE_COUNT

    for image, chain_id in images_with_chain_ids:
        try:
            image_bytes = compress_image_for_upload(image)
        except Exception as e:
            msg = f"Failed to compress '{image.name}': {e}"
            logger.warning(msg)
            if operator is not None:
                operator.report({'WARNING'}, msg)
            continue

        face_count = shared_params.get("face_count")
        if face_count == DEFAULT_FACE_COUNT:
            face_count = None

        job = SceneGenHPJob(
            feature_key=FEATURE_SCENE_GEN_HP,
            label=image.name,
            image_bytes=image_bytes,
            chain_id=chain_id,
            generate_type=shared_params.get("generate_type", "Normal"),
            model_version=shared_params.get("model_version", "3.0"),
            enable_pbr=bool(shared_params.get("enable_pbr", False)),
            face_count=face_count,
            polygon_type=(
                shared_params.get("polygon_type")
                if shared_params.get("generate_type") == "LowPoly"
                else None
            ),
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
    was_generating = bool(getattr(scene, "mixie_scene_gen_hp_is_generating", False))

    if has_work and not was_generating:
        try:
            scene.mixie_scene_gen_hp_is_generating = True
        except (AttributeError, TypeError):
            pass
        return

    if not has_work and was_generating:
        try:
            scene.mixie_scene_gen_hp_is_generating = False
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
            wm.popup_menu(_draw, title="Scene Gen HP batch complete", icon='INFO')
        except Exception as e:
            logger.debug("Batch summary popup failed: %s", e)
        return None

    try:
        bpy.app.timers.register(_popup, first_interval=0.0)
    except Exception as e:
        logger.debug("Could not schedule batch summary popup: %s", e)


def _get_hp_queue() -> FeatureQueue:
    global _listener_attached
    queue = get_queue(FEATURE_SCENE_GEN_HP)
    if not _listener_attached:
        queue.add_listener(_on_queue_changed)
        _listener_attached = True
    return queue
