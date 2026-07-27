# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Model 3D API service.

Currently exposes turnaround / model-sheet view detection, which splits a
single image containing several drawings of the same subject into labelled
per-view crops so they can be submitted as one multi-view generation job
instead of being modelled as a single garbled object.
"""

from typing import Callable, Optional

from ..constants import APIModule
from ..request_queue import AsyncResponse
from ..response import APIResponse
from .base_service import BaseService


class Model3DService(BaseService):
    """
    Model 3D service.

    Endpoints (/api/v1/model-3d-generation/):
    - POST /detect-views - Split a turnaround sheet into per-view crops
    """

    @property
    def module(self) -> APIModule:
        """Return the MODEL_3D_GEN module."""
        return APIModule.MODEL_3D_GEN

    # ========================================================================
    # DETECT VIEWS (TURNAROUND / MODEL SHEET SPLIT)
    # ========================================================================

    def detect_views(
        self,
        image_bytes: bytes,
        filename: str = "image.png",
        timeout: float = 120.0,
    ) -> APIResponse:
        """
        Split a turnaround / model-sheet image into per-view crops.

        Credit-charged (feature key ``turnaround_detect``): a 402 means the
        user is out of credits. A 502 means detection itself failed and the
        credits were refunded — retrying is reasonable. A 200 with
        ``is_turnaround: false`` is NOT an error; it means the image is an
        ordinary single image and should take the existing path.

        Args:
            image_bytes: Image data (PNG, JPEG or WEBP)
            filename: Filename for the upload

        Returns:
            APIResponse whose data envelope contains:
            - is_turnaround: bool — False means "ordinary single image",
              in which case ``panels`` is empty
            - panels: list of {view_type, s3_key, preview_url, confidence,
              width, height}. When ``is_turnaround`` is True exactly one
              panel has view_type == "front" and it is always panels[0].
              ``s3_key`` is the durable handle to forward verbatim at submit
              time; ``preview_url`` is presigned and short-lived (1h).
        """
        files = {"image": (filename, image_bytes, _mime_type(filename))}
        return self._client.post(
            self._endpoint("detect-views"), files=files, timeout=timeout
        )

    def detect_views_async(
        self,
        image_bytes: bytes,
        filename: str = "image.png",
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
        timeout: float = 120.0,
    ) -> str:
        """
        Split a turnaround sheet into per-view crops asynchronously.

        The request runs on a background thread; callbacks are delivered on
        Blender's main thread by the shared request queue.

        Returns:
            Request ID for tracking
        """
        files = {"image": (filename, image_bytes, _mime_type(filename))}
        return self._client.request_async(
            "POST",
            self._endpoint("detect-views"),
            files=files,
            timeout=timeout,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )


def _mime_type(filename: str) -> str:
    """Determine MIME type from filename."""
    lower = filename.lower()
    if lower.endswith(('.jpg', '.jpeg')):
        return "image/jpeg"
    if lower.endswith('.webp'):
        return "image/webp"
    return "image/png"


# Singleton instance
_model_3d_service: Optional[Model3DService] = None


def get_model_3d_service() -> Model3DService:
    """Get or create the global Model 3D service instance."""
    global _model_3d_service
    if _model_3d_service is None:
        _model_3d_service = Model3DService()
    return _model_3d_service
