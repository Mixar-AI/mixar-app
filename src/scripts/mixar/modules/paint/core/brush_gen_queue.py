# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Brush texture generation queue: concrete Job + enqueue helper.

Wires the generic ``FeatureQueue`` framework to the brush texture
generation service via the unified generation queue.  Uses the same
Gemini models as imagegen but with brush-specific system prompt and
hardcoded params (1:1, single image).
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
from mixar.modules.common.job_queue.constants import FEATURE_BRUSH_GEN

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class BrushGenJob(Job):
    """Concrete Job for brush texture generation (sync type — result inline)."""

    prompt: str = ""
    model: str = "flash"
    reference_image_b64: str = ""

    _image_urls: List[str] = field(default_factory=list, repr=False)

    # ------------------------------------------------------------------ #
    # Job interface
    # ------------------------------------------------------------------ #

    def submit(self, on_success, on_error) -> None:
        service = get_generation_queue_service()
        payload = {"prompt": self.prompt}
        if self.reference_image_b64:
            payload["reference_image_bytes_b64"] = self.reference_image_b64

        service.enqueue(
            job_type="brush_gen",
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

        self.reference_image_b64 = ""

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
            self.error = inner.get("error", "Brush generation failed")
            self.user_message = (
                inner.get("user_message", "") or "Brush generation failed"
            )
            return ("FAIL", [])
        return ("WAIT", [])

    def handle_result(self, result_files, on_done, on_error):
        """Download image in bg thread, add to moodboard on main thread."""
        if not self._image_urls:
            on_error("No image URLs in server response")
            return True

        download_images_to_moodboard(
            urls=list(self._image_urls),
            name_prefix="brush_gen",
            prompt=self.prompt,
            job_id=self.id,
            on_done=on_done,
            on_error=on_error,
        )
        return True

    def get_poll_interval(self):
        return 3.0


# ---------------------------------------------------------------------------
# Enqueue helper
# ---------------------------------------------------------------------------


def enqueue_brush_gen_job(
    *,
    prompt: str,
    model: str = "flash",
    reference_image_bytes: Optional[bytes] = None,
) -> Optional[BrushGenJob]:
    """Build a ``BrushGenJob`` and submit it to the queue."""
    ref_b64 = ""
    if reference_image_bytes:
        ref_b64 = _b64.b64encode(reference_image_bytes).decode()

    job = BrushGenJob(
        feature_key=FEATURE_BRUSH_GEN,
        label=f"Brush: {prompt[:40]}",
        prompt=prompt,
        model=model,
        reference_image_b64=ref_b64,
    )
    queue = _get_brush_gen_queue()
    if not queue.submit(job):
        logger.warning("[BrushGen] duplicate job rejected: %s", job.label)
        return None
    return job


# ---------------------------------------------------------------------------
# Queue listener
# ---------------------------------------------------------------------------


def _on_queue_changed(queue) -> None:
    """Sync brush gen progress to queue activity."""
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                area.tag_redraw()
    except Exception:
        pass


def _get_brush_gen_queue():
    return get_queue_with_listener(FEATURE_BRUSH_GEN, _on_queue_changed)
