# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Image-to-3D Pro generation queue: concrete Job + enqueue helpers.

This module wires the generic ``FeatureQueue`` framework to the Hunyuan
Pro 3D generation service. All Pro params are snapshotted at enqueue
time, so the job is fully decoupled from any moodboard state once it
has been queued.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.services.generation_queue_service import get_generation_queue_service
from mixar.modules.common.job_queue import Job, JobState, get_queue
from mixar.modules.common.job_queue.constants import FEATURE_IMAGE_TO_3D_PRO
from mixar.modules.common.job_queue.core.queue_manager import FeatureQueue
from mixar.modules.common.utils.image_utils import compress_image_for_upload
from mixar.modules.hunyuan.constants import DEFAULT_FACE_COUNT

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class ImageTo3DProJob(Job):
    """Concrete Job for the Hunyuan 3D Pro generation flow."""

    # Internal state
    _processing_started: bool = False

    # Submission payload (snapshotted at enqueue time)
    image_bytes: bytes = b""
    image_filename: str = "image.png"
    prompt: Optional[str] = None
    generate_type: str = "Normal"
    model_version: str = "3.0"
    enable_pbr: bool = False
    face_count: Optional[int] = None
    polygon_type: Optional[str] = None
    multi_view_images: Optional[List[Tuple[bytes, str, str]]] = None

    # ------------------------------------------------------------------ #
    # Job interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error) -> None:
        service = get_generation_queue_service()
        # Build the SDK params payload that the backend dispatcher will use
        sdk_params = {
            "GenerateType": self.generate_type,
            "Model": self.model_version,
            "EnablePBR": self.enable_pbr,
        }
        if self.prompt:
            sdk_params["Prompt"] = self.prompt
        if self.face_count is not None:
            sdk_params["FaceCount"] = self.face_count
        if self.polygon_type:
            sdk_params["PolygonType"] = self.polygon_type
        payload = {"sdk_params": sdk_params}
        if self.image_bytes:
            payload["image_bytes_b64"] = __import__("base64").b64encode(self.image_bytes).decode()
            payload["image_filename"] = self.image_filename
        if self.multi_view_images:
            payload["multi_view_images"] = [
                {
                    "image_bytes_b64": __import__("base64").b64encode(img_bytes).decode(),
                    "filename": fname,
                    "view_type": vtype,
                }
                for img_bytes, fname, vtype in self.multi_view_images
            ]

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
        # Map backend statuses to the FeatureQueue protocol
        if status == "PENDING":
            # Still in queue — don't count against timeout
            return ("WAIT", [])
        if status in ("SUBMITTED", "POLLING"):
            # Active processing started — reset timeout clock if this is the
            # first time we see it (prevents queue wait eating into timeout)
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
            self.user_message = inner.get("user_message", "") or "Image to 3D failed"
            return ("FAIL", [])
        return ("WAIT", [])

    def on_imported(self, object_names: str) -> None:
        """Rename imported mesh to ``{image_name}_high`` and set up origin."""
        super().on_imported(object_names)
        import os
        base = os.path.splitext(self.label)[0] if "." in self.label else self.label
        # Sanitize: replace spaces/non-alnum with underscores
        import re
        base = re.sub(r'[^a-zA-Z0-9_]', '_', base)
        base = re.sub(r'_+', '_', base).strip('_') or "object"
        target = base + "_high"
        try:
            from mixar.modules.hunyuan.core.hunyuan_helpers import post_import_rename_and_setup
            post_import_rename_and_setup(object_names, target)
        except Exception as e:
            logger.warning("[ImageTo3DPro] post_import_rename_and_setup failed: %s", e)


# ---------------------------------------------------------------------------
# Enqueue helpers
# ---------------------------------------------------------------------------


def snapshot_shared_params(pro) -> dict:
    """Capture the Pro UI's shared (non-image) params into a dict."""
    return {
        "generate_type": pro.generate_type,
        "model_version": pro.model_version,
        "enable_pbr": pro.enable_pbr,
        "face_count": (
            pro.face_count if pro.face_count != DEFAULT_FACE_COUNT else None
        ),
        "polygon_type": (
            pro.polygon_type if pro.generate_type == 'LowPoly' else None
        ),
        "prompt": pro.prompt.strip() if pro.prompt else None,
    }


def enqueue_pro_job(
    *,
    image: Optional[bpy.types.Image],
    shared: dict,
    label: str,
    multi_views: Optional[List[Tuple[bytes, str, str]]] = None,
) -> Optional[ImageTo3DProJob]:
    """Build an ``ImageTo3DProJob`` and submit it to the Pro queue.

    ``image`` is compressed to bytes immediately, so the queue is not
    affected if the moodboard image is later removed/edited.
    """
    image_bytes = b""
    if image is not None:
        image_bytes = compress_image_for_upload(image)

    job = ImageTo3DProJob(
        feature_key=FEATURE_IMAGE_TO_3D_PRO,
        label=label,
        image_bytes=image_bytes,
        image_filename="image.png",
        prompt=shared.get("prompt") or None,
        generate_type=shared.get("generate_type", "Normal"),
        model_version=shared.get("model_version", "3.0"),
        enable_pbr=bool(shared.get("enable_pbr", False)),
        face_count=shared.get("face_count"),
        polygon_type=shared.get("polygon_type"),
        multi_view_images=multi_views,
    )
    queue = _get_pro_queue()
    if not queue.submit(job):
        logger.warning("[ImageTo3DPro] duplicate job rejected for label: %s", label)
        return None
    return job


# ---------------------------------------------------------------------------
# Queue listener: drives shared progress bar + is_generating scene flag
# ---------------------------------------------------------------------------


_listener_attached = False


def _on_queue_changed(queue: FeatureQueue) -> None:
    """Sync the moodboard ``image_to_3d`` progress bar to queue activity.

    Also fires the one-shot batch completion popup at the active→idle
    transition (Q18: a single summary popup, no per-job popups).
    """
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
    """Schedule a one-shot popup summarising the just-completed batch.

    Deferred via a 0-interval timer so the popup is created on a clean
    main-thread tick rather than from inside a queue listener callback.
    """

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
        return None  # one-shot

    try:
        bpy.app.timers.register(_popup, first_interval=0.0)
    except Exception as e:
        logger.debug("Could not schedule batch summary popup: %s", e)


def _get_pro_queue() -> FeatureQueue:
    global _listener_attached
    queue = get_queue(FEATURE_IMAGE_TO_3D_PRO)
    if not _listener_attached:
        queue.add_listener(_on_queue_changed)
        _listener_attached = True
    return queue
