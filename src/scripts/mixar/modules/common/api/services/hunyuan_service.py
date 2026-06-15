# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Hunyuan 3D API Service.

Handles Hunyuan 3D generation endpoints:
- POST /3d-pro/generate:      High-quality 3D from text/image/multi-view
- POST /3d-rapid/generate:    Fast 3D from text/image
- POST /3d-part/generate:     Decompose FBX into parts
- POST /3d-topology/generate: AI retopology
- POST /3d-uv/generate:       AI UV unwrapping
- GET  /jobs/{job_id}:        Poll job status
"""

from typing import Callable, List, Optional, Tuple

from mixar.config.logging_config import get_logger

from ....auth.core.auth import get_access_token
from ..constants import APIModule, HUNYUAN_TIMEOUT
from ..exceptions import AuthenticationError
from ..request_queue import AsyncResponse
from ..response import APIResponse
from .base_service import BaseService

logger = get_logger(__name__)


def _require_auth() -> None:
    """Raise AuthenticationError if no access token is available."""
    token = get_access_token()
    if not token:
        raise AuthenticationError(
            message="Authentication required. Please login first.",
            status_code=401,
        )


def _mime(filename: str) -> str:
    """Determine MIME type from filename extension."""
    lower = filename.lower()
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    elif lower.endswith(".webp"):
        return "image/webp"
    return "image/png"


class HunyuanService(BaseService):
    """
    Hunyuan 3D service for AI-powered 3D generation.

    Provides:
    - 5 async submit methods (Pro, Rapid, Part, Topology, UV)
    - 1 async poll method for job status
    """

    @property
    def module(self) -> APIModule:
        return APIModule.HUNYUAN

    # ========================================================================
    # SUBMIT METHODS
    # ========================================================================

    def submit_3d_pro_async(
        self,
        *,
        prompt: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        image_filename: str = "image.png",
        multi_view_images: Optional[List[Tuple[bytes, str, str]]] = None,
        enable_pbr: bool = False,
        face_count: Optional[int] = None,
        generate_type: str = "Normal",
        polygon_type: Optional[str] = None,
        model: str = "3.0",
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Submit a Hunyuan 3D Pro generation job.

        Args:
            prompt: Text description (max 1024 chars)
            image_bytes: Main reference image bytes
            image_filename: Filename for the main image
            multi_view_images: List of (bytes, filename, view_type) tuples
            enable_pbr: Whether to generate PBR textures
            face_count: Target face count (40K-1.5M)
            generate_type: Normal, LowPoly, Geometry, or Sketch
            polygon_type: triangle or quadrilateral (for LowPoly)
            model: Model version (3.0 or 3.1)
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        _require_auth()

        files = []
        if prompt:
            files.append(("prompt", (None, prompt)))
        if image_bytes:
            files.append(("image", (image_filename, image_bytes, _mime(image_filename))))
        if multi_view_images:
            for img_bytes, img_filename, view_type in multi_view_images:
                files.append(("multi_view_images", (img_filename, img_bytes, _mime(img_filename))))
                files.append(("multi_view_types", (None, view_type)))
        files.append(("enable_pbr", (None, str(enable_pbr).lower())))
        if face_count is not None:
            files.append(("face_count", (None, str(face_count))))
        files.append(("generate_type", (None, generate_type)))
        if polygon_type:
            files.append(("polygon_type", (None, polygon_type)))
        files.append(("model", (None, model)))

        return self.post_async(
            "3d-pro/generate",
            files=files,
            timeout=HUNYUAN_TIMEOUT,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    def submit_3d_rapid_async(
        self,
        *,
        prompt: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        image_filename: str = "image.png",
        result_format: Optional[str] = None,
        enable_pbr: bool = False,
        enable_geometry: bool = False,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Submit a Hunyuan 3D Rapid generation job.

        Args:
            prompt: Text description (max 200 chars)
            image_bytes: Reference image bytes
            image_filename: Filename for the image
            result_format: Output format (glb, obj, stl, usdz, fbx, mp4, gif)
            enable_pbr: Whether to generate PBR textures
            enable_geometry: Whether to generate geometry-only
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        _require_auth()

        files = []
        if prompt:
            files.append(("prompt", (None, prompt)))
        if image_bytes:
            files.append(("image", (image_filename, image_bytes, _mime(image_filename))))
        if result_format:
            files.append(("result_format", (None, result_format)))
        files.append(("enable_pbr", (None, str(enable_pbr).lower())))
        files.append(("enable_geometry", (None, str(enable_geometry).lower())))

        return self.post_async(
            "3d-rapid/generate",
            files=files,
            timeout=HUNYUAN_TIMEOUT,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    def submit_3d_part_async(
        self,
        *,
        file_bytes: bytes,
        file_filename: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Submit a Hunyuan 3D Part decomposition job.

        Args:
            file_bytes: FBX file bytes
            file_filename: Filename for the file
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        _require_auth()

        files = [("file", (file_filename, file_bytes, "application/octet-stream"))]

        return self.post_async(
            "3d-part/generate",
            files=files,
            timeout=HUNYUAN_TIMEOUT,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    def submit_3d_topology_async(
        self,
        *,
        file_bytes: bytes,
        file_filename: str,
        polygon_type: Optional[str] = None,
        face_level: Optional[str] = None,
        input_name: Optional[str] = None,
        post_process: bool = True,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Submit a Hunyuan 3D Topology retopology job.

        Args:
            file_bytes: GLB or OBJ file bytes
            file_filename: Filename for the file
            polygon_type: triangle or quadrilateral
            face_level: high, medium, or low
            input_name: Original mesh name for LP naming in post-processing
            post_process: Whether to run GPU post-processing (pivot, scale, UV, bake)
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        _require_auth()

        files = [("file", (file_filename, file_bytes, "application/octet-stream"))]
        if polygon_type:
            files.append(("polygon_type", (None, polygon_type)))
        if face_level:
            files.append(("face_level", (None, face_level)))
        if input_name:
            files.append(("input_name", (None, input_name)))
        files.append(("post_process", (None, "true" if post_process else "false")))

        return self.post_async(
            "3d-topology/generate",
            files=files,
            timeout=HUNYUAN_TIMEOUT,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    def submit_3d_uv_async(
        self,
        *,
        file_bytes: bytes,
        file_filename: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Submit a Hunyuan 3D UV unwrapping job.

        Args:
            file_bytes: FBX, OBJ, or GLB file bytes
            file_filename: Filename for the file
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        _require_auth()

        files = [("file", (file_filename, file_bytes, "application/octet-stream"))]

        return self.post_async(
            "3d-uv/generate",
            files=files,
            timeout=HUNYUAN_TIMEOUT,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    # ========================================================================
    # POLL METHOD
    # ========================================================================

    def poll_job_async(
        self,
        job_id: str,
        api_type: Optional[str] = None,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Poll a Hunyuan job for status.

        GET /hunyuan/jobs/{job_id}?api_type=...

        Args:
            job_id: The job ID to poll
            api_type: The API type (e.g., "3d-pro")
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking
        """
        _require_auth()

        params = {}
        if api_type:
            params["api_type"] = api_type

        return self.get_async(
            f"jobs/{job_id}",
            params=params,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )


# Singleton instance
_hunyuan_service: Optional[HunyuanService] = None


def get_hunyuan_service() -> HunyuanService:
    """Get the global HunyuanService instance."""
    global _hunyuan_service
    if _hunyuan_service is None:
        _hunyuan_service = HunyuanService()
    return _hunyuan_service
