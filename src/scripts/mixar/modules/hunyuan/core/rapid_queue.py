# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hunyuan Rapid generation queue: concrete Job + enqueue helper.

Mirrors ``retopology_queue.py`` but for the Hunyuan Rapid 3D generation
service. Supports both text-prompt and image-based generation.
"""

import base64
from dataclasses import dataclass
from typing import Optional

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.services.generation_queue_service import get_generation_queue_service
from mixar.modules.common.job_queue import Job, get_queue
from mixar.modules.common.job_queue.constants import FEATURE_HUNYUAN_RAPID
from mixar.modules.common.job_queue.core.queue_manager import FeatureQueue
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class RapidJob(Job):
    """Concrete Job for the Hunyuan 3D Rapid generation flow."""

    _processing_started: bool = False
    image_bytes: bytes = b""
    image_filename: str = "image.png"
    prompt: str = ""
    result_format: Optional[str] = None
    enable_pbr: bool = False
    enable_geometry: bool = False

    # ------------------------------------------------------------------ #
    # Job interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error) -> None:
        service = get_generation_queue_service()
        sdk_params = {
            "EnablePBR": self.enable_pbr,
            "EnableGeometry": self.enable_geometry,
        }
        if self.result_format:
            sdk_params["ResultFormat"] = self.result_format

        payload = {"sdk_params": sdk_params}

        if self.prompt:
            sdk_params["Prompt"] = self.prompt
        if self.image_bytes:
            payload["image_bytes_b64"] = base64.b64encode(self.image_bytes).decode()
            payload["image_filename"] = self.image_filename

        service.enqueue(
            job_type="hunyuan_rapid",
            model="hunyuan_rapid",
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


def enqueue_rapid_job(
    *,
    prompt: str = "",
    image_bytes: bytes = b"",
    image_filename: str = "image.png",
    result_format: Optional[str] = None,
    enable_pbr: bool = False,
    enable_geometry: bool = False,
    label: str = "",
) -> RapidJob:
    """Validate inputs, create a RapidJob, and submit it to the queue."""
    has_prompt = bool(prompt.strip())
    has_image = bool(image_bytes)

    if not has_prompt and not has_image:
        raise ValueError("Provide either a prompt or an image")
    if has_prompt and has_image:
        raise ValueError("Prompt and image are mutually exclusive")

    if not label:
        label = prompt.strip()[:40] if has_prompt else image_filename

    job = RapidJob(
        feature_key=FEATURE_HUNYUAN_RAPID,
        label=label,
        prompt=prompt.strip() if has_prompt else "",
        image_bytes=image_bytes,
        image_filename=image_filename,
        result_format=result_format if result_format and result_format != "glb" else None,
        enable_pbr=enable_pbr,
        enable_geometry=enable_geometry,
    )
    queue = _get_rapid_queue()
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
    was_generating = bool(getattr(scene, "mixie_hunyuan_rapid_is_generating", False))

    if has_work and not was_generating:
        try:
            scene.mixie_hunyuan_rapid_is_generating = True
        except (AttributeError, TypeError):
            pass
        return

    if not has_work and was_generating:
        try:
            scene.mixie_hunyuan_rapid_is_generating = False
        except (AttributeError, TypeError):
            pass


def _get_rapid_queue() -> FeatureQueue:
    global _listener_attached
    queue = get_queue(FEATURE_HUNYUAN_RAPID)
    if not _listener_attached:
        queue.add_listener(_on_queue_changed)
        _listener_attached = True
    return queue
