# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Lookdev 3D API Service.

Handles /api/v1/lookdev/generate-3d endpoint for 3D model generation from images.
"""

from typing import BinaryIO, Callable, Optional, Union

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


class Lookdev3DService(BaseService):
    """
    Lookdev 3D service for generating 3D models from images.

    Uses Replicate's Trellis model for image-to-3D generation.

    Endpoints:
    - POST /generate-3d - Generate 3D model from an image
    """

    @property
    def module(self) -> APIModule:
        return APIModule.LOOKDEV

    # ========================================================================
    # SYNC METHODS
    # ========================================================================

    def generate(
        self,
        image: Union[BinaryIO, bytes, str],
        prompt: Optional[str] = None,
        image_filename: str = "image.png",
    ) -> APIResponse:
        """
        Generate a 3D model from an image using Replicate's Trellis model.

        Args:
            image: Input image file (file object, bytes, or file path) - required
            prompt: Text prompt to guide 3D generation
            image_filename: Filename for the image (used in multipart)

        Returns:
            APIResponse with generated 3D model data

        Raises:
            AuthenticationError: If no access token is available
        """
        _require_auth()

        # Handle different image input types
        if isinstance(image, str):
            # It's a file path
            with open(image, "rb") as f:
                file_content = f.read()
            files = {"image": (image_filename, file_content)}
        elif isinstance(image, bytes):
            files = {"image": (image_filename, image)}
        else:
            # Assume it's a file-like object
            files = {"image": (image_filename, image)}

        # Build form data with optional parameters
        data = {}
        if prompt is not None:
            data["prompt"] = prompt

        return self.post("generate-3d", files=files, data=data if data else None)

    # ========================================================================
    # ASYNC METHODS
    # ========================================================================

    def generate_async(
        self,
        image: Union[BinaryIO, bytes, str],
        prompt: Optional[str] = None,
        image_filename: str = "image.png",
        on_success: Optional[Callable[[APIResponse], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_complete: Optional[Callable[[AsyncResponse], None]] = None,
    ) -> str:
        """
        Generate a 3D model from an image asynchronously.

        Args:
            image: Input image file (file object, bytes, or file path) - required
            prompt: Text prompt to guide 3D generation
            image_filename: Filename for the image
            on_success: Callback for successful response
            on_error: Callback for errors
            on_complete: Callback with full AsyncResponse

        Returns:
            Request ID for tracking

        Raises:
            AuthenticationError: If no access token is available
        """
        _require_auth()

        # Handle different image input types
        # For async, we need to read the file content on the main thread
        if isinstance(image, str):
            # It's a file path - read it now
            with open(image, "rb") as f:
                file_content = f.read()
            files = {"image": (image_filename, file_content)}
        elif isinstance(image, bytes):
            files = {"image": (image_filename, image)}
        else:
            # Assume it's a file-like object - read it now for thread safety
            file_content = image.read()
            files = {"image": (image_filename, file_content)}

        # Build form data with optional parameters
        data = {}
        if prompt is not None:
            data["prompt"] = prompt

        return self.post_async(
            "generate-3d",
            files=files,
            data=data if data else None,
            on_success=on_success,
            on_error=on_error,
            on_complete=on_complete,
        )


# Singleton instance
_lookdev_3d_service: Optional[Lookdev3DService] = None


def get_lookdev_3d_service() -> Lookdev3DService:
    """Get the global Lookdev3DService instance."""
    global _lookdev_3d_service
    if _lookdev_3d_service is None:
        _lookdev_3d_service = Lookdev3DService()
    return _lookdev_3d_service
