# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Reconstruction API service.

Provides API integration for the Scene Reconstruction service with
job-based upload, status polling, and result download.
"""

import time
from typing import Callable, Optional

import requests

from mixar.config.logging_config import get_logger

from ..constants import APIModule
from ..request_queue import AsyncResponse
from ..response import APIResponse
from .base_service import BaseService

logger = get_logger(__name__)


class SceneReconService(BaseService):
    """
    Scene Reconstruction service.

    Endpoints (/api/v1/scene-reconstruction/):
    - GET /health - Health check
    - POST /jobs - Submit reconstruction job (image upload)
    - GET /jobs/{job_id} - Poll job status
    - GET /jobs/{job_id}/result - Download .npz result file
    - DELETE /jobs/{job_id} - Delete job
    """

    @property
    def module(self) -> APIModule:
        """Return the SCENE_RECONSTRUCTION module."""
        return APIModule.SCENE_RECONSTRUCTION

    # ========================================================================
    # HEALTH CHECK
    # ========================================================================

    def health_check(self) -> APIResponse:
        """
        Check service health.

        Returns:
            APIResponse with status, gpu_memory info, active_job
        """
        return self._client.get(self._endpoint("health"))

    # ========================================================================
    # SUBMIT JOB
    # ========================================================================

    def submit_job(
        self,
        image_bytes: bytes,
        filename: str = "image.png",
        skip_vlm: bool = False,
        categories: Optional[str] = None,
        seed: int = 42,
        generate_mesh: bool = True,
        min_mask_pixels: int = 2000,
        mesh_postprocess: bool = True,
        texture_baking: bool = False,
        vertex_color: bool = True,
        labels_only: bool = False,
    ) -> APIResponse:
        """
        Submit a scene reconstruction job.

        Args:
            image_bytes: Image data (PNG, JPG, or WEBP)
            filename: Filename for the upload
            skip_vlm: Skip VLM detection/verification stages
            categories: Comma-separated object categories (auto-detect if omitted)
            seed: Random seed for reproducibility
            generate_mesh: Generate GLB meshes per object (default True)
            min_mask_pixels: Minimum segment size in pixels (default 2000)
            mesh_postprocess: Simplify mesh via decimation and fill holes (default True)
            texture_baking: Bake textures onto mesh UVs (default False)
            vertex_color: Use vertex colors instead of baked textures (default True)
            labels_only: If true, skip 3D reconstruction; return labels + bboxes only

        Returns:
            APIResponse with data containing:
            - job_id: Unique job identifier
            - status: "queued"
            - created_at: Unix timestamp
        """
        mime_type = self._get_mime_type(filename)
        files = {"image": (filename, image_bytes, mime_type)}
        data = {
            "skip_vlm": str(skip_vlm).lower(),
            "seed": str(seed),
            "generate_mesh": str(generate_mesh).lower(),
            "min_mask_pixels": str(min_mask_pixels),
            "mesh_postprocess": str(mesh_postprocess).lower(),
            "texture_baking": str(texture_baking).lower(),
            "vertex_color": str(vertex_color).lower(),
        }
        if labels_only:
            data["labels_only"] = "true"
        if categories:
            data["categories"] = categories
        return self._client.post(self._endpoint("jobs"), files=files, data=data)

    def submit_job_async(
        self,
        image_bytes: bytes,
        filename: str = "image.png",
        skip_vlm: bool = False,
        categories: Optional[str] = None,
        seed: int = 42,
        generate_mesh: bool = True,
        min_mask_pixels: int = 2000,
        mesh_postprocess: bool = True,
        texture_baking: bool = False,
        vertex_color: bool = True,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
        timeout: float = 120.0,
    ) -> str:
        """
        Submit a scene reconstruction job asynchronously.

        Args:
            image_bytes: Image data (PNG, JPG, or WEBP)
            filename: Filename for the upload
            skip_vlm: Skip VLM detection/verification stages
            categories: Comma-separated object categories
            seed: Random seed
            generate_mesh: Generate GLB meshes per object (default True)
            min_mask_pixels: Minimum segment size in pixels (default 2000)
            mesh_postprocess: Simplify mesh via decimation and fill holes (default True)
            texture_baking: Bake textures onto mesh UVs (default False)
            vertex_color: Use vertex colors instead of baked textures (default True)
            on_success: Success callback
            on_error: Error callback
            on_complete: Completion callback
            timeout: Request timeout in seconds

        Returns:
            Request ID for tracking
        """
        mime_type = self._get_mime_type(filename)
        files = {"image": (filename, image_bytes, mime_type)}
        data = {
            "skip_vlm": str(skip_vlm).lower(),
            "seed": str(seed),
            "generate_mesh": str(generate_mesh).lower(),
            "min_mask_pixels": str(min_mask_pixels),
            "mesh_postprocess": str(mesh_postprocess).lower(),
            "texture_baking": str(texture_baking).lower(),
            "vertex_color": str(vertex_color).lower(),
        }
        if categories:
            data["categories"] = categories
        return self._client.request_async(
            "POST",
            self._endpoint("jobs"),
            files=files,
            data=data,
            timeout=timeout,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    # ========================================================================
    # GET JOB STATUS (POLLING)
    # ========================================================================

    def get_job_status(self, job_id: str) -> APIResponse:
        """
        Poll job status.

        Args:
            job_id: Job ID from submit

        Returns:
            APIResponse with data containing:
            - job_id, status, stage, stage_name, stage_detail,
              elapsed_seconds, error, summary
        """
        return self._client.get(self._endpoint(f"jobs/{job_id}"))

    def get_job_status_async(
        self,
        job_id: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Poll job status asynchronously.

        Args:
            job_id: Job ID from submit
            on_success: Success callback
            on_error: Error callback
            on_complete: Completion callback

        Returns:
            Request ID for tracking
        """
        return self._client.request_async(
            "GET",
            self._endpoint(f"jobs/{job_id}"),
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

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

    # ========================================================================
    # DELETE JOB
    # ========================================================================

    def delete_job(self, job_id: str) -> APIResponse:
        """
        Delete a job and its temporary files.

        Args:
            job_id: Job ID from submit

        Returns:
            APIResponse with deletion status
        """
        return self._client.delete(self._endpoint(f"jobs/{job_id}"))

    def delete_job_async(
        self,
        job_id: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Delete a job asynchronously.

        Args:
            job_id: Job ID from submit
            on_success: Success callback
            on_error: Error callback
            on_complete: Completion callback

        Returns:
            Request ID for tracking
        """
        return self._client.request_async(
            "DELETE",
            self._endpoint(f"jobs/{job_id}"),
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    # ========================================================================
    # UTILITIES
    # ========================================================================

    def _get_mime_type(self, filename: str) -> str:
        """Determine MIME type from filename."""
        lower = filename.lower()
        if lower.endswith(('.jpg', '.jpeg')):
            return "image/jpeg"
        elif lower.endswith('.webp'):
            return "image/webp"
        return "image/png"


# Singleton instance
_scene_recon_service: Optional[SceneReconService] = None


def get_scene_recon_service() -> SceneReconService:
    """Get or create the global Scene Reconstruction service instance."""
    global _scene_recon_service
    if _scene_recon_service is None:
        _scene_recon_service = SceneReconService()
    return _scene_recon_service
