# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Segment API service for image segmentation.

Provides API integration for the Scene Segment (SAM3) service with
job-based upload, point segmentation, polling, and mask download.
"""

from typing import Any, Callable, Dict, List, Optional

from ..constants import APIModule
from ..request_queue import AsyncResponse
from ..response import APIResponse
from .base_service import BaseService


class SceneSegmentService(BaseService):
    """
    Scene Segment (SAM3) service.

    Endpoints (/api/v1/scene-segment/):
    - POST /upload - Upload image, returns job_id
    - POST /segment/point - Point segmentation, returns request_id
    - GET /jobs/{job_id} - Poll job status
    - GET /download/{job_id}/{request_id} - Download mask PNG
    - DELETE /jobs/{job_id} - Delete job
    - GET /health - Health check
    - GET /queue/status - Queue status
    """

    @property
    def module(self) -> APIModule:
        """Return the SCENE_SEGMENT module."""
        return APIModule.SCENE_SEGMENT

    # ========================================================================
    # UPLOAD IMAGE
    # ========================================================================

    def upload_image(
        self,
        image_bytes: bytes,
        filename: str = "image.png",
    ) -> APIResponse:
        """
        Upload an image to create a segmentation job.

        Args:
            image_bytes: Image data (PNG, JPG, or WEBP)
            filename: Filename for the upload

        Returns:
            APIResponse with data containing:
            - job_id: Unique job identifier
            - status: "ready"
            - image_size: {width, height}
            - expires_at: ISO timestamp
        """
        mime_type = self._get_mime_type(filename)
        files = {"image": (filename, image_bytes, mime_type)}
        return self._client.post(self._endpoint("upload"), files=files)

    def upload_image_async(
        self,
        image_bytes: bytes,
        filename: str = "image.png",
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
        timeout: float = 120.0,
    ) -> str:
        """
        Upload an image asynchronously.

        Args:
            image_bytes: Image data (PNG, JPG, or WEBP)
            filename: Filename for the upload
            on_success: Success callback
            on_error: Error callback
            on_complete: Completion callback
            timeout: Request timeout in seconds (default 120s for AI processing)

        Returns:
            Request ID for tracking
        """
        mime_type = self._get_mime_type(filename)
        files = {"image": (filename, image_bytes, mime_type)}
        return self._client.request_async(
            "POST",
            self._endpoint("upload"),
            files=files,
            timeout=timeout,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    # ========================================================================
    # POINT SEGMENTATION
    # ========================================================================

    def segment_point(
        self,
        job_id: str,
        points: List[Dict[str, Any]],
        text: Optional[str] = None,
    ) -> APIResponse:
        """
        Request point-based segmentation.

        Args:
            job_id: Job ID from upload
            points: List of point dicts with x, y (0-1 normalized), label (1=include, 0=exclude)
                    Example: [{"x": 0.5, "y": 0.3, "label": 1}]
            text: Optional text prompt for refinement

        Returns:
            APIResponse with data containing:
            - job_id: Job identifier
            - request_id: Request identifier for this segmentation
            - status: "queued"
            - queue_position: Position in queue
        """
        payload: Dict[str, Any] = {"job_id": job_id, "points": points}
        if text:
            payload["text"] = text
        return self._client.post(self._endpoint("segment/point"), json=payload)

    def segment_point_async(
        self,
        job_id: str,
        points: List[Dict[str, Any]],
        text: Optional[str] = None,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Request point-based segmentation asynchronously.

        Args:
            job_id: Job ID from upload
            points: List of point dicts with x, y (0-1 normalized), label (1=include, 0=exclude)
            text: Optional text prompt for refinement
            on_success: Success callback
            on_error: Error callback
            on_complete: Completion callback

        Returns:
            Request ID for tracking
        """
        payload: Dict[str, Any] = {"job_id": job_id, "points": points}
        if text:
            payload["text"] = text
        return self._client.request_async(
            "POST",
            self._endpoint("segment/point"),
            json=payload,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    # ========================================================================
    # BOX SEGMENTATION
    # ========================================================================

    def segment_box(
        self,
        job_id: str,
        box: Dict[str, float],
        text: Optional[str] = None,
    ) -> APIResponse:
        """
        Request box-based segmentation.

        Args:
            job_id: Job ID from upload
            box: Box dict with x_min, y_min, x_max, y_max (0-1 normalized)
                 Example: {"x_min": 0.1, "y_min": 0.2, "x_max": 0.8, "y_max": 0.9}
            text: Optional text prompt for refinement

        Returns:
            APIResponse with request_id, status, queue_position
        """
        payload: Dict[str, Any] = {"job_id": job_id, "box": box}
        if text:
            payload["text"] = text
        return self._client.post(self._endpoint("segment/box"), json=payload)

    def segment_box_async(
        self,
        job_id: str,
        box: Dict[str, float],
        text: Optional[str] = None,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Request box-based segmentation asynchronously.

        Args:
            job_id: Job ID from upload
            box: Box dict with x_min, y_min, x_max, y_max (0-1 normalized)
            text: Optional text prompt for refinement
            on_success: Success callback
            on_error: Error callback
            on_complete: Completion callback

        Returns:
            Request ID for tracking
        """
        payload: Dict[str, Any] = {"job_id": job_id, "box": box}
        if text:
            payload["text"] = text
        return self._client.request_async(
            "POST",
            self._endpoint("segment/box"),
            json=payload,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    # ========================================================================
    # MASK SEGMENTATION (for Lasso refinement)
    # ========================================================================

    def segment_mask(
        self,
        job_id: str,
        mask_bytes: bytes,
        mask_filename: str = "mask.png",
        text: Optional[str] = None,
    ) -> APIResponse:
        """
        Request mask-based segmentation (for lasso refinement).

        Args:
            job_id: Job ID from upload
            mask_bytes: Binary mask PNG (white=selected, black=background)
            mask_filename: Filename for the mask
            text: Optional text prompt for refinement

        Returns:
            APIResponse with request_id, status, queue_position
        """
        files = {"mask": (mask_filename, mask_bytes, "image/png")}
        data: Dict[str, Any] = {"job_id": job_id}
        if text:
            data["text"] = text
        return self._client.post(self._endpoint("segment/mask"), files=files, data=data)

    def segment_mask_async(
        self,
        job_id: str,
        mask_bytes: bytes,
        mask_filename: str = "mask.png",
        text: Optional[str] = None,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Request mask-based segmentation asynchronously.

        Args:
            job_id: Job ID from upload
            mask_bytes: Binary mask PNG (white=selected, black=background)
            mask_filename: Filename for the mask
            text: Optional text prompt for refinement
            on_success: Success callback
            on_error: Error callback
            on_complete: Completion callback

        Returns:
            Request ID for tracking
        """
        files = {"mask": (mask_filename, mask_bytes, "image/png")}
        data: Dict[str, Any] = {"job_id": job_id}
        if text:
            data["text"] = text
        return self._client.request_async(
            "POST",
            self._endpoint("segment/mask"),
            files=files,
            data=data,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    # ========================================================================
    # GET JOB STATUS (POLLING)
    # ========================================================================

    def get_job_status(self, job_id: str) -> APIResponse:
        """
        Poll job status to check request completion.

        Args:
            job_id: Job ID from upload

        Returns:
            APIResponse with data containing:
            - job_id: Job identifier
            - status: "active" or "expired"
            - requests: List of request objects with status, download_url
        """
        return self._client.get(self._endpoint(f"jobs/{job_id}"))

    def get_job_status_async(
        self,
        job_id: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
        timeout: float = 30.0,
    ) -> str:
        """
        Poll job status asynchronously.

        Args:
            job_id: Job ID from upload
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
            timeout=timeout,
        )

    # ========================================================================
    # DOWNLOAD MASK
    # ========================================================================

    def download_mask(
        self,
        job_id: str,
        request_id: str,
    ) -> APIResponse:
        """
        Download the segmentation mask.

        Args:
            job_id: Job ID from upload
            request_id: Request ID from segment_point

        Returns:
            APIResponse with raw PNG bytes in response.raw.content
        """
        return self._client.get(
            self._endpoint(f"download/{job_id}/{request_id}"),
        )

    def download_mask_async(
        self,
        job_id: str,
        request_id: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
        timeout: float = 30.0,
    ) -> str:
        """
        Download the segmentation mask asynchronously.

        Args:
            job_id: Job ID from upload
            request_id: Request ID from segment_point
            on_success: Success callback
            on_error: Error callback
            on_complete: Completion callback

        Returns:
            Request ID for tracking
        """
        return self._client.request_async(
            "GET",
            self._endpoint(f"download/{job_id}/{request_id}"),
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
            timeout=timeout,
        )

    # ========================================================================
    # DELETE JOB
    # ========================================================================

    def delete_job(self, job_id: str) -> APIResponse:
        """
        Delete a job and all associated data.

        Args:
            job_id: Job ID from upload

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
            job_id: Job ID from upload
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

    def health_check(self) -> APIResponse:
        """
        Check service health.

        Returns:
            APIResponse with health status, model_loaded, gpu_available
        """
        return self._client.get(self._endpoint("health"))

    def get_queue_status(self) -> APIResponse:
        """
        Get current queue status.

        Returns:
            APIResponse with queue_length, currently_processing, queued_requests
        """
        return self._client.get(self._endpoint("queue/status"))

    def _get_mime_type(self, filename: str) -> str:
        """Determine MIME type from filename."""
        lower = filename.lower()
        if lower.endswith(('.jpg', '.jpeg')):
            return "image/jpeg"
        elif lower.endswith('.webp'):
            return "image/webp"
        return "image/png"


# Singleton instance
_scene_segment_service: Optional[SceneSegmentService] = None


def get_scene_segment_service() -> SceneSegmentService:
    """Get or create the global Scene Segment service instance."""
    global _scene_segment_service
    if _scene_segment_service is None:
        _scene_segment_service = SceneSegmentService()
    return _scene_segment_service
