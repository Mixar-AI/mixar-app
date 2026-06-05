# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ImageGen generation queue: concrete Job + enqueue helpers.

Wires the generic ``FeatureQueue`` framework to the image generation
service. All params are snapshotted at enqueue time so the job is fully
decoupled from moodboard UI state once queued.
"""

from dataclasses import dataclass, field
from typing import List, Optional

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.services.generation_queue_service import (
    get_generation_queue_service,
)
from mixar.modules.common.job_queue import (
    Job,
    get_queue_with_listener,
    extract_image_urls,
    download_images_to_moodboard,
)
from mixar.modules.common.job_queue.constants import FEATURE_IMAGEGEN
from mixar.modules.common.job_queue.core.queue_manager import FeatureQueue

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class ImageGenJob(Job):
    """Concrete Job for AI image generation (sync type — result inline)."""

    # Submission payload (snapshotted at enqueue time)
    prompt: str = ""
    model: str = ""
    style: str = "none"
    aspect_ratio: str = "1:1"
    resolution: str = "1K"
    num_images: int = 1
    negative_prompt: Optional[str] = None
    reference_images_b64: List[str] = field(default_factory=list)

    # Internal state (populated during parse_poll_response)
    _image_urls: List[str] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------------ #
    # Job interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error) -> None:
        service = get_generation_queue_service()
        payload = {
            "prompt": self.prompt,
            "params": {
                "style": self.style,
                "aspect_ratio": self.aspect_ratio,
                "resolution": self.resolution,
                "number_of_images": self.num_images,
            },
        }
        if self.negative_prompt:
            payload["params"]["negative_prompt"] = self.negative_prompt
        if self.reference_images_b64:
            payload["reference_images_b64"] = self.reference_images_b64

        service.enqueue(
            job_type="image_gen",
            model=self.model,
            payload=payload,
            on_success=on_success,
            on_error=on_error,
        )

    def parse_submit_response(self, response) -> None:
        inner = self._unwrap_response(response)
        self.backend_job_id = inner.get("job_id", "") or ""

        status = inner.get("status", "")
        result = inner.get("result") or {}
        if status == "DONE" and isinstance(result, dict):
            self._image_urls = extract_image_urls(result)

        if not self.backend_job_id and not self._image_urls:
            raise ValueError("Enqueue response missing job_id")

        # Release large payload memory after successful submission
        self.reference_images_b64 = []

    def should_skip_poll(self) -> bool:
        return bool(self._image_urls)

    def parse_poll_response(self, response):
        inner = self._unwrap_response(response)
        status = inner.get("status", "")
        self.backend_status = status

        if status == "PENDING":
            return ("WAIT", [])
        if status in ("SUBMITTED", "POLLING"):
            return ("RUN", [])
        if status == "DONE":
            result = inner.get("result") or {}
            if isinstance(result, dict):
                self._image_urls = extract_image_urls(result)
            return ("DONE", [])
        if status == "FAILED":
            self.error = inner.get("error", "Image generation failed")
            self.user_message = inner.get("user_message", "") or "Image generation failed"
            return ("FAIL", [])
        return ("WAIT", [])

    def handle_result(self, result_files, on_done, on_error):
        """Download images in bg thread, add to moodboard on main thread."""
        if not self._image_urls:
            on_error("No image URLs in server response")
            return True

        download_images_to_moodboard(
            urls=list(self._image_urls),
            name_prefix="imagegen",
            prompt=self.prompt,
            job_id=self.id,
            on_done=on_done,
            on_error=on_error,
            undo_message="Generate Image",
        )
        return True

    def get_poll_interval(self):
        return 3.0


# ---------------------------------------------------------------------------
# Enqueue helpers
# ---------------------------------------------------------------------------


def enqueue_imagegen_job(
    *,
    prompt: str,
    model: str,
    style: str = "none",
    aspect_ratio: str = "1:1",
    resolution: str = "1K",
    num_images: int = 1,
    negative_prompt: Optional[str] = None,
    reference_images_b64: Optional[List[str]] = None,
) -> Optional[ImageGenJob]:
    """Build an ``ImageGenJob`` and submit it to the queue."""
    job = ImageGenJob(
        feature_key=FEATURE_IMAGEGEN,
        label=f"ImageGen: {prompt[:40]}",
        prompt=prompt,
        model=model,
        style=style,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        num_images=num_images,
        negative_prompt=negative_prompt,
        reference_images_b64=reference_images_b64 or [],
    )
    queue = _get_imagegen_queue()
    if not queue.submit(job):
        logger.warning("[ImageGen] duplicate job rejected: %s", job.label)
        return None
    return job


# ---------------------------------------------------------------------------
# Queue listener: drives progress bar + is_generating scene flag
# ---------------------------------------------------------------------------


def _on_queue_changed(queue: FeatureQueue) -> None:
    """Sync imagegen progress bar to queue activity."""
    try:
        scene = bpy.context.scene
    except Exception:
        return
    if scene is None:
        return

    has_work = queue.has_active_work()
    was_generating = bool(getattr(scene, "mixie_imagegen_is_generating", False))

    if has_work and not was_generating:
        try:
            scene.mixie_imagegen_is_generating = True
            scene.mixie_imagegen_error = ""
        except (AttributeError, TypeError):
            pass
        return

    if not has_work and was_generating:
        try:
            scene.mixie_imagegen_is_generating = False
        except (AttributeError, TypeError):
            pass

        try:
            for area in bpy.context.screen.areas:
                if area.type == 'MIXIE':
                    area.tag_redraw()
        except Exception:
            pass


def _get_imagegen_queue():
    return get_queue_with_listener(FEATURE_IMAGEGEN, _on_queue_changed)
