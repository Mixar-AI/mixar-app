# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Reconstruction API service.

Provides GLB download from presigned URLs for scene reconstruction results.
"""

import time
from typing import Optional

import requests

from mixar.config.logging_config import get_logger

from ..constants import APIModule
from .base_service import BaseService

logger = get_logger(__name__)


class SceneReconService(BaseService):
    """Scene Reconstruction service — GLB download from presigned URLs."""

    @property
    def module(self) -> APIModule:
        """Return the SCENE_RECONSTRUCTION module."""
        return APIModule.SCENE_RECONSTRUCTION

    # ========================================================================
    # DOWNLOAD GLB FROM URL
    # ========================================================================

    def download_glb_from_url(
        self, url: str, timeout: float = 120.0, max_retries: int = 3,
    ) -> bytes:
        """
        Download a GLB file from an S3 presigned URL.

        Uses requests directly (not the HTTPClient) since the URL is an
        external S3 presigned URL, not a backend API endpoint.
        Retries with exponential backoff on connection errors.

        Args:
            url: S3 presigned URL for the GLB file
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts

        Returns:
            Raw GLB bytes
        """
        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                response = requests.get(url, timeout=timeout)
                response.raise_for_status()
                return response.content
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                if attempt < max_retries:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning("[SceneRecon] Download retry %s/%s after %ss: %s",
                                   attempt + 1, max_retries, wait, e)
                    time.sleep(wait)
        raise last_exc


# Singleton instance
_scene_recon_service: Optional[SceneReconService] = None


def get_scene_recon_service() -> SceneReconService:
    """Get or create the global Scene Reconstruction service instance."""
    global _scene_recon_service
    if _scene_recon_service is None:
        _scene_recon_service = SceneReconService()
    return _scene_recon_service
