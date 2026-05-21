# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Generation Service for 3D model generation from images and masks.

Provides API integration for the job-based scene generation service with
submit, poll, download, and cancel endpoints.
"""

from typing import Callable, List, Optional

from ..constants import APIModule
from ..request_queue import AsyncResponse
from ..response import APIResponse
from .base_service import BaseService


class SceneGenService(BaseService):
    """
    Scene Generation service.

    Endpoints (base path /api/v1/scene-gen/):
    - POST /generate - Submit generation job
    - GET /jobs/{job_id} - Poll job status
    - GET /jobs/{job_id}/objects/{download_token} - Download GLB
    - DELETE /jobs/{job_id} - Cancel/delete job
    - GET /health - Service health check
    - GET /queue/status - Queue status
    """

    @property
    def module(self) -> APIModule:
        """Return the SCENE_GEN module."""
        return APIModule.SCENE_GEN

    # ========================================================================
    # GENERATE (Submit Job)
    # ========================================================================

    def generate(
        self,
        image_bytes: bytes,
        mask_bytes_list: List[bytes],
        texture_size: int = 1024,
        simplify: float = 0.95,
        seed: Optional[int] = None,
    ) -> APIResponse:
        """
        Submit a scene generation job.

        Args:
            image_bytes: Source image PNG/JPEG data
            mask_bytes_list: List of binary mask PNG data (one per object)
            texture_size: Texture resolution (512, 1024, 2048, 4096)
            simplify: Mesh simplification ratio [0-1]
            seed: Optional random seed for reproducibility

        Returns:
            APIResponse with job_id, status, poll_url
        """
        files = [("image", ("image.png", image_bytes, "image/png"))]
        for i, mask_bytes in enumerate(mask_bytes_list):
            files.append(("masks", (f"mask_{i}.png", mask_bytes, "image/png")))

        data = {
            "texture_size": str(texture_size),
            "simplify": str(simplify),
        }
        if seed is not None:
            data["seed"] = str(seed)

        return self._client.post(
            self._endpoint("generate"),
            files=files,
            data=data,
            timeout=60.0,
        )

    def generate_async(
        self,
        image_bytes: bytes,
        mask_bytes_list: List[bytes],
        texture_size: int = 1024,
        simplify: float = 0.95,
        seed: Optional[int] = None,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Submit a scene generation job asynchronously.

        Args:
            image_bytes: Source image PNG/JPEG data
            mask_bytes_list: List of binary mask PNG data
            texture_size: Texture resolution
            simplify: Mesh simplification ratio
            seed: Optional random seed
            on_success: Success callback
            on_error: Error callback
            on_complete: Completion callback

        Returns:
            Request ID for tracking
        """
        files = [("image", ("image.png", image_bytes, "image/png"))]
        for i, mask_bytes in enumerate(mask_bytes_list):
            files.append(("masks", (f"mask_{i}.png", mask_bytes, "image/png")))

        data = {
            "texture_size": str(texture_size),
            "simplify": str(simplify),
        }
        if seed is not None:
            data["seed"] = str(seed)

        return self._client.request_async(
            "POST",
            self._endpoint("generate"),
            files=files,
            data=data,
            timeout=60.0,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    # ========================================================================
    # GET JOB STATUS
    # ========================================================================

    def get_job_status(self, job_id: str) -> APIResponse:
        """
        Poll job status.

        Args:
            job_id: The job identifier

        Returns:
            APIResponse with job status, objects array with download_tokens and pose data
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
            job_id: The job identifier
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
    # DOWNLOAD OBJECT
    # ========================================================================

    def download_object(self, job_id: str, download_token: str) -> APIResponse:
        """
        Download a generated GLB object.

        Args:
            job_id: The job identifier
            download_token: Download token from job status response

        Returns:
            APIResponse with raw GLB bytes in response.raw.content
        """
        return self._client.get(
            self._endpoint(f"jobs/{job_id}/objects/{download_token}"),
            timeout=120.0,
        )

    def download_object_async(
        self,
        job_id: str,
        download_token: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Download a generated GLB object asynchronously.

        Args:
            job_id: The job identifier
            download_token: Download token from job status response
            on_success: Success callback
            on_error: Error callback
            on_complete: Completion callback

        Returns:
            Request ID for tracking
        """
        return self._client.request_async(
            "GET",
            self._endpoint(f"jobs/{job_id}/objects/{download_token}"),
            timeout=120.0,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    # ========================================================================
    # DELETE JOB
    # ========================================================================

    def delete_job(self, job_id: str) -> APIResponse:
        """
        Cancel or delete a job.

        Args:
            job_id: The job identifier

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
        Cancel or delete a job asynchronously.

        Args:
            job_id: The job identifier
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
    # HEALTH CHECK
    # ========================================================================

    def health_check(self) -> APIResponse:
        """
        Check service health.

        Returns:
            APIResponse with health status, model_loaded, gpu_available, queue_length
        """
        return self._client.get(self._endpoint("health"))

    # ========================================================================
    # QUEUE STATUS
    # ========================================================================

    def get_queue_status(self) -> APIResponse:
        """
        Get queue status information.

        Returns:
            APIResponse with queue_length, currently_processing, queued_jobs
        """
        return self._client.get(self._endpoint("queue/status"))


# Singleton instance
_scene_gen_service: Optional[SceneGenService] = None


def get_scene_gen_service() -> SceneGenService:
    """Get or create the global Scene Generation service instance."""
    global _scene_gen_service
    if _scene_gen_service is None:
        _scene_gen_service = SceneGenService()
    return _scene_gen_service
