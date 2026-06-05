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
from mixar.modules.common.job_queue import (
    Job, get_queue_with_listener, create_scene_flag_listener,
)
from mixar.modules.common.job_queue.constants import FEATURE_IMAGE_TO_3D_PRO
from mixar.modules.common.utils.image_utils import compress_image_for_upload
from mixar.modules.hunyuan.constants import DEFAULT_FACE_COUNT

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class ImageTo3DProJob(Job):
    """Concrete Job for the Hunyuan 3D Pro generation flow."""

    _processing_started: bool = False

    image_bytes: bytes = b""
    image_filename: str = "image.png"
    prompt: Optional[str] = None
    generate_type: str = "Normal"
    model_version: str = "3.0"
    enable_pbr: bool = False
    face_count: Optional[int] = None
    polygon_type: Optional[str] = None
    multi_view_images: Optional[List[Tuple[bytes, str, str]]] = None

    def submit(self, on_success, on_error) -> None:
        service = get_generation_queue_service()
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

    def parse_submit_response(self, response) -> None:
        self._parse_standard_submit(response)

    def parse_poll_response(self, response):
        return self._parse_standard_poll(
            response, fail_message="Image to 3D failed",
        )

    def on_imported(self, object_names: str) -> None:
        """Rename imported mesh to ``{image_name}_high`` and set up origin."""
        super().on_imported(object_names)
        import os
        base = os.path.splitext(self.label)[0] if "." in self.label else self.label
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
    """Build an ``ImageTo3DProJob`` and submit it to the Pro queue."""
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
# Queue listener
# ---------------------------------------------------------------------------

_listener = create_scene_flag_listener(
    "mixie_image_to_3d_is_generating",
    batch_popup_title="Image to 3D batch complete",
)


def _get_pro_queue():
    return get_queue_with_listener(FEATURE_IMAGE_TO_3D_PRO, _listener)
