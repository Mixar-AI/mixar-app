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
from mixar.modules.common.job_queue import (
    Job, get_queue_with_listener, create_scene_flag_listener,
)
from mixar.modules.common.job_queue.constants import FEATURE_SCENE_GEN_HP
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

    def parse_submit_response(self, response) -> None:
        self._parse_standard_submit(response)

    def parse_poll_response(self, response):
        return self._parse_standard_poll(
            response, fail_message="Scene generation failed",
        )

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
    """Submit one SceneGenHPJob per (image, chain_id) tuple."""
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

_listener = create_scene_flag_listener(
    "mixie_scene_gen_hp_is_generating",
    batch_popup_title="Scene Gen HP batch complete",
)


def _get_hp_queue():
    return get_queue_with_listener(FEATURE_SCENE_GEN_HP, _listener)
