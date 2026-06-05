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

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.services.generation_queue_service import get_generation_queue_service
from mixar.modules.common.job_queue import (
    Job, get_queue_with_listener, create_scene_flag_listener,
)
from mixar.modules.common.job_queue.constants import FEATURE_HUNYUAN_RAPID

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

    def parse_submit_response(self, response) -> None:
        self._parse_standard_submit(response)

    def parse_poll_response(self, response):
        return self._parse_standard_poll(response, fail_message="Generation failed")


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

_listener = create_scene_flag_listener("mixie_hunyuan_rapid_is_generating")


def _get_rapid_queue():
    return get_queue_with_listener(FEATURE_HUNYUAN_RAPID, _listener)
