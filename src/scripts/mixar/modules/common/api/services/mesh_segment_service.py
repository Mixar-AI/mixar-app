# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Mesh Segment API Service.

Handles /api/v1/mesh-segment endpoints for UV segmentation of meshes.
"""

from typing import BinaryIO, Callable, Dict, Optional, Union

from ....auth.core.auth import get_access_token
from ..constants import APIModule
from ..exceptions import AuthenticationError
from ..request_queue import AsyncResponse
from ..response import APIResponse
from .base_service import BaseService


def _require_auth() -> None:
    """Raise AuthenticationError if no access token is available."""
    token = get_access_token()
    if not token:
        raise AuthenticationError(
            message="Authentication required. Please login first.",
            status_code=401,
        )


class MeshSegmentService(BaseService):
    """
    Mesh Segment service for UV mesh segmentation.

    Endpoints:
    - POST / - Submit a segmentation job
    - GET /{job_id} - Get job status
    - GET /{job_id}/result - Get job result
    - DELETE /{job_id} - Cancel/delete a job
    """

    @property
    def module(self) -> APIModule:
        return APIModule.MESH_SEGMENT

    # ========================================================================
    # SYNC METHODS
    # ========================================================================

    def submit_job(
        self,
        mesh_file: Union[BinaryIO, bytes, str],
        description: str,
        expected_parts: str,
        mesh_filename: str = "mesh.obj",
    ) -> APIResponse:
        """
        Submit a mesh for UV segmentation.

        Args:
            mesh_file: Mesh file (file object, bytes, or file path) - required
            description: Description of the mesh for segmentation context
            expected_parts: Comma-separated list of expected parts
            mesh_filename: Filename for the mesh file (used in multipart)

        Returns:
            APIResponse with job_id and initial status

        Raises:
            AuthenticationError: If no access token is available
        """
        _require_auth()

        # Handle different mesh_file input types
        if isinstance(mesh_file, str):
            with open(mesh_file, "rb") as f:
                file_content = f.read()
            files = {"mesh": (mesh_filename, file_content)}
        elif isinstance(mesh_file, bytes):
            files = {"mesh": (mesh_filename, mesh_file)}
        else:
            files = {"mesh": (mesh_filename, mesh_file)}

        data = {
            "description": description,
            "expected_parts": expected_parts,
        }

        return self.post("/", files=files, data=data)

    def get_status(self, job_id: str) -> APIResponse:
        """
        Get the status of a segmentation job.

        Args:
            job_id: The job identifier

        Returns:
            APIResponse with job status, progress, and current_step

        Raises:
            AuthenticationError: If no access token is available
        """
        _require_auth()
        return self.get(job_id)

    def get_result(self, job_id: str) -> APIResponse:
        """
        Get the result of a completed segmentation job.

        Args:
            job_id: The job identifier

        Returns:
            APIResponse with island_labels and segmentation data

        Raises:
            AuthenticationError: If no access token is available
        """
        _require_auth()
        return self.get(f"{job_id}/result")

    def delete_job(self, job_id: str) -> APIResponse:
        """
        Cancel or delete a segmentation job.

        Args:
            job_id: The job identifier

        Returns:
            APIResponse confirming deletion

        Raises:
            AuthenticationError: If no access token is available
        """
        _require_auth()
        return self.delete(job_id)

    # ========================================================================
    # ASYNC METHODS
    # ========================================================================

    def submit_job_async(
        self,
        mesh_file: Union[BinaryIO, bytes, str],
        description: str,
        expected_parts: str,
        mesh_filename: str = "mesh.obj",
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Submit a mesh for UV segmentation asynchronously.

        Args:
            mesh_file: Mesh file (file object, bytes, or file path) - required
            description: Description of the mesh for segmentation context
            expected_parts: Comma-separated list of expected parts
            mesh_filename: Filename for the mesh file
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking

        Raises:
            AuthenticationError: If no access token is available
        """
        _require_auth()

        # Read file content on main thread for thread safety
        if isinstance(mesh_file, str):
            with open(mesh_file, "rb") as f:
                file_content = f.read()
            files = {"mesh": (mesh_filename, file_content)}
        elif isinstance(mesh_file, bytes):
            files = {"mesh": (mesh_filename, mesh_file)}
        else:
            file_content = mesh_file.read()
            files = {"mesh": (mesh_filename, file_content)}

        data = {
            "description": description,
            "expected_parts": expected_parts,
        }

        return self.post_async(
            "/",
            files=files,
            data=data,
            timeout=60.0,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    def get_status_async(
        self,
        job_id: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Get the status of a segmentation job asynchronously.

        Args:
            job_id: The job identifier
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking

        Raises:
            AuthenticationError: If no access token is available
        """
        _require_auth()
        return self.get_async(
            job_id,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    def get_result_async(
        self,
        job_id: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Get the result of a completed segmentation job asynchronously.

        Args:
            job_id: The job identifier
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking

        Raises:
            AuthenticationError: If no access token is available
        """
        _require_auth()
        return self.get_async(
            f"{job_id}/result",
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )

    def delete_job_async(
        self,
        job_id: str,
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Cancel or delete a segmentation job asynchronously.

        Args:
            job_id: The job identifier
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking

        Raises:
            AuthenticationError: If no access token is available
        """
        _require_auth()
        return self.delete_async(
            job_id,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )


# Singleton instance
_mesh_segment_service: Optional[MeshSegmentService] = None


def get_mesh_segment_service() -> MeshSegmentService:
    """Get the global MeshSegmentService instance."""
    global _mesh_segment_service
    if _mesh_segment_service is None:
        _mesh_segment_service = MeshSegmentService()
    return _mesh_segment_service
