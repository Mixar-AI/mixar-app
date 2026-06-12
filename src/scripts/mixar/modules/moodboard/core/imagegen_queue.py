# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ImageGen generation queue: concrete Job + enqueue helpers.

Wires the generic ``FeatureQueue`` framework to the image generation
service. All params are snapshotted at enqueue time so the job is fully
decoupled from moodboard UI state once queued.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

import bpy

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.services.generation_queue_service import (
    get_generation_queue_service,
)
from mixar.modules.common.job_queue import Job, get_queue
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
        if not isinstance(inner, dict):
            inner = {}

        # Sync type: result may be inline in the submit response
        self.backend_job_id = inner.get("job_id", "") or ""
        status = inner.get("status", "")
        result = inner.get("result") or {}

        if status == "DONE" and isinstance(result, dict):
            # Extract image URLs from inline result
            self._extract_image_urls(result)

        if not self.backend_job_id and not self._image_urls:
            raise ValueError("Enqueue response missing job_id")

        # Release large payload memory after successful submission
        self.reference_images_b64 = []

    def should_skip_poll(self) -> bool:
        return bool(self._image_urls)

    def parse_poll_response(self, response):
        data = getattr(response, "data", None) or {}
        inner = data.get("data", data) if isinstance(data, dict) else {}
        if not isinstance(inner, dict):
            return ("WAIT", [])

        status = inner.get("status", "")
        self.backend_status = status

        if status == "PENDING":
            return ("WAIT", [])
        if status in ("SUBMITTED", "POLLING"):
            return ("RUN", [])
        if status == "DONE":
            result = inner.get("result") or {}
            if isinstance(result, dict):
                self._extract_image_urls(result)
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

        urls = list(self._image_urls)
        prompt = self.prompt
        job_id = self.id

        def _bg_download():
            try:
                from mixar.modules.common.utils.image_utils import (
                    load_image_from_url,
                )

                downloaded = []
                for i, url in enumerate(urls):
                    try:
                        timestamp = int(time.time())
                        name = f"imagegen_{timestamp}_{i}"
                        img = load_image_from_url(url, name)
                        downloaded.append(img)
                    except Exception as e:
                        logger.error("Failed to download image %d: %s", i, e)

                def _apply():
                    if not downloaded:
                        on_error("Failed to download generated images")
                        return None
                    from mixar.modules.common.utils.image_utils import (
                        add_image_to_moodboard,
                    )

                    for img in downloaded:
                        try:
                            add_image_to_moodboard(img, prompt, job_handle=job_id)
                        except Exception as e:
                            logger.error("Failed to add image to moodboard: %s", e)

                    names = ", ".join(img.name for img in downloaded)
                    bpy.ops.ed.undo_push(message="Generate Image")
                    on_done(names)
                    return None

                bpy.app.timers.register(_apply, first_interval=0.0)
            except Exception as e:
                err = f"Unexpected error during image download: {e}"
                logger.error("[ImageGen] %s", err)

                def _fail():
                    on_error(err)
                    return None

                bpy.app.timers.register(_fail, first_interval=0.0)

        threading.Thread(target=_bg_download, daemon=True).start()
        return True

    def get_poll_interval(self):
        return 3.0

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _extract_image_urls(self, result: dict) -> None:
        """Extract image URLs from the result dict."""
        # Unwrap nested data/result
        data = result
        if "data" in data and isinstance(data["data"], dict):
            data = data["data"]
        if "result" in data and isinstance(data["result"], dict):
            data = data["result"]

        images = []
        for img_item in data.get("images", []):
            if isinstance(img_item, dict) and "url" in img_item:
                images.append(img_item["url"])
            elif isinstance(img_item, str):
                images.append(img_item)

        if not images:
            single_url = data.get("image_url")
            if single_url:
                images.append(single_url)

        self._image_urls = images


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


_listener_attached = False


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

        # Redraw MIXIE sidebar so new images / error state are visible
        try:
            for area in bpy.context.screen.areas:
                if area.type == 'MIXIE':
                    area.tag_redraw()
        except Exception:
            pass


def _get_imagegen_queue() -> FeatureQueue:
    global _listener_attached
    queue = get_queue(FEATURE_IMAGEGEN)
    if not _listener_attached:
        queue.add_listener(_on_queue_changed)
        _listener_attached = True
    return queue
