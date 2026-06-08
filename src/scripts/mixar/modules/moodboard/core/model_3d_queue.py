# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Model 3D generation queue: concrete Job + enqueue helper.

Replaces the blocking 600s async call in ``image_to_3d_ops.py`` with a
proper submit+poll queue pattern via the unified generation queue.
"""

import base64
from dataclasses import dataclass
from typing import Optional

from mixar.config.logging_config import get_logger
from mixar.modules.common.api.services.generation_queue_service import get_generation_queue_service
from mixar.modules.common.job_queue import (
    Job, get_queue_with_listener, create_scene_flag_listener,
)
from mixar.modules.common.job_queue.constants import FEATURE_MODEL_3D

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class Model3DJob(Job):
    """Concrete Job for the Model 3D generation flow (Replicate/Tripo)."""

    _processing_started: bool = False
    image_bytes: bytes = b""
    image_filename: str = "image.png"
    model_name: str = ""
    prompt: Optional[str] = None
    parameters: Optional[dict] = None

    def submit(self, on_success, on_error) -> None:
        service = get_generation_queue_service()
        payload = {}
        if self.image_bytes:
            payload["image_bytes_b64"] = base64.b64encode(self.image_bytes).decode()
            payload["image_filename"] = self.image_filename
        if self.prompt:
            payload["prompt"] = self.prompt
        if self.parameters:
            payload["params"] = self.parameters

        service.enqueue(
            job_type="model_3d",
            model=self.model_name,
            payload=payload,
            on_success=on_success,
            on_error=on_error,
        )

    def parse_submit_response(self, response) -> None:
        self._parse_standard_submit(response)

    def parse_poll_response(self, response):
        return self._parse_standard_poll(
            response, fail_message="3D model generation failed",
        )


# ---------------------------------------------------------------------------
# Enqueue helper
# ---------------------------------------------------------------------------


def enqueue_model_3d_job(
    *,
    image_bytes: bytes,
    model_name: str,
    prompt: Optional[str] = None,
    parameters: Optional[dict] = None,
    label: str = "",
) -> Model3DJob:
    """Create a Model3DJob and submit it to the queue."""
    if not label:
        label = model_name or "model_3d"

    job = Model3DJob(
        feature_key=FEATURE_MODEL_3D,
        label=label,
        image_bytes=image_bytes,
        image_filename="image.png",
        model_name=model_name,
        prompt=prompt,
        parameters=parameters,
    )
    queue = _get_model_3d_queue()
    queue.submit(job)
    return job


# ---------------------------------------------------------------------------
# Queue listener
# ---------------------------------------------------------------------------

_listener = create_scene_flag_listener(
    "mixie_image_to_3d_is_generating",
    batch_popup_title="Image to 3D batch complete",
)


def _get_model_3d_queue():
    return get_queue_with_listener(FEATURE_MODEL_3D, _listener)
