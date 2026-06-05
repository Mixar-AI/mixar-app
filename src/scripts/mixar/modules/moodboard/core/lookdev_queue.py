# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lookdev (depth-to-image) generation queue: concrete Job + enqueue helper.

Wires the generic ``FeatureQueue`` framework to the depth-to-image
service via the unified generation queue.  The depth map bytes are
base64-encoded at enqueue time and uploaded to S3 by the backend
router before the handler runs.
"""

import base64 as _b64
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
from mixar.modules.common.job_queue.constants import FEATURE_LOOKDEV
from mixar.modules.common.job_queue.core.queue_manager import FeatureQueue

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class LookdevJob(Job):
    """Concrete Job for depth-to-image generation (sync type — result inline)."""

    # Submission payload (snapshotted at enqueue time)
    prompt: str = ""
    model: str = "flux-depth-dev"
    depth_map_b64: str = ""

    # Internal state (populated during parse_poll_response)
    _image_urls: List[str] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------------ #
    # Job interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error) -> None:
        service = get_generation_queue_service()
        payload = {
            "prompt": self.prompt,
            "depth_map_bytes_b64": self.depth_map_b64,
            "params": {},
        }
        service.enqueue(
            job_type="depth_to_image",
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
        self.depth_map_b64 = ""

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
            self.error = inner.get("error", "Lookdev generation failed")
            self.user_message = (
                inner.get("user_message", "") or "Lookdev generation failed"
            )
            return ("FAIL", [])
        return ("WAIT", [])

    def handle_result(self, result_files, on_done, on_error):
        """Download images in bg thread, add to moodboard on main thread."""
        if not self._image_urls:
            on_error("No image URLs in server response")
            return True

        download_images_to_moodboard(
            urls=list(self._image_urls),
            name_prefix="lookdev",
            prompt=self.prompt,
            job_id=self.id,
            on_done=on_done,
            on_error=on_error,
            undo_message="Blockout to Render",
        )
        return True

    def get_poll_interval(self):
        return 3.0


# ---------------------------------------------------------------------------
# Enqueue helper
# ---------------------------------------------------------------------------


def enqueue_lookdev_job(
    *,
    prompt: str,
    depth_map_bytes: bytes,
    model: str = "flux-depth-dev",
) -> Optional[LookdevJob]:
    """Build a ``LookdevJob`` and submit it to the queue."""
    job = LookdevJob(
        feature_key=FEATURE_LOOKDEV,
        label=f"Lookdev: {prompt[:40]}",
        prompt=prompt,
        model=model,
        depth_map_b64=_b64.b64encode(depth_map_bytes).decode(),
    )
    queue = _get_lookdev_queue()
    if not queue.submit(job):
        logger.warning("[Lookdev] duplicate job rejected: %s", job.label)
        return None
    return job


# ---------------------------------------------------------------------------
# Queue listener: drives is_generating scene flag
# ---------------------------------------------------------------------------


def _on_queue_changed(queue: FeatureQueue) -> None:
    """Sync lookdev generating flag to queue activity."""
    try:
        scene = bpy.context.scene
    except Exception:
        return
    if scene is None:
        return

    has_work = queue.has_active_work()
    was_generating = bool(getattr(scene, "mixie_lookdev_is_generating", False))

    if has_work and not was_generating:
        try:
            scene.mixie_lookdev_is_generating = True
            if hasattr(scene, "mixie_lookdev_error"):
                scene.mixie_lookdev_error = ""
        except (AttributeError, TypeError):
            pass
        from ...core.generate_progress import start_progress
        start_progress("lookdev")
        return

    if not has_work and was_generating:
        try:
            scene.mixie_lookdev_is_generating = False
        except (AttributeError, TypeError):
            pass
        from ...core.generate_progress import complete_progress
        complete_progress("lookdev")

        try:
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    area.tag_redraw()
        except Exception:
            pass


def _get_lookdev_queue():
    return get_queue_with_listener(FEATURE_LOOKDEV, _on_queue_changed)
